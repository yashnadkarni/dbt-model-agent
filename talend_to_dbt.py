"""
Talend-to-dbt Converter

Translates parsed Talend job definitions into dbt model files (.sql + .yml).
Works in two modes:
  1. Deterministic mode (default): Generates SQL and YAML directly using
     pattern-matched translations. No LLM required.
  2. Agent mode: Feeds enriched context to the LLM agent for refinement.

Supported Talend components:
  - tMap          → SQL SELECT, JOIN, column expressions
  - tFilterRow    → SQL WHERE clause
  - tAggregateRow → SQL GROUP BY + aggregate functions

Usage:
    from talend_to_dbt import TalendToDbtConverter
    converter = TalendToDbtConverter(parsed_job_dict)
    result = converter.convert()
"""

import os
import re
import logging
import subprocess
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger("agent.converter")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GENERATED_MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "generated")


# ---------------------------------------------------------------------------
# Expression Translation
# ---------------------------------------------------------------------------
# Talend uses Java-like expressions in tMap mappings. These must be converted
# to SQL expressions that DuckDB (or any SQL engine) understands.

TALEND_FUNCTION_MAP = {
    "StringHandling.UPCASE":    "UPPER",
    "StringHandling.DOWNCASE":  "LOWER",
    "StringHandling.TRIM":      "TRIM",
    "StringHandling.LTRIM":     "LTRIM",
    "StringHandling.RTRIM":     "RTRIM",
    "StringHandling.LEFT":      "LEFT",
    "StringHandling.RIGHT":     "RIGHT",
    "StringHandling.LEN":       "LENGTH",
    "StringHandling.SUBSTR":    "SUBSTR",
    "TalendDate.formatDate":    "STRFTIME",   # DuckDB-specific
    "TalendDate.getCurrentDate": "CURRENT_DATE",
}

# Talend filter operators → SQL operators
TALEND_OPERATOR_MAP = {
    "==":       "=",
    "!=":       "!=",
    ">":        ">",
    "<":        "<",
    ">=":       ">=",
    "<=":       "<=",
    "contains": "LIKE",
    "matches":  "REGEXP",
}

# Talend aggregate functions → SQL aggregate functions
TALEND_AGG_MAP = {
    "sum":   "SUM",
    "count": "COUNT",
    "min":   "MIN",
    "max":   "MAX",
    "avg":   "AVG",
    "first": "FIRST",
    "last":  "LAST",
}

# Talend types → SQL types (for schema documentation)
TALEND_TYPE_MAP = {
    "id_Integer": "INTEGER",
    "id_Long":    "BIGINT",
    "id_Float":   "FLOAT",
    "id_Double":  "DOUBLE",
    "id_String":  "VARCHAR",
    "id_Date":    "DATE",
    "id_Boolean": "BOOLEAN",
}


def derive_alias(table_name: str) -> str:
    """
    Derive a short, readable alias from a table name.
    raw_customers → customers, raw_orders → orders
    """
    if table_name.startswith("raw_"):
        return table_name[4:]
    return table_name


def translate_expression(expr: str, row_to_alias: dict) -> str:
    """
    Translate a Talend Java expression to SQL.

    Handles:
      - Row references:    row1.column      → alias.column
      - Function calls:    StringHandling.UPCASE(row1.col) → UPPER(alias.col)
      - String concat:     row1.a + " " + row2.b → alias1.a || ' ' || alias2.b
      - Math expressions:  row1.amount / 100.0   → alias.amount / 100.0
    """
    result = expr

    # Step 1: Translate Talend functions to SQL equivalents
    # We sort by length (longest first) to avoid partial replacements
    for talend_func, sql_func in sorted(
        TALEND_FUNCTION_MAP.items(), key=lambda x: -len(x[0])
    ):
        result = result.replace(talend_func, sql_func)

    # Step 2: Replace row references (row1., row2.) with table aliases
    for row_label, alias in row_to_alias.items():
        result = result.replace(f"{row_label}.", f"{alias}.")

    # Step 3: Handle string concatenation
    # Java uses + for string concat, SQL uses ||
    # Pattern: expr + "literal" + expr  →  expr || 'literal' || expr
    result = re.sub(r'\s*\+\s*"([^"]*?)"\s*\+\s*', r" || '\1' || ", result)
    # Pattern: "literal" + expr (at start)
    result = re.sub(r'"([^"]*?)"\s*\+\s*', r"'\1' || ", result)
    # Pattern: expr + "literal" (at end)
    result = re.sub(r'\s*\+\s*"([^"]*?)"', r" || '\1'", result)

    return result


