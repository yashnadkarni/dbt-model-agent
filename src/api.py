"""
dbt Model Agent — REST API for React Frontend

Exposes parsing, conversion, validation, and download as REST endpoints.
All business logic delegates to existing parser.py, converter.py, and agent.py.

Usage:
    uvicorn src.api:app --port 8000 --reload
"""

import io
import os
import sys
import json
import zipfile
import tempfile
import subprocess
from dataclasses import asdict

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src import PROJECT_ROOT, TALEND_JOBS_DIR, GENERATED_MODELS_DIR, DBT_BIN, SQLFLUFF_BIN
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="dbt Model Agent API",
    description="REST API for the dbt Model Agent React frontend.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ConvertRequest(BaseModel):
    xml_content: str = Field(..., description="Talend .item XML content")
    filename: str = Field(default="job.item", description="Original filename hint")
    use_llm: bool = Field(default=False, description="Whether to also run LLM conversion")


class ValidateRequest(BaseModel):
    model_name: str
    source_name: str
    sql_content: str
    schema_yaml: str
    source_yaml: str
    label: str = "Deterministic"


class DownloadRequest(BaseModel):
    model_name: str
    source_name: str
    sql_content: str
    schema_yaml: str
    source_yaml: str


# ---------------------------------------------------------------------------
# Helpers (ported from ui.py)
# ---------------------------------------------------------------------------

