"""
dbt Model Generation Agent — FastAPI Server

An AI-powered agent that takes JSON schema definitions and produces
production-ready dbt model files (.sql) and schema definitions (.yml)
with built-in validation and testing.
"""

import os
import sys
import json
import glob
import logging
import subprocess
from logging.handlers import RotatingFileHandler

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

from src import PROJECT_ROOT, GENERATED_MODELS_DIR, LOGS_DIR, SQLFLUFF_BIN, DBT_BIN
os.makedirs(LOGS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def _setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a logger that writes to both a rotating file and the console."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers on reload
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Rotating file handler — 5 MB per file, keep 3 backups
    file_handler = RotatingFileHandler(
        os.path.join(LOGS_DIR, log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = _setup_logger("agent", "agent.log")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="dbt Model Agent API",
    description="AI agent that generates validated dbt models from JSON schemas.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _remove_conflicting_models(table_name: str) -> None:
    """
    Remove any .sql files with the same model name that exist OUTSIDE
    of models/generated/. dbt enforces globally unique model names, so
    duplicates anywhere in the project tree cause compilation errors.
    """
    models_root = os.path.join(PROJECT_ROOT, "models")
    pattern = os.path.join(models_root, "**", f"{table_name}.sql")
    for sql_file in glob.glob(pattern, recursive=True):
        if os.path.dirname(os.path.abspath(sql_file)) == os.path.abspath(GENERATED_MODELS_DIR):
            continue
        logger.warning("Removing conflicting model: %s", sql_file)
        os.remove(sql_file)


def _merge_source_tables(existing: dict, new_parsed: dict) -> dict:
    """Merge new source table definitions into an existing sources dict."""
    existing_sources = {s["name"]: s for s in existing.get("sources", [])}

    for new_source in new_parsed.get("sources", []):
        sname = new_source["name"]
        if sname in existing_sources:
            existing_table_names = {
                t["name"] for t in existing_sources[sname].get("tables", [])
            }
            for table in new_source.get("tables", []):
                if table["name"] not in existing_table_names:
                    existing_sources[sname].setdefault("tables", []).append(table)
        else:
            existing_sources[sname] = new_source

    return {"sources": list(existing_sources.values())}

# ---------------------------------------------------------------------------
# Agent Tools
# ---------------------------------------------------------------------------

@tool
def generate_dbt_sources(source_name: str, yaml_content: str) -> str:
    """
    Writes a dbt source definition to models/generated/.
    If a sources file already exists for this source_name, new tables are
    merged so that previous definitions are preserved.

    Args:
        source_name: The name of the source (e.g., 'jaffle_shop').
        yaml_content: Raw YAML string with a top-level `sources:` block.
    """
    os.makedirs(GENERATED_MODELS_DIR, exist_ok=True)
    source_path = os.path.join(GENERATED_MODELS_DIR, f"{source_name}_sources.yml")

    # --- Validate incoming YAML ---
    try:
        new_parsed = yaml.safe_load(yaml_content)
        if not isinstance(new_parsed, dict) or "sources" not in new_parsed:
            return "Validation Failed: yaml_content must contain a top-level 'sources:' key."
    except yaml.YAMLError as exc:
        return f"Validation Failed: Invalid YAML syntax: {exc}"

    # --- Merge with existing file if present ---
    if os.path.exists(source_path):
        try:
            with open(source_path, "r") as fh:
                existing = yaml.safe_load(fh.read()) or {}
            merged = _merge_source_tables(existing, new_parsed)
        except Exception as exc:
            logger.error("Failed to merge existing sources file: %s", exc)
            merged = new_parsed
    else:
        merged = new_parsed

    # Programmatically enforce version: 2 at the top level
    ordered_merged = {"version": 2}
    for k, v in merged.items():
        if k != "version":
            ordered_merged[k] = v

    with open(source_path, "w") as fh:
        yaml.dump(ordered_merged, fh, default_flow_style=False, sort_keys=False)

    logger.info("Wrote/merged source definition → %s", source_path)
    return f"Successfully generated dbt source at {source_path}"


@tool
def generate_dbt_model(table_name: str, sql_content: str, yaml_content: str) -> str:
    """
    Writes the SQL and YAML for a dbt model to models/generated/ and runs
    sqlfluff lint + YAML validation. Returns error details on failure so the
    agent can self-correct.

    IMPORTANT: Always use the exact table_name from the original request.
    Never rename or append suffixes like _v2, _new, _temp.

    Args:
        table_name: Model name — must match the original request exactly.
        sql_content: Raw SQL string for the dbt model.
        yaml_content: Raw YAML string for the schema.yml (models: block).
    """
    os.makedirs(GENERATED_MODELS_DIR, exist_ok=True)

    model_path = os.path.join(GENERATED_MODELS_DIR, f"{table_name}.sql")
    schema_path = os.path.join(GENERATED_MODELS_DIR, f"{table_name}_schema.yml")

    # --- Validate YAML structure ---
    try:
        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            return "Validation Failed: yaml_content must be a valid YAML mapping."
        if "models" not in parsed:
            return "Validation Failed: yaml_content must contain a top-level 'models:' key."
    except yaml.YAMLError as exc:
        return f"Validation Failed: Invalid YAML syntax: {exc}"

    # --- Scrub known Talend expressions ---
    from src.converter import TALEND_FUNCTION_MAP
    for talend_func, sql_func in TALEND_FUNCTION_MAP.items():
        sql_content = sql_content.replace(talend_func, sql_func)

    # --- Normalize trailing newline (fixes sqlfluff LT12) ---
    sql_content = sql_content.rstrip() + "\n"
    yaml_content = yaml_content.rstrip() + "\n"

    # --- Write files ---
    with open(model_path, "w") as fh:
        fh.write(sql_content)
    with open(schema_path, "w") as fh:
        fh.write(yaml_content)

    logger.info("Wrote model files for '%s'. Validating…", table_name)

    # --- Remove name-colliding models elsewhere in the project ---
    _remove_conflicting_models(table_name)

    # --- sqlfluff lint (per-file, no project-graph scan) ---
    try:
        result = subprocess.run(
            [SQLFLUFF_BIN, "lint", model_path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("sqlfluff lint failed for '%s':\n%s", table_name, result.stdout)
            return (
                "Validation Failed on `sqlfluff lint`. "
                "Fix the SQL content (never change the table_name!) based on this error:\n"
                + result.stdout
            )
        logger.info("sqlfluff lint passed for '%s'", table_name)
    except FileNotFoundError:
        logger.error("sqlfluff binary not found at %s", SQLFLUFF_BIN)
        return "Tool error: sqlfluff binary not found. Check your venv."
    except Exception as exc:
        logger.error("Unexpected error during validation: %s", exc)
        return f"Tool execution error: {exc}"

    return (
        f"Successfully generated and verified dbt model at {model_path} "
        f"and schema at {schema_path}"
    )

# ---------------------------------------------------------------------------
# Prompt Builder (Talend → Agent)
# ---------------------------------------------------------------------------

def build_talend_prompt(parsed_dict: dict) -> tuple[str, str, str]:
    """
    Build a structured prompt from a parsed Talend job dict.

    Returns:
        (prompt, target_name, source_name)
    """
    sources_desc = ", ".join(
        f"{s['table_name']} ({s['component_type']})"
        for s in parsed_dict["sources"]
    )
    target = parsed_dict["targets"][0] if parsed_dict["targets"] else {}
    target_name = target.get("table_name", "output")
    target_cols = ", ".join(c["name"] for c in target.get("columns", []))

    transforms_desc = []
    for t in parsed_dict["transformations"]:
        if t["component_type"] == "tFilterRow":
            for f in t.get("filters", []):
                transforms_desc.append(f"Filter: {f['input_column']} {f['operator']} {f['value']}")
        elif t["component_type"] == "tMap":
            for m in t.get("column_mappings", []):
                transforms_desc.append(f"Map: {m['output_column']} = {m['expression']}")
            for j in t.get("joins", []):
                transforms_desc.append(f"Join: {j['join_type']} JOIN on {j['lookup_table']}.{j['join_column']} = {j['join_expression']}")
        elif t["component_type"] == "tAggregateRow":
            for g in t.get("group_by_columns", []):
                transforms_desc.append(f"Group by: {g}")
            for a in t.get("aggregations", []):
                transforms_desc.append(f"Aggregate: {a['output_column']} = {a['function']}({a['input_column']})")

    source_name = parsed_dict["sources"][0].get("database", "raw") if parsed_dict["sources"] else "raw"
    source_tables = [s["table_name"] for s in parsed_dict["sources"]]

    prompt = (
        f"Generate a dbt model for a Talend ETL migration.\n\n"
        f"Source tables: {sources_desc}\n"
        f"Source name: {source_name}\n"
        f"Target table: {target_name}\n"
        f"Target columns: {target_cols}\n"
        f"Transformations:\n" + "\n".join(f"  - {t}" for t in transforms_desc) + "\n\n"
        f"Instructions:\n"
        f"1. Call generate_dbt_sources with source_name='{source_name}'\n"
        f"   CRITICAL: The yaml_content MUST start with 'version: 2' and be a valid sources: block declaring "
        f"source '{source_name}'. Each table MUST be an object with a 'name' key (e.g. - name: {source_tables[0] if source_tables else 'table_name'}).\n"
        f"   CRITICAL: ONLY include tables that are explicitly listed above: {source_tables}. Do NOT add any other tables.\n"
        f"2. Call generate_dbt_model with table_name='{target_name}', sql_content, and yaml_content\n"
        f"   CRITICAL: The sql_content MUST start with {{{{ config(materialized='table') }}}}\n"
        f"3. Use {{{{ source('{source_name}', 'table') }}}} syntax\n"
        f"4. Use CTEs for readability\n"
        f"5. Add not_null and unique tests on key columns in schema YAML\n"
        f"6. Make sure the SQL file ends with a single trailing newline.\n"
        f"7. Pay strict attention to sqlfluff validation errors. If you get a lint error, READ it carefully and FIX the SQL before retrying.\n"
        f"   - For ST06: Ensure simple column references (like table.col) appear BEFORE complex expressions/aggregations in the SELECT clause.\n"
        f"   - For AL01: Ensure you use explicit 'AS' for all table aliases in FROM and JOIN clauses.\n"
        f"   - For ST09: In JOIN conditions, ensure the column from the table referenced EARLIER in the query (usually the FROM table) is on the LEFT side of the equals sign (e.g. from_table.id = join_table.id).\n"
    )

    return prompt, target_name, source_name


# ---------------------------------------------------------------------------
# Reusable Agent Runner
# ---------------------------------------------------------------------------

def run_generation_agent(user_prompt: str, table_name: str, source_name: str) -> dict:
    """
    Core agent execution logic — reusable by both the FastAPI endpoint
    and the Streamlit UI.

    Runs the LangGraph ReAct agent with the real tools (file writing +
    sqlfluff validation + self-correction loop).

    Returns:
        dict with keys: success, table_name, sql_content, schema_yaml,
        source_yaml, agent_transcript, and optionally error.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"success": False, "error": "OPENAI_API_KEY not set in .env"}

    logger.info("━━━ Starting generation for '%s' ━━━", table_name)

    # --- Build agent ---
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [generate_dbt_model, generate_dbt_sources]
    agent = create_react_agent(llm, tools)

    # --- Stream agent execution ---
    inputs = {"messages": [("user", user_prompt)]}
    messages_out = []

    try:
        # Cap recursion to prevent infinite retry loops.
        # 20 steps allows for roughly 6-7 tool calls (including retries) + final response.
        config = {"recursion_limit": 15}
        for chunk in agent.stream(inputs, stream_mode="values", config=config):
            message = chunk["messages"][-1]
            if hasattr(message, "content") and message.content:
                messages_out.append({"role": "agent", "content": message.content})
                logger.info("Agent: %s", message.content[:200])
            elif hasattr(message, "tool_calls") and message.tool_calls:
                tool_name = message.tool_calls[0].get("name")
                messages_out.append({"role": "agent", "tool": tool_name})
                logger.info("Agent calling tool: %s", tool_name)
    except Exception as exc:
        logger.exception("Agent execution failed for '%s'", table_name)
        return {"success": False, "error": str(exc)}

    logger.info("━━━ Completed generation for '%s' ━━━", table_name)

    # --- Read back generated files ---
    result = {
        "success": True,
        "table_name": table_name,
        "agent_transcript": messages_out,
        "sql_content": "",
        "schema_yaml": "",
        "source_yaml": "",
    }

    sql_path = os.path.join(GENERATED_MODELS_DIR, f"{table_name}.sql")
    schema_path = os.path.join(GENERATED_MODELS_DIR, f"{table_name}_schema.yml")
    source_path = os.path.join(GENERATED_MODELS_DIR, f"{source_name}_sources.yml")

    if os.path.exists(sql_path):
        with open(sql_path) as f:
            result["sql_content"] = f.read()
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            result["schema_yaml"] = f.read()
    if os.path.exists(source_path):
        with open(source_path) as f:
            result["source_yaml"] = f.read()

    return result


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

class GenerationRequest(BaseModel):
    """Request body for model generation."""
    schema_def: dict = Field(
        ...,
        description="JSON schema describing the table, columns, and transformations.",
    )


@app.post("/generate_model", summary="Generate a dbt model from a JSON schema")
def generate_model(request: GenerationRequest):
    """
    Accepts a JSON schema, invokes the LangGraph agent which calls the
    `generate_dbt_sources` and `generate_dbt_model` tools, validates
    the output with sqlfluff, and returns the agent transcript.
    """
    schema_json = request.schema_def
    table_name = schema_json.get("table_name", "unknown")
    source_name = schema_json.get("source_name", "jaffle_shop")
    source_table = schema_json.get("source_table", f"raw_{table_name}")

    user_prompt = (
        f"You are a stellar dbt engineer. Please generate a dbt model and schema tests "
        f"using the following JSON schema input:\n\n{json.dumps(schema_json, indent=2)}\n\n"
        f"IMPORTANT INSTRUCTIONS:\n"
        f"1. You MUST translate the transformation requirement into functional SQL (do not just write comments).\n"
        f"2. You MUST use BOTH tools effectively:\n"
        f"   - First, call `generate_dbt_sources` with source_name='{source_name}' to define the source. "
        f"The yaml_content must be a valid `sources:` block declaring source '{source_name}' with table '{source_table}'.\n"
        f"   - Then, call `generate_dbt_model` with table_name='{table_name}' to create the model SQL and schema.\n"
        f"3. In the SQL, reference the source table using: {{{{ source('{source_name}', '{source_table}') }}}}\n"
        f"4. In your `generate_dbt_model` call, the `yaml_content` MUST only contain a `models:` block (NOT sources). "
        f"Include dbt tests: `not_null`, `unique` on primary keys, and `accepted_values` where applicable.\n"
        f"5. ABSOLUTE RULE: The table_name argument MUST be exactly '{table_name}'. "
        f"NEVER rename it, never add suffixes like _v2, _new, _temp, _transformed.\n"
        f"6. If the tool returns a validation error, fix only the SQL or YAML content, never change the table_name.\n"
        f"7. Make sure the SQL file ends with a single trailing newline.\n"
        f"8. You have a maximum of 3 retries if validation fails.\n"
        f"Work through this step-by-step."
    )

    result = run_generation_agent(user_prompt, table_name, source_name)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "status": "success",
        "table_name": result["table_name"],
        "agent_transcript": result["agent_transcript"],
    }


@app.post("/validate_project", summary="Run dbt compile on the full project")
def validate_project():
    """
    Runs `dbt compile` across the entire project to verify that all
    models, sources, and refs resolve correctly. Call this after all
    models have been generated.
    """
    venv_dbt = DBT_BIN
    logger.info("Running full dbt compile validation…")

    try:
        result = subprocess.run(
            [venv_dbt, "compile"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.error("dbt binary not found at %s", venv_dbt)
        raise HTTPException(status_code=500, detail="dbt binary not found. Check your venv.")

    if result.returncode == 0:
        logger.info("dbt compile PASSED")
    else:
        logger.error("dbt compile FAILED:\n%s\n%s", result.stderr, result.stdout)

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# Talend Conversion Endpoint
# ---------------------------------------------------------------------------

class TalendConversionRequest(BaseModel):
    """Request body for Talend-to-dbt conversion."""
    job_file: str = Field(
        ...,
        description="Path to a Talend .item file (relative to project root or absolute).",
    )


@app.post("/convert_talend", summary="Convert a Talend job to a dbt model")
def convert_talend(request: TalendConversionRequest):
    """
    Parses a Talend .item XML file, deterministically converts it to a dbt
    model (SQL + schema YAML), writes the files, and validates with sqlfluff.
    No LLM required — uses pattern-matched translation.
    """
    from dataclasses import asdict
    from src.parser import parse_talend_job
    from src.converter import TalendToDbtConverter, write_dbt_files, validate_sql

    # Resolve file path
    job_path = request.job_file
    if not os.path.isabs(job_path):
        job_path = os.path.join(PROJECT_ROOT, job_path)

    if not os.path.exists(job_path):
        raise HTTPException(status_code=404, detail=f"File not found: {job_path}")

    logger.info("━━━ Converting Talend job: %s ━━━", os.path.basename(job_path))

    # Parse
    parsed = parse_talend_job(job_path)
    parsed_dict = asdict(parsed)

    # Convert
    converter = TalendToDbtConverter(parsed_dict)
    result = converter.convert()

    # Write files
    paths = write_dbt_files(result)

    # Validate
    lint = validate_sql(paths["sql_path"])

    logger.info("━━━ Conversion complete: %s (lint: %s) ━━━",
                result.model_name, "PASS" if lint["passed"] else "FAIL")

    return {
        "status": "success",
        "model_name": result.model_name,
        "source_tables": result.source_tables,
        "sql_content": result.sql_content,
        "schema_yaml": result.schema_yaml,
        "files": paths,
        "lint": lint,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