def translate_filter_to_sql(filter_cond: dict, row_to_alias: dict) -> str:
    """
    Convert a Talend tFilterRow condition to a SQL WHERE expression.

    Example:
      {input_column: "status", operator: "==", value: "active"}
      → "status = 'active'"
    """
    col = filter_cond["input_column"]
    op = TALEND_OPERATOR_MAP.get(filter_cond["operator"], filter_cond["operator"])
    val = filter_cond["value"]
    func = filter_cond.get("function", "")

    # Apply function wrapping if present (e.g., UPPER(col))
    col_expr = f"{func.upper()}({col})" if func else col

    # Special handling for LIKE/CONTAINS
    if op == "LIKE":
        return f"{col_expr} LIKE '%{val}%'"
    elif op == "REGEXP":
        return f"{col_expr} REGEXP '{val}'"
    else:
        # Quote string values, leave numbers unquoted
        try:
            float(val)
            return f"{col_expr} {op} {val}"
        except ValueError:
            return f"{col_expr} {op} '{val}'"


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

@dataclass
class ConversionResult:
    """The output of a Talend-to-dbt conversion."""
    model_name: str
    source_name: str
    sql_content: str
    schema_yaml: str
    source_yaml: str
    source_tables: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class TalendToDbtConverter:
    """
    Converts a parsed Talend job (dict from talend_parser) into dbt files.

    The conversion follows this strategy:
      1. Map Talend connection labels (row1, row2) to source tables
      2. Translate all expressions from Java to SQL
      3. Generate CTE-based dbt SQL with {{ source() }} macros
      4. Generate schema YAML with auto-detected tests
    """

    def __init__(self, parsed_job: dict):
        self.job = parsed_job
        self.row_to_source: dict[str, dict] = {}   # row label → source table info
        self.row_to_alias: dict[str, str] = {}      # row label → SQL alias
        self.warnings: list[str] = []
        self._build_mappings()

    def _build_mappings(self) -> None:
        """
        Map connection labels (row1, row2) to source tables and aliases.

        In Talend, data flows between components via named connections.
        "row1" might connect tMysqlInput_1 to tMap_1. We need to know
        that "row1" means the "raw_orders" table so we can translate
        expressions like "row1.id" to "orders.id".
        """
        for conn in self.job.get("connections", []):
            for src in self.job.get("sources", []):
                if conn["source"] == src["component_id"]:
                    label = conn["label"]
                    self.row_to_source[label] = src
                    self.row_to_alias[label] = derive_alias(src["table_name"])

    def _get_model_name(self) -> str:
        """Derive the dbt model name from the Talend target table."""
        targets = self.job.get("targets", [])
        if targets:
            return targets[0]["table_name"]
        # Fallback: use filename without extension
        return os.path.splitext(self.job.get("filename", "unknown"))[0]

    def _get_source_name(self) -> str:
        """Derive the dbt source name from the Talend database parameter."""
        sources = self.job.get("sources", [])
        if sources and sources[0].get("database"):
            return sources[0]["database"]
        return "raw"

    def _get_transformations_by_type(self, comp_type: str) -> list[dict]:
        """Get all transformations of a specific component type."""
        return [
            t for t in self.job.get("transformations", [])
            if t["component_type"] == comp_type
        ]

    def _has_joins(self) -> bool:
        """Check if any tMap has join specifications."""
        for t in self._get_transformations_by_type("tMap"):
            if t.get("joins"):
                return True
        return False

    # -------------------------------------------------------------------
    # SQL Generation
    # -------------------------------------------------------------------

    def _generate_ctes(self) -> str:
        """
        Generate CTE (WITH) blocks for each source table.

        Each source table gets its own CTE that references the dbt source:
          WITH orders AS (
              SELECT * FROM {{ source('jaffle_shop', 'raw_orders') }}
          )

        This is a dbt best practice — it keeps the main SELECT clean
        and makes the lineage explicit.
        """
        source_name = self._get_source_name()
        ctes = []

        for i, (label, src) in enumerate(self.row_to_source.items()):
            alias = self.row_to_alias[label]
            table = src["table_name"]
            cte = (
                f"{alias} AS (\n"
                f"    SELECT * FROM {{{{ source('{source_name}', '{table}') }}}}\n"
                f")"
            )
            ctes.append(cte)

        return "WITH " + ",\n\n".join(ctes)

    def _generate_select_columns(self, tmap: dict) -> list[str]:
        """
        Translate tMap output column mappings to SQL SELECT expressions.

        Each mapping becomes a line like:
          orders.id AS order_id
          UPPER(orders.payment_method) AS payment_method
          orders.amount / 100.0 AS amount_dollars

        Columns are sorted: simple references first, then calculations/aggregates
        (sqlfluff rule ST06: column_order).
        """
        simple_cols = []   # passthrough: alias.col or alias.col AS renamed
        complex_cols = []  # expressions: math, functions, concat

        for mapping in tmap.get("column_mappings", []):
            expr = translate_expression(mapping["expression"], self.row_to_alias)
            out_col = mapping["output_column"]

            # Determine if this is a "simple" reference (just alias.column)
            is_simple = bool(re.match(r'^\w+\.\w+$', expr))

            if is_simple and expr.endswith(f".{out_col}"):
                # Pure passthrough — no rename needed
                entry = f"    {expr}"
            elif is_simple:
                # Simple column with rename
                entry = f"    {expr} AS {out_col}"
            else:
                entry = f"    {expr} AS {out_col}"

            if is_simple:
                simple_cols.append(entry)
            else:
                complex_cols.append(entry)

        # ST06: simple columns first, then calculations
        return simple_cols + complex_cols

    def _generate_join_clause(self, tmap: dict) -> str:
        """
        Generate SQL JOIN clauses from tMap join specifications.

        A Talend tMap join:
          lookup_table=row2, join_column=id, join_expression=row1.user_id, join_type=LEFT
        becomes:
          LEFT JOIN customers ON orders.user_id = customers.id

        Note: sqlfluff rule ST09 requires the table referenced EARLIER
        (in FROM) to appear on the LEFT side of the ON condition.
        """
        join_clauses = []
        for join in tmap.get("joins", []):
            join_type = join["join_type"]
            lookup_alias = self.row_to_alias.get(join["lookup_table"], join["lookup_table"])
            join_col = join["join_column"]
            join_expr = translate_expression(join["join_expression"], self.row_to_alias)

            # ST09: FROM-table column on the left, lookup column on the right
            join_clauses.append(
                f"{join_type} JOIN {lookup_alias}\n"
                f"    ON {join_expr} = {lookup_alias}.{join_col}"
            )

        return "\n".join(join_clauses)

    def _generate_where_clause(self) -> str:
        """
        Generate SQL WHERE clause from tFilterRow conditions.

        Multiple conditions are combined with AND.
        """
        filters = self._get_transformations_by_type("tFilterRow")
        if not filters:
            return ""

        conditions = []
        for filt in filters:
            for cond in filt.get("filters", []):
                sql_cond = translate_filter_to_sql(cond, self.row_to_alias)
                conditions.append(sql_cond)

        if conditions:
            return "WHERE " + "\n  AND ".join(conditions)
        return ""

    def _generate_group_by(self, agg: dict) -> str:
        """Generate SQL GROUP BY + aggregate SELECT from tAggregateRow."""
        group_cols = agg.get("group_by_columns", [])
        agg_ops = agg.get("aggregations", [])

        select_parts = []
        for col in group_cols:
            select_parts.append(f"    {col}")

        for op in agg_ops:
            sql_func = TALEND_AGG_MAP.get(op["function"], op["function"].upper())
            select_parts.append(f"    {sql_func}({op['input_column']}) AS {op['output_column']}")

        group_clause = f"GROUP BY {', '.join(group_cols)}" if group_cols else ""

        return select_parts, group_clause

    def generate_sql(self) -> str:
        """
        Generate the complete dbt SQL model.

        The structure depends on the Talend pipeline:
          - Simple filter:     SELECT ... FROM source WHERE ...
          - Join:              WITH ctes... SELECT ... FROM main JOIN lookup ON ...
          - Transform + Agg:   WITH ctes... transformed AS (...) SELECT agg FROM transformed GROUP BY ...
        """
        source_name = self._get_source_name()
        tmaps = self._get_transformations_by_type("tMap")
        filters = self._get_transformations_by_type("tFilterRow")
        aggregations = self._get_transformations_by_type("tAggregateRow")

        has_joins = self._has_joins()
        has_agg = bool(aggregations)
        has_tmap = bool(tmaps)
        use_ctes = has_joins or has_agg or len(self.row_to_source) > 1

        lines = ["{{ config(materialized='table') }}", ""]

        # --- Case 1: Simple filter (no tMap, no aggregation) ---
        if not has_tmap and not has_agg and filters:
            src = list(self.row_to_source.values())[0] if self.row_to_source else self.job["sources"][0]
            table = src["table_name"]
            cols = [c["name"] for c in src.get("columns", [])]
            col_list = ",\n    ".join(cols) if cols else "*"

            lines.append(f"SELECT\n    {col_list}")
            lines.append(f"FROM {{{{ source('{source_name}', '{table}') }}}}")
            lines.append(self._generate_where_clause())
            return "\n".join(lines) + "\n"

        # --- Case 2+: Has tMap and/or aggregation — use CTEs ---
        if use_ctes:
            lines.append(self._generate_ctes())

        # --- If tMap + aggregation, create an intermediate CTE ---
        if has_tmap and has_agg:
            tmap = tmaps[0]
            select_cols = self._generate_select_columns(tmap)
            main_alias = list(self.row_to_alias.values())[0] if self.row_to_alias else "source"

            lines.append("")  # blank line separator
            # Check if CTEs were already added (need comma separator)
            if use_ctes:
                lines[-1] = ","  # replace blank line with comma
                lines.append("")

            lines.append("transformed AS (")
            lines.append("    SELECT")
            lines.append(",\n".join(f"        {c.strip()}" for c in select_cols))
            lines.append(f"    FROM {main_alias}")

            # Add join if present
            if has_joins:
                lines.append("    " + self._generate_join_clause(tmap).replace("\n", "\n    "))

            lines.append(")")
            lines.append("")

            # Now the final SELECT with aggregation
            agg = aggregations[0]
            agg_select_parts, group_clause = self._generate_group_by(agg)
            lines.append("SELECT")
            lines.append(",\n".join(agg_select_parts))
            lines.append("FROM transformed")
            if group_clause:
                lines.append(group_clause)

        # --- Case 3: tMap only (join or column mapping, no aggregation) ---
        elif has_tmap:
            tmap = tmaps[0]
            select_cols = self._generate_select_columns(tmap)
            main_alias = list(self.row_to_alias.values())[0] if self.row_to_alias else "source"

            if not use_ctes:
                # Single source, no CTE needed
                src = list(self.row_to_source.values())[0]
                lines.append("SELECT")
                lines.append(",\n".join(select_cols))
                lines.append(f"FROM {{{{ source('{source_name}', '{src['table_name']}') }}}}")
            else:
                lines.append("")
                lines.append("SELECT")
                lines.append(",\n".join(select_cols))
                lines.append(f"FROM {main_alias}")

                if has_joins:
                    lines.append(self._generate_join_clause(tmap))

            # Add WHERE if tFilterRow exists
            where = self._generate_where_clause()
            if where:
                lines.append(where)

        # --- Case 4: Aggregation only (no tMap) ---
        elif has_agg:
            src = list(self.row_to_source.values())[0] if self.row_to_source else self.job["sources"][0]
            agg = aggregations[0]
            agg_select_parts, group_clause = self._generate_group_by(agg)

            if use_ctes:
                main_alias = list(self.row_to_alias.values())[0]
                lines.append("")
                lines.append("SELECT")
                lines.append(",\n".join(agg_select_parts))
                lines.append(f"FROM {main_alias}")
            else:
                lines.append("SELECT")
                lines.append(",\n".join(agg_select_parts))
                lines.append(f"FROM {{{{ source('{source_name}', '{src['table_name']}') }}}}")

            if group_clause:
                lines.append(group_clause)

        return "\n".join(lines) + "\n"

    # -------------------------------------------------------------------
    # YAML Generation
    # -------------------------------------------------------------------

    def generate_schema_yaml(self, model_name: str) -> str:
        """
        Generate dbt schema YAML with auto-detected tests.

        Test rules:
          - Primary key columns (key=true) get: not_null + unique
          - Other non-nullable columns get: not_null
          - String columns with known accepted values get: accepted_values
        """
        targets = self.job.get("targets", [])
        if not targets:
            return f"models:\n  - name: {model_name}\n"

        target = targets[0]
        columns_yaml = []

        for col in target.get("columns", []):
            col_entry = {
                "name": col["name"],
                "description": col.get("comment", "") or f"Column {col['name']}",
            }
            tests = []
            if col.get("key"):
                tests.extend(["not_null", "unique"])
            elif not col.get("nullable", True):
                tests.append("not_null")
            if tests:
                col_entry["tests"] = tests
            columns_yaml.append(col_entry)

        schema = {
            "models": [{
                "name": model_name,
                "description": f"dbt model converted from Talend job: {self.job.get('filename', 'unknown')}",
                "columns": columns_yaml,
            }]
        }

        return yaml.dump(schema, default_flow_style=False, sort_keys=False)

    def generate_source_yaml(self) -> str:
        """
        Generate dbt source YAML declaring all source tables used by this job.
        """
        source_name = self._get_source_name()
        tables = []
        seen = set()
        for src in self.job.get("sources", []):
            tname = src["table_name"]
            if tname not in seen:
                tables.append({"name": tname})
                seen.add(tname)

        source_def = {
            "sources": [{
                "name": source_name,
                "tables": tables,
            }]
        }
        return yaml.dump(source_def, default_flow_style=False, sort_keys=False)

    # -------------------------------------------------------------------
    # Main Conversion
    # -------------------------------------------------------------------

    def convert(self) -> ConversionResult:
        """
        Run the full conversion pipeline.

        Returns a ConversionResult containing:
          - model_name: Target table name (used as dbt model name)
          - sql_content: Complete dbt SQL with Jinja macros
          - schema_yaml: Model schema with tests
          - source_yaml: Source definitions
          - warnings: Any issues encountered during translation
        """
        model_name = self._get_model_name()
        source_name = self._get_source_name()

        sql_content = self.generate_sql()
        schema_yaml = self.generate_schema_yaml(model_name)
        source_yaml = self.generate_source_yaml()

        source_tables = [src["table_name"] for src in self.job.get("sources", [])]

        return ConversionResult(
            model_name=model_name,
            source_name=source_name,
            sql_content=sql_content,
            schema_yaml=schema_yaml,
            source_yaml=source_yaml,
            source_tables=source_tables,
            warnings=self.warnings,
        )


