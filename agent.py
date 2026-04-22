"""
dbt Model Generation Agent — FastAPI Server

An AI-powered agent that takes JSON schema definitions and produces
production-ready dbt model files (.sql) and schema definitions (.yml)
with built-in validation and testing.
"""

import os
import json
import glob
import logging
import subprocess
from logging.handlers import RotatingFileHandler

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

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GENERATED_MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "generated")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
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

    with open(source_path, "w") as fh:
        yaml.dump(merged, fh, default_flow_style=False, sort_keys=False)

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
    venv_sqlfluff = os.path.join(PROJECT_ROOT, "venv", "bin", "sqlfluff")
    try:
        result = subprocess.run(
            [venv_sqlfluff, "lint", model_path],
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
        logger.error("sqlfluff binary not found at %s", venv_sqlfluff)
        return "Tool error: sqlfluff binary not found. Check your venv."
    except Exception as exc:
        logger.error("Unexpected error during validation: %s", exc)
        return f"Tool execution error: {exc}"

    return (
        f"Successfully generated and verified dbt model at {model_path} "
        f"and schema at {schema_path}"
    )

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
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not set")
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY environment variable is not set.")

    schema_json = request.schema_def
    table_name = schema_json.get("table_name", "unknown")
    source_name = schema_json.get("source_name", "jaffle_shop")
    source_table = schema_json.get("source_table", f"raw_{table_name}")

    logger.info("━━━ Starting generation for '%s' ━━━", table_name)

    # --- Build agent ---
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [generate_dbt_model, generate_dbt_sources]
    agent = create_react_agent(llm, tools)

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

    # --- Stream agent execution ---
    inputs = {"messages": [("user", user_prompt)]}
    messages_out = []

    try:
        for chunk in agent.stream(inputs, stream_mode="values"):
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
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    logger.info("━━━ Completed generation for '%s' ━━━", table_name)
    return {
        "status": "success",
        "table_name": table_name,
        "agent_transcript": messages_out,
    }


@app.post("/validate_project", summary="Run dbt compile on the full project")
def validate_project():
    """
    Runs `dbt compile` across the entire project to verify that all
    models, sources, and refs resolve correctly. Call this after all
    models have been generated.
    """
    venv_dbt = os.path.join(PROJECT_ROOT, "venv", "bin", "dbt")
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
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