def _parse_and_convert(xml_content: str, original_filename: str = "job.item") -> dict:
    """Parse Talend XML and convert deterministically to dbt."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".item",
        prefix=original_filename.replace(".item", "") + "_",
        delete=False,
    ) as tmp:
        tmp.write(xml_content)
        tmp_path = tmp.name

    try:
        parsed = parse_talend_job(tmp_path)
        parsed.filename = original_filename
        parsed_dict = asdict(parsed)
        converter = TalendToDbtConverter(parsed_dict)
        result = converter.convert(source_schema="main")

        warnings = list(result.warnings)
        if not parsed_dict["targets"]:
            warnings.insert(0,
                "No output component found (e.g. tMysqlOutput / tDBOutput). "
                "Model name was derived from the filename instead of a target table."
            )

        return {
            "success": True,
            "model_name": result.model_name,
            "source_name": result.source_name,
            "sql_content": result.sql_content,
            "schema_yaml": result.schema_yaml,
            "source_yaml": result.source_yaml,
            "source_tables": result.source_tables,
            "warnings": warnings,
            "num_sources": len(parsed_dict["sources"]),
            "num_transforms": len(parsed_dict["transformations"]),
            "num_targets": len(parsed_dict["targets"]),
            "num_connections": len(parsed_dict["connections"]),
            "parsed_dict": parsed_dict,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        os.unlink(tmp_path)


def _convert_with_llm(parsed_dict: dict) -> dict:
    """Send parsed Talend context to the LangGraph agent for SQL generation."""
    try:
        from dotenv import load_dotenv
        load_dotenv()

        from src.agent import build_talend_prompt, run_generation_agent

        prompt, target_name, source_name = build_talend_prompt(parsed_dict)
        result = run_generation_agent(prompt, target_name, source_name)

        if result.get("success"):
            result["model_name"] = result.get("table_name", target_name)
            result["source_name"] = source_name

        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _validate_model(model_name: str, source_name: str, sql_content: str,
                     schema_yaml: str, source_yaml: str, label: str = "Deterministic") -> dict:
    """Write model files and run sqlfluff lint + dbt compile."""
    import yaml

    os.makedirs(GENERATED_MODELS_DIR, exist_ok=True)

    sql_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}.sql")
    schema_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}_schema.yml")
    source_path = os.path.join(GENERATED_MODELS_DIR, f"{source_name}_sources.yml")

    with open(sql_path, "w") as f:
        f.write(sql_content)
    with open(schema_path, "w") as f:
        f.write(schema_yaml)

    # Merge source YAML
    new_sources = yaml.safe_load(source_yaml) or {}
    if os.path.exists(source_path):
        try:
            with open(source_path, "r") as f:
                existing = yaml.safe_load(f.read()) or {}
            existing_map = {}
            for src in existing.get("sources", []):
                existing_map[src["name"]] = src
            for src in new_sources.get("sources", []):
                name = src["name"]
                if name in existing_map:
                    existing_tables = {t["name"] for t in existing_map[name].get("tables", [])}
                    for t in src.get("tables", []):
                        if t["name"] not in existing_tables:
                            existing_map[name].setdefault("tables", []).append(t)
                    if "schema" in src and "schema" not in existing_map[name]:
                        existing_map[name]["schema"] = src["schema"]
                else:
                    existing_map[name] = src
            merged = {"version": 2, "sources": list(existing_map.values())}
        except Exception:
            merged = new_sources
    else:
        merged = new_sources
        if "version" not in merged:
            merged = {"version": 2, **merged}

    with open(source_path, "w") as f:
        yaml.dump(merged, f, default_flow_style=False, sort_keys=False)

    steps = []

    # Step 1: sqlfluff lint
    try:
        proc = subprocess.run(
            [SQLFLUFF_BIN, "lint", sql_path],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        )
        steps.append({
            "name": "sqlfluff lint",
            "passed": proc.returncode == 0,
            "output": proc.stdout.strip() or proc.stderr.strip() or "OK",
        })
    except Exception as exc:
        steps.append({"name": "sqlfluff lint", "passed": False, "output": str(exc)})

    # Step 2: dbt compile
    try:
        proc = subprocess.run(
            [DBT_BIN, "compile", "--profiles-dir", ".", "--select", model_name],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        )
        output = proc.stdout.strip()
        summary = [l for l in output.split("\n") if "Finished" in l or "ERROR" in l or "PASS" in l]
        steps.append({
            "name": "dbt compile",
            "passed": proc.returncode == 0,
            "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
        })
    except Exception as exc:
        steps.append({"name": "dbt compile", "passed": False, "output": str(exc)})

    all_passed = all(s["passed"] for s in steps)
    return {"label": label, "model_name": model_name, "steps": steps, "all_passed": all_passed}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

SAMPLE_JOBS = {
    "🔍 Filter (Simple)": "filter_active_customers.item",
    "🔗 Join (Medium)": "join_orders_customers.item",
    "📊 Aggregate (Complex)": "aggregate_payments.item",
    "🔀 Multi-Filter": "04_multi_filter.item",
    "🔗+🔍 Join + Filter": "05_join_with_filter.item",
    "⚡ Full Pipeline": "06_full_pipeline.item",
}


@app.get("/api/sample-jobs")
def get_sample_jobs():
    """Return all sample Talend jobs with their XML content."""
    jobs = []
    for label, filename in SAMPLE_JOBS.items():
        full_path = os.path.join(TALEND_JOBS_DIR, filename)
        if os.path.exists(full_path):
            with open(full_path, "r") as fh:
                xml_content = fh.read()
            jobs.append({
                "label": label,
                "filename": filename,
                "xml_content": xml_content,
            })
    return {"jobs": jobs}


@app.post("/api/convert")
def convert(request: ConvertRequest):
    """Parse Talend XML and convert to dbt (deterministic mode)."""
    result = _parse_and_convert(request.xml_content, request.filename)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    response = {
        "success": True,
        "deterministic": {
            "model_name": result["model_name"],
            "source_name": result["source_name"],
            "sql_content": result["sql_content"],
            "schema_yaml": result["schema_yaml"],
            "source_yaml": result["source_yaml"],
            "source_tables": result["source_tables"],
            "warnings": result["warnings"],
        },
        "metrics": {
            "sources": result["num_sources"],
            "transforms": result["num_transforms"],
            "targets": result["num_targets"],
            "connections": result["num_connections"],
        },
        "llm": None,
    }

    if request.use_llm:
        llm_result = _convert_with_llm(result["parsed_dict"])
        if llm_result.get("success"):
            response["llm"] = {
                "model_name": llm_result.get("model_name", result["model_name"]),
                "source_name": llm_result.get("source_name", result["source_name"]),
                "sql_content": llm_result.get("sql_content", ""),
                "schema_yaml": llm_result.get("schema_yaml", ""),
                "source_yaml": llm_result.get("source_yaml", ""),
            }
        else:
            response["llm_error"] = llm_result.get("error", "LLM conversion failed")

    return response


@app.post("/api/validate")
def validate(request: ValidateRequest):
    """Run sqlfluff lint + dbt compile on a conversion result."""
    result = _validate_model(
        model_name=request.model_name,
        source_name=request.source_name,
        sql_content=request.sql_content,
        schema_yaml=request.schema_yaml,
        source_yaml=request.source_yaml,
        label=request.label,
    )
    return result


@app.post("/api/download")
def download(request: DownloadRequest):
    """Generate and return a zip of dbt model files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"models/{request.model_name}.sql", request.sql_content)
        zf.writestr(f"models/{request.model_name}_schema.yml", request.schema_yaml)
        zf.writestr(f"models/{request.source_name}_sources.yml", request.source_yaml)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={request.model_name}_dbt.zip"
        },
    )


@app.get("/api/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/check-api-key")
def check_api_key():
    """Check if OPENAI_API_KEY is set in the environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    key = os.environ.get("OPENAI_API_KEY", "")
    return {"has_key": bool(key)}
