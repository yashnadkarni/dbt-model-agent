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
from dataclasses import asdict

# Ensure project root is on sys.path (Streamlit runs scripts directly)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

from src import PROJECT_ROOT, TALEND_JOBS_DIR
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter

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
# Sample Jobs
# ---------------------------------------------------------------------------
SAMPLE_JOBS = {
    "🔍 Filter (Simple)": "filter_active_customers.item",
    "🔗 Join (Medium)": "join_orders_customers.item",
    "📊 Aggregate (Complex)": "aggregate_payments.item",
    "🔀 Multi-Filter": "04_multi_filter.item",
    "🔗+🔍 Join + Filter": "05_join_with_filter.item",
    "⚡ Full Pipeline": "06_full_pipeline.item",
    "💰 Revenue Delta": "07_compute_revenue_delta.item",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_and_convert(xml_content: str, original_filename: str = "job.item") -> dict:
    """
    Parse Talend XML and convert deterministically to dbt.

    original_filename is used so that if the Talend job has no recognisable
    output component, the fallback model name is meaningful rather than a
    random temp-file name like 'tmpatc54u1t'.
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
        converter = TalendToDbtConverter(parsed_dict)
        # Pass source_schema='main' because DuckDB seeds land in the 'main' schema
        result = converter.convert(source_schema="main")

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
col_btn, col_space = st.columns([1, 3])
with col_btn:
    convert_clicked = st.button("🚀  Convert to dbt", type="primary", use_container_width=True)

should_convert = convert_clicked

# ---------------------------------------------------------------------------
# Conversion & Results
# ---------------------------------------------------------------------------
if should_convert and xml_text and xml_text.strip():
    # Determine the best filename hint for meaningful model-name fallbacks
    _filename_hint = st.session_state.pop("upload_filename", "job.item")
    with st.spinner("Converting…"):
        result = parse_and_convert(xml_text, original_filename=_filename_hint)

    if result["success"]:
        if use_llm:
            st.markdown(
                f'<div class="success-banner">'
                f'🔧 Deterministic conversion done → <code>{result["model_name"]}.sql</code>. '
                f'<span class="mode-badge mode-llm">Now running LLM agent…</span>'
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
        llm_result = None
        if use_llm:
            with st.spinner("🤖 Running LLM agent…"):
                llm_result = convert_with_llm(result["parsed_dict"])

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
    else:
        st.markdown(
            f'<div class="error-banner">❌ Conversion failed: {result["error"]}</div>',
            unsafe_allow_html=True,
        )
elif should_convert:
    st.warning("Please paste XML or upload a file first.")
