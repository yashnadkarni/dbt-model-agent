"""
dbt Model Agent — Streamlit UI

Paste XML, upload a file, or click a sample — see the dbt output instantly.
Toggle LLM mode to compare deterministic vs. AI-generated output.

Usage:
    streamlit run src/ui.py
"""

import io
import os
import sys
import json
import zipfile
import tempfile
import subprocess
from dataclasses import asdict

# Ensure project root is on sys.path (Streamlit runs scripts directly)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

from src import PROJECT_ROOT, TALEND_JOBS_DIR, GENERATED_MODELS_DIR, DBT_BIN, SQLFLUFF_BIN
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter
from src.connections import ConnectionConfig, ConnectionManager

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="dbt Model Agent",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #6C63FF 0%, #3F3D56 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
    }
    .main-header h1 {
        color: #FFFFFF;
        font-size: 2.2rem;
        margin: 0;
        font-weight: 700;
    }
    .main-header p {
        color: #C4C1E0;
        font-size: 1.05rem;
        margin: 0.5rem 0 0 0;
    }
    .metric-card {
        background: #1A1D24;
        border: 1px solid #2D2D3D;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
    }
    .metric-card .value {
        font-size: 2rem;
        font-weight: 700;
        color: #6C63FF;
    }
    .metric-card .label {
        font-size: 0.85rem;
        color: #9E9E9E;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .success-banner {
        background: linear-gradient(135deg, #1B5E20 0%, #2E7D32 100%);
        border-radius: 10px;
        padding: 1rem 1.5rem;
        color: #E8F5E9;
        font-weight: 600;
        font-size: 1rem;
        margin: 1rem 0;
    }
    .error-banner {
        background: linear-gradient(135deg, #B71C1C 0%, #D32F2F 100%);
        border-radius: 10px;
        padding: 1rem 1.5rem;
        color: #FFEBEE;
        font-weight: 600;
        font-size: 1rem;
        margin: 1rem 0;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(108, 99, 255, 0.3);
    }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #6C63FF 0%, #5A52D5 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.7rem 2rem !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
    }
    .stDownloadButton > button:hover {
        background: linear-gradient(135deg, #7B73FF 0%, #6C63FF 100%) !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(108, 99, 255, 0.4);
    }
    .stCodeBlock { border-radius: 8px; }
    .stTabs [data-baseweb="tab-list"] { gap: 2rem; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; font-size: 0.95rem; }
    footer { visibility: hidden; }
    .mode-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 16px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .mode-deterministic { background: #1B5E20; color: #E8F5E9; }
    .mode-llm { background: #4A148C; color: #E1BEE7; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Connection State Helpers
# ---------------------------------------------------------------------------

def _get_connection_config() -> ConnectionConfig:
    """Return the active ConnectionConfig from session state, defaulting to DuckDB."""
    return st.session_state.get("connection_config", ConnectionConfig(adapter="duckdb"))


def _get_dialect() -> str:
    """Return the active sqlfluff/converter dialect."""
    return _get_connection_config().adapter


# ---------------------------------------------------------------------------
# Sample Jobs
# ---------------------------------------------------------------------------
SAMPLE_JOBS = {
    "🔍 Filter (Simple)": "filter_active_customers.item",
    "🔗 Join (Medium)": "join_orders_customers.item",
    "📊 Aggregate (Complex)": "aggregate_payments.item",
    "🔀 Multi-Filter": "04_multi_filter.item",
    "🔗+🔍 Join + Filter": "05_join_with_filter.item",
    "⚡ Full Pipeline": "06_full_pipeline.item",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_and_convert(xml_content: str, original_filename: str = "job.item", dialect: str = "duckdb") -> dict:
    """
    Parse Talend XML and convert deterministically to dbt.

    original_filename is used so that if the Talend job has no recognisable
    output component, the fallback model name is meaningful rather than a
    random temp-file name like 'tmpatc54u1t'.

    Args:
        dialect: SQL dialect for expression translation ("duckdb" or "snowflake").
    """
    # Write content to a temp file named after the real job file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".item", prefix=original_filename.replace(".item", "") + "_",
        delete=False
    ) as tmp:
        tmp.write(xml_content)
        tmp_path = tmp.name

    try:
        parsed = parse_talend_job(tmp_path)
        # Override the filename with the real name so the model-name fallback
        # (used when no output component is found) is human-readable.
        parsed.filename = original_filename
        parsed_dict = asdict(parsed)
        converter = TalendToDbtConverter(parsed_dict, dialect=dialect)
        # Use the connection config's source_schema
        conn_config = _get_connection_config()
        result = converter.convert(source_schema=conn_config.source_schema)

        warnings = list(result.warnings)
        if not parsed_dict["targets"]:
            warnings.insert(0,
                "⚠️ No output component found (e.g. tMysqlOutput / tDBOutput). "
                "Model name was derived from the filename instead of a target table. "
                "Check that your Talend job has a supported output component with a TABLE value set."
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


def convert_with_llm(parsed_dict: dict) -> dict:
    """
    Send parsed Talend context to the LangGraph agent for SQL generation.

    Delegates prompt-building to agent.build_talend_prompt() so the prompt
    logic lives in one place, then runs the ReAct agent with file writing +
    sqlfluff validation + self-correction.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()

        from src.agent import build_talend_prompt, run_generation_agent

        prompt, target_name, source_name = build_talend_prompt(parsed_dict)
        result = run_generation_agent(prompt, target_name, source_name)

        # Normalize keys to match deterministic result shape
        if result.get("success"):
            result["model_name"] = result.get("table_name", target_name)
            result["source_name"] = source_name

        return result

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def create_zip(result: dict) -> bytes:
    """Create an in-memory zip with the dbt model files."""
    buf = io.BytesIO()
    model_name = result["model_name"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"models/{model_name}.sql", result["sql_content"])
        zf.writestr(f"models/{model_name}_schema.yml", result["schema_yaml"])
        zf.writestr(f"models/{result['source_name']}_sources.yml", result["source_yaml"])
    buf.seek(0)
    return buf.getvalue()


def validate_dbt_model(result: dict, label: str = "Deterministic", dialect: str = "duckdb") -> dict:
    """
    Write a model's generated files to models/generated/ and run the full
    dbt validation pipeline: sqlfluff lint → dbt compile → dbt run → dbt test.

    Args:
        dialect: SQL dialect for sqlfluff ("duckdb" or "snowflake").

    Returns a dict with step-by-step results for display in the UI.
    """
    model_name = result["model_name"]
    source_name = result.get("source_name", "unknown")
    os.makedirs(GENERATED_MODELS_DIR, exist_ok=True)

    # Write SQL and schema (these are per-model, safe to overwrite)
    sql_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}.sql")
    schema_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}_schema.yml")
    source_path = os.path.join(GENERATED_MODELS_DIR, f"{source_name}_sources.yml")
    with open(sql_path, "w") as f:
        f.write(result["sql_content"])
    with open(schema_path, "w") as f:
        f.write(result["schema_yaml"])

    # Merge source YAML into existing file (don't overwrite — shared across models)
    import yaml
    new_sources = yaml.safe_load(result["source_yaml"]) or {}
    if os.path.exists(source_path):
        try:
            with open(source_path, "r") as f:
                existing = yaml.safe_load(f.read()) or {}
            # Build a map of existing source name → source definition
            existing_map = {}
            for src in existing.get("sources", []):
                existing_map[src["name"]] = src
            # Merge new sources into existing
            for src in new_sources.get("sources", []):
                name = src["name"]
                if name in existing_map:
                    # Merge tables: add any new table names
                    existing_tables = {t["name"] for t in existing_map[name].get("tables", [])}
                    for t in src.get("tables", []):
                        if t["name"] not in existing_tables:
                            existing_map[name].setdefault("tables", []).append(t)
                    # Preserve schema if set
                    if "schema" in src and "schema" not in existing_map[name]:
                        existing_map[name]["schema"] = src["schema"]
                else:
                    existing_map[name] = src
            merged = {"version": 2, "sources": list(existing_map.values())}
        except Exception:
            merged = new_sources
    else:
        merged = new_sources
        # Ensure version: 2 is present
        if "version" not in merged:
            merged = {"version": 2, **merged}

    with open(source_path, "w") as f:
        yaml.dump(merged, f, default_flow_style=False, sort_keys=False)

    steps = []

    # Step 1: sqlfluff lint (dialect-aware)
    try:
        proc = subprocess.run(
            [SQLFLUFF_BIN, "lint", "--dialect", dialect, sql_path],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        )
        steps.append({
            "name": "sqlfluff lint",
            "passed": proc.returncode == 0,
            "output": proc.stdout.strip() or proc.stderr.strip() or "OK",
        })
    except Exception as exc:
        steps.append({"name": "sqlfluff lint", "passed": False, "output": str(exc)})

    # Step 2: dbt compile (checks SQL is valid Jinja + SQL)
    try:
        proc = subprocess.run(
            [DBT_BIN, "compile", "--profiles-dir", ".", "--select", model_name],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        )
        output = proc.stdout.strip()
        # Extract just the summary line
        summary = [l for l in output.split("\n") if "Finished" in l or "ERROR" in l or "PASS" in l]
        steps.append({
            "name": "dbt compile",
            "passed": proc.returncode == 0,
            "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
        })
    except Exception as exc:
        steps.append({"name": "dbt compile", "passed": False, "output": str(exc)})

    # # Step 3: dbt run (actually executes the model against DuckDB)
    # try:
    #     proc = subprocess.run(
    #         [DBT_BIN, "run", "--profiles-dir", ".", "--select", model_name],
    #         cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    #     )
    #     output = proc.stdout.strip()
    #     summary = [l for l in output.split("\n") if "OK" in l or "ERROR" in l or "PASS" in l or "FAIL" in l or "Done" in l]
    #     steps.append({
    #         "name": "dbt run",
    #         "passed": proc.returncode == 0,
    #         "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
    #     })
    # except Exception as exc:
    #     steps.append({"name": "dbt run", "passed": False, "output": str(exc)})

    # # Step 4: dbt test (runs not_null/unique data quality tests)
    # try:
    #     proc = subprocess.run(
    #         [DBT_BIN, "test", "--profiles-dir", ".", "--select", model_name],
    #         cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    #     )
    #     output = proc.stdout.strip()
    #     summary = [l for l in output.split("\n") if "PASS" in l or "FAIL" in l or "ERROR" in l or "Done" in l or "Warn" in l]
    #     steps.append({
    #         "name": "dbt test",
    #         "passed": proc.returncode == 0,
    #         "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
    #     })
    # except Exception as exc:
    #     steps.append({"name": "dbt test", "passed": False, "output": str(exc)})

    all_passed = all(s["passed"] for s in steps)
    return {"label": label, "model_name": model_name, "steps": steps, "all_passed": all_passed}


# ---------------------------------------------------------------------------
# Validation Results Renderer
# ---------------------------------------------------------------------------

def _render_validation(val: dict):
    """Render validation results as a styled step-by-step report."""
    overall = "✅ All checks passed" if val["all_passed"] else "❌ Check failed"
    badge_color = "#1B5E20" if val["all_passed"] else "#B71C1C"

    st.markdown(
        f'<div style="background: {badge_color}; border-radius: 8px; padding: 0.6rem 1rem; '
        f'color: white; font-weight: 600; margin: 0.5rem 0;">'
        f'{overall} — {val["label"]} ({val["model_name"]})</div>',
        unsafe_allow_html=True,
    )

    for step in val["steps"]:
        icon = "✅" if step["passed"] else "❌"
        with st.expander(f'{icon} {step["name"]}', expanded=not step["passed"]):
            st.code(step["output"], language="text")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚡ Quick Demo")
    st.caption("Click a sample to paste its XML, then hit Convert.")

    for label, filename in SAMPLE_JOBS.items():
        if st.button(label, use_container_width=True):
            full_path = os.path.join(TALEND_JOBS_DIR, filename)
            with open(full_path, "r") as fh:
                st.session_state["xml_input"] = fh.read()

    st.markdown("---")

    # LLM Toggle
    st.markdown("### 🤖 Conversion Mode")
    use_llm = st.toggle("Use LLM (GPT-4o-mini)", value=False)
    if use_llm:
        st.markdown('<span class="mode-badge mode-llm">LLM Mode</span>', unsafe_allow_html=True)
        st.caption("Sends parsed context to GPT-4o-mini. Requires `OPENAI_API_KEY` in `.env`.")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.environ.get("OPENAI_API_KEY", "")
            except ImportError:
                pass
        if api_key:
            st.success("✓ API key found")
        else:
            st.error("✗ OPENAI_API_KEY not set")
    else:
        st.markdown('<span class="mode-badge mode-deterministic">Deterministic</span>', unsafe_allow_html=True)
        st.caption("Pattern-matched translation. No API key needed.")

    st.markdown("---")
    st.markdown("### How It Works")
    st.markdown("""
    1. **Parse** — Reads Talend XML structure
    2. **Translate** — Java expressions → SQL
    3. **Generate** — CTE-based dbt SQL + YAML
    4. **Package** — Downloadable zip file
    """)
    st.markdown("---")
    st.markdown("### Component Support")
    st.markdown("""
    | Component | Status |
    |---|---|
    | `tFilterRow` | ✅ |
    | `tMap` (join) | ✅ |
    | `tMap` (mapping) | ✅ |
    | `tAggregateRow` | ✅ |
    | `tNormalize` | ❌ |
    | `tUnite` | ❌ |
    """)
    st.markdown("---")

    # --- Warehouse Connection ---
    st.markdown("### ❄️ Warehouse Connection")

    adapter_options = {"DuckDB (Local)":  "duckdb", "Snowflake": "snowflake", "Databricks": "databricks"}
    selected_label = st.selectbox(
        "Adapter",
        list(adapter_options.keys()),
        index=0,
        help="Select your data warehouse. Default: DuckDB.",
    )
    selected_adapter = adapter_options[selected_label]

    if selected_adapter == "duckdb":
        st.session_state["connection_config"] = ConnectionConfig(adapter="duckdb")
        st.session_state["warehouse_connected"] = False
        st.success("✓ DuckDB (local) — no credentials needed")

    elif selected_adapter == "snowflake":
        st.caption("Enter your Snowflake credentials. These are stored only in session memory.")

        # if st.button("📂 Load from .env", use_container_width=True, key="sf_load_env"):
        #     try:
        #         from dotenv import load_dotenv
        #         load_dotenv(override=True)
        #     except ImportError:
        #         pass
        #     st.session_state["sf_account"] = os.environ.get("SNOWFLAKE_ACCOUNT", "")
        #     st.session_state["sf_user"] = os.environ.get("SNOWFLAKE_USER", "")
        #     st.session_state["sf_password"] = os.environ.get("SNOWFLAKE_PASSWORD", "")
        #     st.session_state["sf_role"] = os.environ.get("SNOWFLAKE_ROLE", "")
        #     st.session_state["sf_warehouse"] = os.environ.get("SNOWFLAKE_WAREHOUSE", "")
        #     st.session_state["sf_database"] = os.environ.get("SNOWFLAKE_DATABASE", "")
        #     st.session_state["sf_schema"] = os.environ.get("SNOWFLAKE_SCHEMA", "")
        #     st.rerun()

        sf_account = st.text_input("Account", placeholder="ORGNAME-ACCOUNTNAME", key="sf_account")
        sf_user = st.text_input("User", key="sf_user")
        sf_password = st.text_input("Password", type="password", key="sf_password")
        sf_role = st.text_input("Role", placeholder="TRANSFORM_ROLE (optional)", key="sf_role")
        sf_warehouse = st.text_input("Warehouse", placeholder="TRANSFORM_WH", key="sf_warehouse")
        sf_database = st.text_input("Database", placeholder="ANALYTICS", key="sf_database")
        sf_schema = st.text_input("Schema", placeholder="DBT_DEV", key="sf_schema")

        sf_config = ConnectionConfig(
            adapter="snowflake",
            account=sf_account,
            user=sf_user,
            password=sf_password,
            role=sf_role,
            warehouse=sf_warehouse,
            database=sf_database,
            schema=sf_schema,
        )
        st.session_state["connection_config"] = sf_config

        if st.button("🔌 Test Connection", use_container_width=True, key="sf_test"):
            missing = sf_config.validate()
            if missing:
                st.error(f"Missing fields: {', '.join(missing)}")
            else:
                with st.spinner("Connecting to Snowflake…"):
                    mgr = ConnectionManager(sf_config)
                    result = mgr.test_connection()
                if result["success"]:
                    st.success(f"✓ {result['message']}")
                    st.session_state["warehouse_connected"] = True
                else:
                    st.error(f"✗ {result['message']}")
                    st.session_state["warehouse_connected"] = False

    elif selected_adapter == "databricks":
        st.caption("Enter your Databricks credentials. These are stored only in session memory.")

        # if st.button("📂 Load from .env", use_container_width=True, key="db_load_env"):
        #     try:
        #         from dotenv import load_dotenv
        #         load_dotenv(override=True)
        #     except ImportError:
        #         pass
        #     st.session_state["db_host"] = os.environ.get("DATABRICKS_HOST", "")
        #     st.session_state["db_token"] = os.environ.get("DATABRICKS_TOKEN", "")
        #     st.session_state["db_http_path"] = os.environ.get("DATABRICKS_HTTP_PATH", "")
        #     st.session_state["db_catalog"] = os.environ.get("DATABRICKS_CATALOG", "")
        #     st.session_state["db_schema"] = os.environ.get("DATABRICKS_SCHEMA", "")
        #     st.rerun()

        db_host = st.text_input("Host", placeholder="dbc-xxxxx.cloud.databricks.com", key="db_host")
        db_token = st.text_input("Token (PAT)", type="password", key="db_token")
        db_http_path = st.text_input("HTTP Path", placeholder="/sql/1.0/warehouses/...", key="db_http_path")
        db_catalog = st.text_input("Catalog", placeholder="hive_metastore (optional)", key="db_catalog")
        db_schema = st.text_input("Schema", placeholder="default", key="db_schema")

        db_config = ConnectionConfig(
            adapter="databricks",
            host=db_host,
            token=db_token,
            http_path=db_http_path,
            catalog=db_catalog,
            schema=db_schema,
        )
        st.session_state["connection_config"] = db_config

        if st.button("🔌 Test Connection", use_container_width=True, key="db_test"):
            missing = db_config.validate()
            if missing:
                st.error(f"Missing fields: {', '.join(missing)}")
            else:
                with st.spinner("Connecting to Databricks…"):
                    mgr = ConnectionManager(db_config)
                    result = mgr.test_connection()
                if result["success"]:
                    st.success(f"✓ {result['message']}")
                    st.session_state["warehouse_connected"] = True
                else:
                    st.error(f"✗ {result['message']}")
                    st.session_state["warehouse_connected"] = False

    st.markdown("---")
    st.caption("Built with LangGraph, FastAPI, DuckDB")
    st.caption("[GitHub](https://github.com/yashnadkarni/dbt-model-agent)")


# ---------------------------------------------------------------------------
# Main Content
# ---------------------------------------------------------------------------

st.markdown("""
<div class="main-header">
    <h1>🔄 dbt Model Agent</h1>
    <p>Convert Talend ETL jobs into production-ready dbt models — instantly, deterministically, no LLM required.</p>
</div>
""", unsafe_allow_html=True)

# Input
tab_paste, tab_upload = st.tabs(["📋  Paste XML", "📁  Upload File"])

with tab_paste:
    xml_text = st.text_area(
        "Paste your Talend .item XML here",
        value=st.session_state.get("xml_input", ""),
        height=280,
        placeholder="<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<xmi:XMI ...>\n  ...\n</xmi:XMI>",
    )

with tab_upload:
    uploaded = st.file_uploader(
        "Upload a Talend .item file",
        type=["item", "xml"],
        help="Exported from Talend Open Studio",
    )
    if uploaded is not None:
        xml_text = uploaded.read().decode("utf-8")
        # Store the real filename so parse_and_convert can use it as a fallback
        st.session_state["upload_filename"] = uploaded.name

# Convert Button
col_btn, col_refresh, col_space = st.columns([1, 1, 2])
with col_btn:
    convert_clicked = st.button("🚀  Convert to dbt", type="primary", use_container_width=True)
with col_refresh:
    if st.button("🔄 Refresh", use_container_width=True):
        st.session_state.pop("conversion_result", None)
        st.session_state.pop("llm_conversion_result", None)

# ---------------------------------------------------------------------------
# Conversion & Results
# ---------------------------------------------------------------------------
if convert_clicked:
    if not xml_text or not xml_text.strip():
        st.warning("Please paste XML or upload a file first.")
    else:
        # Determine the best filename hint for meaningful model-name fallbacks
        _filename_hint = st.session_state.pop("upload_filename", "job.item")
        with st.spinner("Converting…"):
            dialect = _get_dialect()
            result = parse_and_convert(xml_text, original_filename=_filename_hint, dialect=dialect)
            st.session_state["conversion_result"] = result
            
            # Clear previous LLM result
            st.session_state.pop("llm_conversion_result", None)
            
            if use_llm and result["success"]:
                with st.spinner("🤖 Running LLM agent…"):
                    llm_result = convert_with_llm(result["parsed_dict"])
                    st.session_state["llm_conversion_result"] = llm_result

if "conversion_result" in st.session_state:
    result = st.session_state["conversion_result"]
    llm_result = st.session_state.get("llm_conversion_result")

    if result["success"]:
        if use_llm and llm_result:
            st.markdown(
                f'<div class="success-banner">'
                f'🔧 Deterministic conversion done → <code>{result["model_name"]}.sql</code>. '
                f'<span class="mode-badge mode-llm">LLM Agent run complete</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="success-banner">'
                f'✅ Converted successfully → <code>{result["model_name"]}.sql</code> '
                f'<span class="mode-badge mode-deterministic">Deterministic</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        for col, val, label in [
            (m1, result["num_sources"], "Sources"),
            (m2, result["num_transforms"], "Transforms"),
            (m3, result["num_targets"], "Targets"),
            (m4, result["num_connections"], "Connections"),
        ]:
            with col:
                st.markdown(
                    f'<div class="metric-card"><div class="value">{val}</div>'
                    f'<div class="label">{label}</div></div>',
                    unsafe_allow_html=True,
                )

        st.markdown("")

        # Pipeline
        src_tables = ", ".join(result["source_tables"])
        st.markdown(
            f'<div style="text-align: center; padding: 0.8rem; '
            f'background: #1A1D24; border-radius: 10px; border: 1px solid #2D2D3D;">'
            f'<span style="color: #9E9E9E;">Pipeline:</span> &nbsp; '
            f'<code>{src_tables}</code>'
            f' &nbsp;→&nbsp; '
            f'<span style="color: #6C63FF; font-weight: 700;">Converter</span>'
            f' &nbsp;→&nbsp; '
            f'<code>{result["model_name"]}.sql</code></div>',
            unsafe_allow_html=True,
        )

        st.markdown("")

        # --- LLM Mode: side-by-side ---
        if use_llm and llm_result:
            if llm_result["success"]:
                st.markdown(
                    f'<div class="success-banner">'
                    f'✅ LLM agent completed → <code>{llm_result.get("model_name", result["model_name"])}.sql</code> '
                    f'<span class="mode-badge mode-llm">LLM (self-corrected)</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # Side-by-side SQL comparison
                col_det, col_llm = st.columns(2)
                with col_det:
                    st.markdown("#### 🔧 Deterministic Output")
                    st.code(result["sql_content"], language="sql")
                with col_llm:
                    st.markdown("#### 🤖 LLM Output")
                    st.code(llm_result["sql_content"], language="sql")

                # LLM schema + source YAML
                if llm_result.get("schema_yaml"):
                    with st.expander("🤖 LLM Schema YAML", expanded=False):
                        st.code(llm_result["schema_yaml"], language="yaml")
                if llm_result.get("source_yaml"):
                    with st.expander("🤖 LLM Source YAML", expanded=False):
                        st.code(llm_result["source_yaml"], language="yaml")
            else:
                st.warning(f"LLM conversion failed: {llm_result['error']}")
                # Fall back to showing deterministic output
                col_sql, col_yaml = st.columns(2)
                with col_sql:
                    st.markdown(f"#### 📄 `{result['model_name']}.sql`")
                    st.code(result["sql_content"], language="sql")
                with col_yaml:
                    st.markdown(f"#### 📋 `{result['model_name']}_schema.yml`")
                    st.code(result["schema_yaml"], language="yaml")
        else:
            # --- Deterministic only: SQL + YAML side by side ---
            col_sql, col_yaml = st.columns(2)
            with col_sql:
                st.markdown(f"#### 📄 `{result['model_name']}.sql`")
                st.code(result["sql_content"], language="sql")
            with col_yaml:
                st.markdown(f"#### 📋 `{result['model_name']}_schema.yml`")
                st.code(result["schema_yaml"], language="yaml")

        # Sources YAML (deterministic)
        with st.expander(f"📦 `{result['source_name']}_sources.yml`", expanded=False):
            st.code(result["source_yaml"], language="yaml")

        # Warnings
        if result["warnings"]:
            with st.expander("⚠️ Warnings", expanded=True):
                for w in result["warnings"]:
                    st.warning(w)

        # Download — Deterministic
        st.markdown("")
        zip_bytes = create_zip(result)
        st.download_button(
            label="⬇️  Download Deterministic Output (.zip)",
            data=zip_bytes,
            file_name=f"{result['model_name']}_dbt.zip",
            mime="application/zip",
            use_container_width=True,
        )

        # Download — LLM (if available)
        if llm_result and llm_result.get("success") and llm_result.get("sql_content"):
            llm_zip = create_zip(llm_result)
            st.download_button(
                label="⬇️  Download LLM Output (.zip)",
                data=llm_zip,
                file_name=f"{llm_result['model_name']}_llm_dbt.zip",
                mime="application/zip",
                use_container_width=True,
            )

        # --- Validate with dbt ---
        st.markdown("")
        st.markdown("---")
        
        
        validate_clicked = st.button(
            "🔍  Validate with dbt",
            type = "primary",
            use_container_width=True,
            help="Write generated files to disk and run: sqlfluff lint → dbt compile → dbt run → dbt test",
        )

        if validate_clicked:
            has_llm = llm_result and llm_result.get("success") and llm_result.get("sql_content")
            dialect = _get_dialect()

            if has_llm:
                # Side-by-side validation
                col_val_det, col_val_llm = st.columns(2)
                with col_val_det:
                    with st.spinner("Validating deterministic output…"):
                        val_det = validate_dbt_model(result, label="Deterministic", dialect=dialect)
                    _render_validation(val_det)
                with col_val_llm:
                    with st.spinner("Validating LLM output…"):
                        val_llm = validate_dbt_model(llm_result, label="LLM", dialect=dialect)
                    _render_validation(val_llm)
            else:
                with st.spinner("Validating deterministic output…"):
                    val_det = validate_dbt_model(result, label="Deterministic", dialect=dialect)
                _render_validation(val_det)
            
            st.warning("⚠️ **Note:** Only `sqlfluff lint` and `dbt compile` are expected to pass. `dbt run` and `dbt test` need to be tested after connecting to your database.")

        # --- Deploy to Warehouse ---
        conn_config = _get_connection_config()
        if conn_config.adapter != "duckdb":
            st.markdown("")
            st.markdown("---")
            st.markdown("### 🚀 Deploy to Warehouse")

            is_connected = st.session_state.get("warehouse_connected", False)
            if not is_connected:
                st.info("🔌 Connect to your warehouse first (sidebar) to enable deployment.")

            # Let user choose which output to deploy when LLM result is available
            has_llm_result = llm_result and llm_result.get("success") and llm_result.get("sql_content")
            if has_llm_result:
                deploy_source = st.radio(
                    "Deploy which output?",
                    ["🔧 Deterministic", "🤖 LLM"],
                    index=0,
                    horizontal=True,
                    help="Choose which generated model to deploy to the warehouse.",
                )
                deploy_result = llm_result if deploy_source == "🤖 LLM" else result
            else:
                deploy_result = result

            deploy_clicked = st.button(
                f"🚀  Deploy to {conn_config.adapter.title()}",
                type="primary",
                use_container_width=True,
                disabled=not is_connected,
                help=f"Generate profiles.yml for {conn_config.adapter.title()}, then run dbt seed + dbt run + dbt test.",
            )

            if deploy_clicked and is_connected:
                # Step 1: Write dynamic profiles.yml for the target warehouse
                mgr = ConnectionManager(conn_config)
                mgr.write_profiles_yml()

                deploy_steps = []

                # Step 2: Clean generated models dir and write ONLY this model's files
                # This prevents stale source YAMLs from other models causing
                # "source not found" compilation errors.
                model_name = deploy_result["model_name"]
                source_name = deploy_result.get("source_name", "unknown")

                # Remove all existing files in generated dir to start clean
                if os.path.isdir(GENERATED_MODELS_DIR):
                    for f in os.listdir(GENERATED_MODELS_DIR):
                        os.remove(os.path.join(GENERATED_MODELS_DIR, f))
                os.makedirs(GENERATED_MODELS_DIR, exist_ok=True)

                sql_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}.sql")
                schema_path = os.path.join(GENERATED_MODELS_DIR, f"{model_name}_schema.yml")
                source_path = os.path.join(GENERATED_MODELS_DIR, f"{source_name}_sources.yml")

                with open(sql_path, "w") as f:
                    f.write(deploy_result["sql_content"])
                with open(schema_path, "w") as f:
                    f.write(deploy_result["schema_yaml"])

                # Write source YAML directly from the conversion result
                # (it already has version: 2 and all source tables)
                with open(source_path, "w") as f:
                    f.write(deploy_result["source_yaml"])

                # Step 3: dbt seed (load CSV data into the warehouse)
                with st.spinner(f"Seeding raw data into {conn_config.adapter.title()}…"):
                    try:
                        proc = subprocess.run(
                            [DBT_BIN, "seed", "--profiles-dir", "."],
                            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
                        )
                        output = proc.stdout.strip()
                        summary = [l for l in output.split("\n") if "OK" in l or "ERROR" in l or "PASS" in l or "FAIL" in l or "Done" in l or "seed" in l.lower()]
                        deploy_steps.append({
                            "name": "dbt seed",
                            "passed": proc.returncode == 0,
                            "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
                        })
                    except Exception as exc:
                        deploy_steps.append({"name": "dbt seed", "passed": False, "output": str(exc)})

                # Step 4: dbt run (only if seed succeeded)
                if deploy_steps[-1]["passed"]:
                    with st.spinner(f"Running dbt run against {conn_config.adapter.title()}…"):
                        try:
                            proc = subprocess.run(
                                [DBT_BIN, "run", "--profiles-dir", ".", "--select", model_name],
                                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
                            )
                            output = proc.stdout.strip()
                            summary = [l for l in output.split("\n") if "OK" in l or "ERROR" in l or "PASS" in l or "FAIL" in l or "Done" in l]
                            deploy_steps.append({
                                "name": "dbt run",
                                "passed": proc.returncode == 0,
                                "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
                            })
                        except Exception as exc:
                            deploy_steps.append({"name": "dbt run", "passed": False, "output": str(exc)})
                else:
                    deploy_steps.append({"name": "dbt run", "passed": False, "output": "Skipped — dbt seed failed"})

                # Step 5: dbt test (only if run succeeded)
                if len(deploy_steps) >= 2 and deploy_steps[-1]["passed"]:
                    with st.spinner(f"Running dbt test against {conn_config.adapter.title()}…"):
                        try:
                            proc = subprocess.run(
                                [DBT_BIN, "test", "--profiles-dir", ".", "--select", model_name],
                                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
                            )
                            output = proc.stdout.strip()
                            summary = [l for l in output.split("\n") if "PASS" in l or "FAIL" in l or "ERROR" in l or "Done" in l or "Warn" in l]
                            deploy_steps.append({
                                "name": "dbt test",
                                "passed": proc.returncode == 0,
                                "output": "\n".join(summary) if summary else output[-500:] if output else proc.stderr.strip()[-500:],
                            })
                        except Exception as exc:
                            deploy_steps.append({"name": "dbt test", "passed": False, "output": str(exc)})
                else:
                    deploy_steps.append({"name": "dbt test", "passed": False, "output": "Skipped — dbt run failed"})

                # Render deploy results
                all_passed = all(s["passed"] for s in deploy_steps)
                _render_validation({
                    "label": f"Deploy ({conn_config.adapter.title()})",
                    "model_name": model_name,
                    "steps": deploy_steps,
                    "all_passed": all_passed,
                })

                # Step 6: Restore DuckDB profiles.yml
                duckdb_mgr = ConnectionManager(ConnectionConfig(adapter="duckdb"))
                duckdb_mgr.write_profiles_yml()
                st.caption("ℹ️ profiles.yml restored to DuckDB default after deployment.")


    else:
        st.markdown(
            f'<div class="error-banner">❌ Conversion failed: {result["error"]}</div>',
            unsafe_allow_html=True,
        )
