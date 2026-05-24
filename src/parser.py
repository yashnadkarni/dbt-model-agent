"""
Talend XML Parser — Extracts source tables, transformations, and target tables
from Talend Open Studio job export files (.item).

Talend jobs are stored as XMI (XML Metadata Interchange) files. This parser
reads the XML structure and produces a structured Python dictionary describing
the entire ETL pipeline: what it reads from, what it does, and where it writes.

Usage:
    python -m src.parser                                      # Parse all jobs in fixtures/talend_jobs/
    python -m src.parser fixtures/talend_jobs/my_job.item      # Parse a single job
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Optional
from src import TALEND_JOBS_DIR
from src import PROJECT_ROOT


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------
# These dataclasses represent the parsed structure of a Talend job.
# They mirror the logical concepts: columns, tables, transformations, and jobs.

@dataclass
class Column:
    """A single column in a schema (source or target)."""
    name: str
    type: str
    key: bool = False
    nullable: bool = True
    length: Optional[int] = None
    comment: str = ""


@dataclass
class SourceTable:
    """An input table read by the job."""
    component_id: str          # e.g. "tMysqlInput_1"
    component_type: str        # e.g. "tMysqlInput"
    database: str
    table_name: str
    query: str
    columns: list[Column] = field(default_factory=list)


@dataclass
class TargetTable:
    """An output table written by the job."""
    component_id: str          # e.g. "tMysqlOutput_1"
    component_type: str        # e.g. "tMysqlOutput"
    database: str
    table_name: str
    action_on_table: str       # DROP_CREATE, CREATE, NONE
    action_on_data: str        # INSERT, UPDATE, INSERT_OR_UPDATE
    columns: list[Column] = field(default_factory=list)


@dataclass
class FilterCondition:
    """A single filter rule from a tFilterRow component."""
    input_column: str
    operator: str              # ==, !=, >, <, >=, <=, matches, contains
    value: str
    function: str = ""         # Optional: UPPER, LOWER, TRIM, etc.


@dataclass
class ColumnMapping:
    """A column mapping from a tMap output: output_col = expression(input_cols)."""
    output_column: str
    expression: str            # e.g. "row1.id", "row1.amount / 100.0"
    output_type: str


@dataclass
class JoinSpec:
    """A join specification from a tMap's lookup input table."""
    lookup_table: str          # Name of the lookup input (e.g. "row2")
    join_expression: str       # e.g. "row1.user_id" (what the lookup key matches)
    join_column: str           # The column in the lookup table being matched
    join_type: str             # "LEFT" or "INNER"
    match_mode: str            # FIRST_MATCH, ALL_MATCHES, ALL_ROWS


@dataclass
class AggregateOp:
    """A single aggregation operation from tAggregateRow."""
    input_column: str
    function: str              # sum, count, min, max, avg, first, last
    output_column: str


@dataclass
class Transformation:
    """A transformation step (tMap, tFilterRow, or tAggregateRow)."""
    component_id: str
    component_type: str        # "tMap", "tFilterRow", "tAggregateRow"
    filters: list[FilterCondition] = field(default_factory=list)
    column_mappings: list[ColumnMapping] = field(default_factory=list)
    joins: list[JoinSpec] = field(default_factory=list)
    group_by_columns: list[str] = field(default_factory=list)
    aggregations: list[AggregateOp] = field(default_factory=list)


@dataclass
class DataFlow:
    """A connection between two components."""
    source: str
    target: str
    connector_type: str        # FLOW, LOOKUP, REJECT
    label: str                 # row1, row2, out1, etc.