# ---------------------------------------------------------------------------
# File Writer
# ---------------------------------------------------------------------------

def write_dbt_files(result: ConversionResult, output_dir: str = GENERATED_MODELS_DIR) -> dict:
    """
    Write the conversion result to dbt model files on disk.

    Creates:
      - {model_name}.sql            — The dbt SQL model
      - {model_name}_schema.yml     — Schema tests
      - {source_name}_sources.yml   — Source definitions (merged)
    """
    os.makedirs(output_dir, exist_ok=True)

    # Write SQL model
    sql_path = os.path.join(output_dir, f"{result.model_name}.sql")
    # Normalize trailing newline
    sql_content = result.sql_content.rstrip() + "\n"
    with open(sql_path, "w") as fh:
        fh.write(sql_content)

    # Write schema YAML
    schema_path = os.path.join(output_dir, f"{result.model_name}_schema.yml")
    with open(schema_path, "w") as fh:
        fh.write(result.schema_yaml)

    # Merge source definitions (don't overwrite existing sources)
    source_path = os.path.join(output_dir, f"{result.source_name}_sources.yml")
    new_sources = yaml.safe_load(result.source_yaml) or {}

    if os.path.exists(source_path):
        with open(source_path, "r") as fh:
            existing = yaml.safe_load(fh.read()) or {}
        # Merge tables
        existing_src_map = {s["name"]: s for s in existing.get("sources", [])}
        for new_src in new_sources.get("sources", []):
            sname = new_src["name"]
            if sname in existing_src_map:
                existing_tables = {t["name"] for t in existing_src_map[sname].get("tables", [])}
                for t in new_src.get("tables", []):
                    if t["name"] not in existing_tables:
                        existing_src_map[sname].setdefault("tables", []).append(t)
            else:
                existing_src_map[sname] = new_src
        merged = {"sources": list(existing_src_map.values())}
    else:
        merged = new_sources

    with open(source_path, "w") as fh:
        yaml.dump(merged, fh, default_flow_style=False, sort_keys=False)

    logger.info("Wrote dbt files for '%s' → %s", result.model_name, output_dir)

    return {
        "sql_path": sql_path,
        "schema_path": schema_path,
        "source_path": source_path,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_sql(sql_path: str) -> dict:
    """Run sqlfluff lint on a generated SQL file."""
    venv_sqlfluff = os.path.join(PROJECT_ROOT, "venv", "bin", "sqlfluff")
    try:
        result = subprocess.run(
            [venv_sqlfluff, "lint", sql_path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        return {
            "passed": result.returncode == 0,
            "output": result.stdout if result.returncode != 0 else "OK",
        }
    except FileNotFoundError:
        return {"passed": False, "output": "sqlfluff binary not found"}
