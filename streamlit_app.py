"""
dbt Model Agent — Streamlit UI

A visual demo for converting Talend ETL jobs into production-ready dbt models.
Paste XML, upload a file, or click a sample — see the dbt output instantly.

Usage:
    streamlit run streamlit_app.py
"""

import io
import os
import zipfile
import tempfile
from dataclasses import asdict

import streamlit as st

from talend_parser import parse_talend_job
from talend_to_dbt import TalendToDbtConverter

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
# Custom CSS — polished, interview-ready look
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Header gradient */
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

    /* Metric cards */
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

    /* Success / error banners */
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

    /* Sample buttons */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(108, 99, 255, 0.3);
    }

    /* Download button override */
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

    /* Code blocks — tighter */
    .stCodeBlock { border-radius: 8px; }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] { gap: 2rem; }
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        font-size: 0.95rem;
    }

    /* Hide Streamlit footer */
    footer { visibility: hidden; }

    /* Pipeline arrow */
    .pipeline-arrow {
        text-align: center;
        font-size: 2rem;
        color: #6C63FF;
        padding: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sample Talend Jobs (for one-click demo)
# ---------------------------------------------------------------------------
SAMPLE_JOBS = {
    "🔍 Filter (Simple)": "talend_jobs/filter_active_customers.item",
    "🔗 Join (Medium)": "talend_jobs/join_orders_customers.item",
    "📊 Aggregate (Complex)": "talend_jobs/aggregate_payments.item",
}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def parse_and_convert(xml_content: str) -> dict:
    """
    Parse Talend XML content and convert to dbt.
    Returns a dict with all outputs or an error.
    """
    # Write XML to a temp file (parser requires a file path)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".item", delete=False
    ) as tmp:
        tmp.write(xml_content)
        tmp_path = tmp.name

    try:
        # Step 1: Parse
        parsed = parse_talend_job(tmp_path)
        parsed_dict = asdict(parsed)

        # Step 2: Convert
        converter = TalendToDbtConverter(parsed_dict)
        result = converter.convert()

        return {
            "success": True,
            "model_name": result.model_name,
            "source_name": result.source_name,
            "sql_content": result.sql_content,
            "schema_yaml": result.schema_yaml,
            "source_yaml": result.source_yaml,
            "source_tables": result.source_tables,
            "warnings": result.warnings,
            "num_sources": len(parsed_dict["sources"]),
            "num_transforms": len(parsed_dict["transformations"]),
            "num_targets": len(parsed_dict["targets"]),
            "num_connections": len(parsed_dict["connections"]),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        os.unlink(tmp_path)


def create_zip(result: dict) -> bytes:
    """Create an in-memory zip file containing the dbt model files."""
    buf = io.BytesIO()
    model_name = result["model_name"]

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"models/{model_name}.sql",
            result["sql_content"],
        )
        zf.writestr(
            f"models/{model_name}_schema.yml",
            result["schema_yaml"],
        )
        zf.writestr(
            f"models/{result['source_name']}_sources.yml",
            result["source_yaml"],
        )

    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚡ Quick Demo")
    st.caption("Click a sample to see it convert instantly.")

    for label, filepath in SAMPLE_JOBS.items():
        if st.button(label, use_container_width=True):
            full_path = os.path.join(PROJECT_ROOT, filepath)
            with open(full_path, "r") as fh:
                st.session_state["xml_input"] = fh.read()
                st.session_state["auto_convert"] = True

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

# Header
st.markdown("""
<div class="main-header">
    <h1>🔄 dbt Model Agent</h1>
    <p>Convert Talend ETL jobs into production-ready dbt models — instantly, deterministically, no LLM required.</p>
</div>
""", unsafe_allow_html=True)

# Input Section
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

# Convert Button
col_btn, col_space = st.columns([1, 3])
with col_btn:
    convert_clicked = st.button(
        "🚀  Convert to dbt",
        type="primary",
        use_container_width=True,
    )

# Auto-convert when sample is loaded
auto = st.session_state.pop("auto_convert", False)
should_convert = convert_clicked or auto

# ---------------------------------------------------------------------------
# Conversion & Results
# ---------------------------------------------------------------------------
if should_convert and xml_text and xml_text.strip():
    with st.spinner("Converting…"):
        result = parse_and_convert(xml_text)

    if result["success"]:
        # --- Success Banner ---
        st.markdown(
            f'<div class="success-banner">'
            f'✅ Converted successfully → <code>{result["model_name"]}.sql</code>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # --- Metrics Row ---
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="value">{result["num_sources"]}</div>'
                f'<div class="label">Sources</div></div>',
                unsafe_allow_html=True,
            )
        with m2:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="value">{result["num_transforms"]}</div>'
                f'<div class="label">Transforms</div></div>',
                unsafe_allow_html=True,
            )
        with m3:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="value">{result["num_targets"]}</div>'
                f'<div class="label">Targets</div></div>',
                unsafe_allow_html=True,
            )
        with m4:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="value">{result["num_connections"]}</div>'
                f'<div class="label">Connections</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")  # spacer

        # --- Pipeline Visualization ---
        src_tables = ", ".join(result["source_tables"])
        st.markdown(
            f'<div style="text-align: center; padding: 0.8rem; '
            f'background: #1A1D24; border-radius: 10px; border: 1px solid #2D2D3D;">'
            f'<span style="color: #9E9E9E;">Pipeline:</span> &nbsp; '
            f'<code>{src_tables}</code>'
            f' &nbsp;→&nbsp; '
            f'<span style="color: #6C63FF; font-weight: 700;">Converter</span>'
            f' &nbsp;→&nbsp; '
            f'<code>{result["model_name"]}.sql</code>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown("")  # spacer

        # --- Output: SQL + YAML side by side ---
        col_sql, col_yaml = st.columns(2)

        with col_sql:
            st.markdown(f"#### 📄 `{result['model_name']}.sql`")
            st.code(result["sql_content"], language="sql")

        with col_yaml:
            st.markdown(f"#### 📋 `{result['model_name']}_schema.yml`")
            st.code(result["schema_yaml"], language="yaml")

        # --- Sources YAML (collapsible) ---
        with st.expander(
            f"📦 `{result['source_name']}_sources.yml`", expanded=False
        ):
            st.code(result["source_yaml"], language="yaml")

        # --- Warnings ---
        if result["warnings"]:
            with st.expander("⚠️ Warnings", expanded=True):
                for w in result["warnings"]:
                    st.warning(w)

        # --- Download Button ---
        st.markdown("")  # spacer
        zip_bytes = create_zip(result)
        st.download_button(
            label=f"⬇️  Download dbt Project (.zip)",
            data=zip_bytes,
            file_name=f"{result['model_name']}_dbt.zip",
            mime="application/zip",
            use_container_width=True,
        )

    else:
        # --- Error ---
        st.markdown(
            f'<div class="error-banner">'
            f'❌ Conversion failed: {result["error"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

elif should_convert:
    st.warning("Please paste XML or upload a file first.")