@dataclass
class TalendJob:
    """The complete parsed representation of a Talend job."""
    filename: str
    sources: list[SourceTable] = field(default_factory=list)
    targets: list[TargetTable] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    connections: list[DataFlow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# XML Parsing Helpers
# ---------------------------------------------------------------------------

def _get_param(node_elem: ET.Element, param_name: str) -> str:
    """
    Extract the value of an <elementParameter> by its 'name' attribute.
    
    Talend stores component properties as:
      <elementParameter field="TEXT" name="TABLE" value="&quot;raw_customers&quot;"/>
    
    The value is often wrapped in XML-escaped quotes (&quot;), so we strip those.
    """
    for param in node_elem.findall("elementParameter"):
        if param.get("name") == param_name:
            val = param.get("value", "")
            # Strip escaped quotes that Talend adds around string values
            return val.strip('"').replace("&quot;", "")
    return ""


def _parse_columns(node_elem: ET.Element) -> list[Column]:
    """
    Parse the <metadata><column .../> structure to extract the schema.
    
    Every Talend component that touches data has a <metadata> block defining
    the columns that flow through it. This is essentially the schema contract.
    """
    columns = []
    for metadata in node_elem.findall("metadata"):
        for col in metadata.findall("column"):
            columns.append(Column(
                name=col.get("name", ""),
                type=col.get("type", ""),
                key=col.get("key", "false") == "true",
                nullable=col.get("nullable", "true") == "true",
                length=int(col.get("length")) if col.get("length") else None,
                comment=col.get("comment", ""),
            ))
    return columns


def _parse_filter_conditions(node_elem: ET.Element) -> list[FilterCondition]:
    """
    Parse tFilterRow's CONDITIONS parameter.
    
    Talend stores filter conditions as a TABLE-type parameter where each
    <elementValue> represents one field of the condition. The elementRef
    tells us which field it is (INPUT_COLUMN, OPERATOR, RVALUE, FUNCTION).
    
    Multiple conditions appear as repeated CONDITIONS parameter blocks.
    """
    conditions = []
    for param in node_elem.findall("elementParameter"):
        if param.get("name") != "CONDITIONS":
            continue

        # Collect all elementValue entries for this condition
        values = {}
        for ev in param.findall("elementValue"):
            ref = ev.get("elementRef", "")
            val = ev.get("value", "").strip('"')
            values[ref] = val

        if values.get("INPUT_COLUMN"):
            conditions.append(FilterCondition(
                input_column=values.get("INPUT_COLUMN", ""),
                operator=values.get("OPERATOR", ""),
                value=values.get("RVALUE", ""),
                function=values.get("FUNCTION", ""),
            ))

    return conditions


def _parse_tmap(node_elem: ET.Element) -> Transformation:
    """
    Parse a tMap component — the most complex Talend component.
    
    The tMap's logic lives inside a <nodeData xsi:type="TalendMapper:MapperData">
    element, which contains:
    
    1. <inputTables> — Each incoming data flow. The FIRST inputTable is the
       main flow. Subsequent ones are LOOKUP tables (for joins).
       
       For lookup tables, the join key is encoded in the mapperTableEntries:
       if a column's "expression" points to another table's column
       (e.g., "row1.user_id"), that's the join condition.
       
    2. <outputTables> — Each outgoing data flow. The mapperTableEntries here
       define the column mappings (what to output and where values come from).
       
    3. <varTables> — Intermediate variables (we extract these too if present).
    """
    component_id = _get_param(node_elem, "UNIQUE_NAME")
    trans = Transformation(
        component_id=component_id,
        component_type="tMap",
    )

    # Find the nodeData element (may have namespace prefix)
    node_data = None
    for child in node_elem:
        if child.tag == "nodeData" or child.tag.endswith("}MapperData"):
            node_data = child
            break

    if node_data is None:
        return trans

    # --- Parse input tables ---
    is_first_input = True
    for input_table in node_data.findall("inputTables"):
        table_name = input_table.get("name", "")
        inner_join = input_table.get("innerJoin", "true") == "true"
        match_mode = input_table.get("matchingMode", "ALL_ROWS")

        if is_first_input:
            # First input is the main flow — not a join
            is_first_input = False
            continue

        # Subsequent inputs are LOOKUP tables — find the join key
        for entry in input_table.findall("mapperTableEntries"):
            expr = entry.get("expression", "")
            if expr:
                # This column has a join expression pointing to the main table
                trans.joins.append(JoinSpec(
                    lookup_table=table_name,
                    join_expression=expr,
                    join_column=entry.get("name", ""),
                    join_type="INNER" if inner_join else "LEFT",
                    match_mode=match_mode,
                ))

    # --- Parse output tables (column mappings) ---
    for output_table in node_data.findall("outputTables"):
        for entry in output_table.findall("mapperTableEntries"):
            expr = entry.get("expression", "")
            if expr:
                trans.column_mappings.append(ColumnMapping(
                    output_column=entry.get("name", ""),
                    expression=expr.replace("&quot;", '"'),
                    output_type=entry.get("type", ""),
                ))

    return trans


def _parse_aggregate(node_elem: ET.Element) -> Transformation:
    """
    Parse a tAggregateRow component.
    
    It has two TABLE-type parameters:
    - GROUP_BY: columns to group by (INPUT_COLUMN → OUTPUT_COLUMN)
    - OPERATIONS: aggregate functions (INPUT_COLUMN + FUNCTION → OUTPUT_COLUMN)
    
    Multiple GROUP_BY or OPERATIONS entries are stored as repeated
    <elementParameter name="GROUP_BY"> or <elementParameter name="OPERATIONS"> blocks.
    """
    component_id = _get_param(node_elem, "UNIQUE_NAME")
    trans = Transformation(
        component_id=component_id,
        component_type="tAggregateRow",
    )

    for param in node_elem.findall("elementParameter"):
        pname = param.get("name", "")
        values = {}
        for ev in param.findall("elementValue"):
            values[ev.get("elementRef", "")] = ev.get("value", "")

        if pname == "GROUP_BY" and values.get("INPUT_COLUMN"):
            trans.group_by_columns.append(values["INPUT_COLUMN"])

        elif pname == "OPERATIONS" and values.get("INPUT_COLUMN"):
            trans.aggregations.append(AggregateOp(
                input_column=values["INPUT_COLUMN"],
                function=values.get("FUNCTION", ""),
                output_column=values.get("OUTPUT_COLUMN", ""),
            ))

    return trans


# ---------------------------------------------------------------------------
# Main Parser
# ---------------------------------------------------------------------------

# Components that represent data sources (reading data)
SOURCE_COMPONENTS = {
    "tMysqlInput", "tPostgresqlInput", "tOracleInput", "tDBInput",
    "tSnowflakeInput", "tFileInputDelimited", "tFileInputExcel",
    "tBigQueryInput", "tRedshiftInput", "tSalesforceInput",
}

# Components that represent data targets (writing data)
TARGET_COMPONENTS = {
    "tMysqlOutput", "tPostgresqlOutput", "tOracleOutput", "tDBOutput",
    "tSnowflakeOutput", "tFileOutputDelimited", "tFileOutputExcel",
    "tBigQueryOutput", "tRedshiftOutput", "tSalesforceOutput",
}


def parse_talend_job(filepath: str) -> TalendJob:
    """
    Parse a single Talend .item XML file and return a structured TalendJob.
    
    The parsing strategy:
    1. Parse the XML tree
    2. Find the <process> element (root of all job logic)
    3. Iterate over all <node> elements — each is a component
    4. Based on componentName, classify as source/target/transformation
    5. Extract connections to understand the data flow graph
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    job = TalendJob(filename=os.path.basename(filepath))

    # Navigate to <process> — it may be nested under <talendfile:ProcessItem>
    process = None
    for elem in root.iter():
        if elem.tag == "process" or elem.tag.endswith("}process"):
            process = elem
            break

    if process is None:
        print(f"WARNING: No <process> element found in {filepath}")
        return job

    # --- Parse each <node> (component) ---
    for node in process.findall("node"):
        comp_name = node.get("componentName", "")
        comp_id = _get_param(node, "UNIQUE_NAME")

        if comp_name in SOURCE_COMPONENTS:
            # This is a SOURCE (data reader)
            job.sources.append(SourceTable(
                component_id=comp_id,
                component_type=comp_name,
                database=_get_param(node, "DBNAME"),
                table_name=_get_param(node, "TABLE"),
                query=_get_param(node, "QUERY"),
                columns=_parse_columns(node),
            ))

        elif comp_name in TARGET_COMPONENTS:
            # This is a TARGET (data writer)
            job.targets.append(TargetTable(
                component_id=comp_id,
                component_type=comp_name,
                database=_get_param(node, "DBNAME"),
                table_name=_get_param(node, "TABLE"),
                action_on_table=_get_param(node, "ACTION_ON_TABLE"),
                action_on_data=_get_param(node, "ACTION_ON_DATA"),
                columns=_parse_columns(node),
            ))

        elif comp_name == "tMap":
            job.transformations.append(_parse_tmap(node))

        elif comp_name == "tFilterRow":
            trans = Transformation(
                component_id=comp_id,
                component_type="tFilterRow",
                filters=_parse_filter_conditions(node),
            )
            job.transformations.append(trans)

        elif comp_name == "tAggregateRow":
            job.transformations.append(_parse_aggregate(node))

    # --- Parse connections (data flow graph) ---
    for conn in process.findall("connection"):
        job.connections.append(DataFlow(
            source=conn.get("source", ""),
            target=conn.get("target", ""),
            connector_type=conn.get("connectorName", ""),
            label=conn.get("label", ""),
        ))

    return job


# ---------------------------------------------------------------------------
# Pretty Printer
# ---------------------------------------------------------------------------

def print_job_summary(job: TalendJob) -> None:
    """Print a human-readable summary of a parsed Talend job."""
    print(f"\n{'=' * 60}")
    print(f"  TALEND JOB: {job.filename}")
    print(f"{'=' * 60}")

    # --- Sources ---
    print(f"\n📥 SOURCES ({len(job.sources)}):")
    for src in job.sources:
        print(f"   [{src.component_id}] {src.component_type}")
        print(f"   Database: {src.database}")
        print(f"   Table:    {src.table_name}")
        print(f"   Query:    {src.query[:80]}{'...' if len(src.query) > 80 else ''}")
        print(f"   Columns:  {', '.join(c.name for c in src.columns)}")
        print()

    # --- Transformations ---
    print(f"🔄 TRANSFORMATIONS ({len(job.transformations)}):")
    for trans in job.transformations:
        print(f"   [{trans.component_id}] {trans.component_type}")

        if trans.filters:
            for f in trans.filters:
                func_str = f"{f.function}(" if f.function else ""
                func_end = ")" if f.function else ""
                print(f"   Filter: {func_str}{f.input_column}{func_end} {f.operator} '{f.value}'")

        if trans.joins:
            for j in trans.joins:
                print(f"   Join:   {j.join_type} JOIN on {j.lookup_table}.{j.join_column} = {j.join_expression}")

        if trans.column_mappings:
            print(f"   Mappings:")
            for m in trans.column_mappings:
                print(f"     {m.output_column} = {m.expression}")

        if trans.group_by_columns:
            print(f"   Group By: {', '.join(trans.group_by_columns)}")

        if trans.aggregations:
            for a in trans.aggregations:
                print(f"   Aggregate: {a.output_column} = {a.function.upper()}({a.input_column})")

        print()

    # --- Targets ---
    print(f"📤 TARGETS ({len(job.targets)}):")
    for tgt in job.targets:
        print(f"   [{tgt.component_id}] {tgt.component_type}")
        print(f"   Database: {tgt.database}")
        print(f"   Table:    {tgt.table_name}")
        print(f"   Action:   {tgt.action_on_table} / {tgt.action_on_data}")
        print(f"   Columns:  {', '.join(c.name for c in tgt.columns)}")
        print()

    # --- Data Flow ---
    print(f"🔗 DATA FLOW:")
    for conn in job.connections:
        arrow = "→" if conn.connector_type == "FLOW" else "⇢ (LOOKUP)"
        print(f"   {conn.source} {arrow} {conn.target}  [{conn.label}]")
    print()


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    """Parse Talend jobs and print summaries. Optionally export to JSON."""
    if len(sys.argv) > 1:
        # Parse specific file(s) passed as arguments
        filepaths = sys.argv[1:]
    else:
        # Default: parse all .item files in fixtures/talend_jobs/
        jobs_dir = TALEND_JOBS_DIR
        if not os.path.isdir(jobs_dir):
            print(f"ERROR: Directory '{jobs_dir}' not found.")
            sys.exit(1)
        filepaths = sorted(
            os.path.join(jobs_dir, f)
            for f in os.listdir(jobs_dir)
            if f.endswith(".item")
        )

    if not filepaths:
        print("No .item files found to parse.")
        sys.exit(1)

    all_jobs = []
    for fp in filepaths:
        print(f"Parsing: {fp}")
        job = parse_talend_job(fp)
        print_job_summary(job)
        all_jobs.append(asdict(job))

    # Export to JSON for downstream consumption
    output_path = os.path.join(PROJECT_ROOT, "parsed_talend_jobs.json")
    with open(output_path, "w") as fh:
        json.dump(all_jobs, fh, indent=2, default=str)
    print(f"📁 Exported parsed data to: {output_path}")


if __name__ == "__main__":
    main()
