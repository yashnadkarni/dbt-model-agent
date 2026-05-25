# dbt Model Agent

Convert Talend ETL jobs into production-ready dbt models deterministically with optional LLM enhancement. Check it out: https://talend-to-dbt.streamlit.app/

## What This Does

Takes a Talend job (.item file) and converts it into a complete set of dbt files:

| Talend Component | dbt Equivalent |
|---|---|
| `tMysqlInput` (source table) | `{{ source('name', 'table') }}` in SQL + `_sources.yml` |
| `tFilterRow` (filter conditions) | `WHERE` clause |
| `tMap` (column mapping + joins) | `SELECT` expressions + `JOIN` |
| `tAggregateRow` (group by + sum/count) | `GROUP BY` + aggregate functions |
| `tMysqlOutput` (target table) | The model name + `{{ config(materialized='table') }}` |

For each Talend job, the converter generates **3 files**:
- `model_name.sql` — The dbt SQL model (CTE-based, sqlfluff-validated)
- `model_name_schema.yml` — Column definitions + data quality tests (not_null, unique)
- `source_name_sources.yml` — Declares the raw input tables (shared across models)

## Quick Start

### Prerequisites
- Python 3.9+
- (Optional) `OPENAI_API_KEY` for LLM mode

### 1. Setup

```bash
git clone https://github.com/yashnadkarni/dbt-model-agent.git && cd dbt-model-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Seed the Database

This loads sample raw data (customers, orders, payments) into a local DuckDB database:

```bash
venv/bin/dbt seed --profiles-dir .
```

### 3. Run the App

```bash
venv/bin/streamlit run src/ui.py
```

Open **http://localhost:8501** in your browser.

### 4. Sample Demo

1. Click any sample job in the left sidebar (e.g., "Filter Active Customers")
2. See the generated SQL, schema YAML, and source YAML instantly
3. Click "⬇️ Download" to get a zip of all generated files
4. (Optional) Toggle "Use LLM" in the sidebar to compare AI vs deterministic output

### 5. Verify Everything Works

Run the full validation pipeline:

```bash
# Run the full validation pipeline (tests, parsing, conversion, sqlfluff linting, dbt compile/run/test)
./validate.sh
```

Expected results:
- **pytest**: 56/56 tests pass
- **sqlfluff**: "All Finished!"
- **dbt run**: 6 models created, 0 errors
- **dbt test**: 14 data tests pass, 0 failures

## Project Structure

```
dbt-model-agent/
├── src/
│   ├── __init__.py          # Centralized path config
│   ├── parser.py            # Talend XML parser → TalendJob dataclass
│   ├── converter.py         # TalendJob → dbt SQL/YAML converter
│   ├── agent.py             # FastAPI + LangGraph AI agent (optional)
│   └── ui.py                # Streamlit UI (main entry point)
├── fixtures/
│   └── talend_jobs/         # 6 sample Talend .item files
├── seeds/                   # Raw CSV data for DuckDB
│   ├── raw_customers.csv
│   ├── raw_orders.csv
│   └── raw_payments.csv
├── models/
│   └── generated/           # Output: generated dbt models go here
├── tests/                   # pytest test suite
├── dbt_project.yml          # dbt project config
├── profiles.yml             # dbt connection config (DuckDB)
└── .sqlfluff                # SQL linter config
```

## Sample Talend Jobs Included

| Job | Talend Pipeline | What It Tests |
|---|---|---|
| `filter_active_customers.item` | Input → Filter → Output | Simple `WHERE` clause |
| `04_multi_filter.item` | Input → Filter(2 conditions) → Output | `WHERE x AND y` |
| `join_orders_customers.item` | 2 Inputs → tMap(join) → Output | `LEFT JOIN` + column expressions |
| `05_join_with_filter.item` | 2 Inputs → tMap(join) → Filter → Output | `JOIN` + `WHERE` together |
| `aggregate_payments.item` | Input → Aggregate → Output | `GROUP BY` + `SUM`/`COUNT` |
| `06_full_pipeline.item` | 2 Inputs → tMap(join) → Aggregate → Output | `JOIN` + `GROUP BY` + `UPPER()` |

## Running Modes

### Deterministic Mode (default)
Pattern-matched conversion. No API key needed. Handles all 6 supported component types reliably.

### LLM Mode (optional)
Toggle "Use LLM" in the sidebar. Requires `OPENAI_API_KEY` in a `.env` file. Uses GPT-4o-mini via a LangGraph ReAct agent with self-correction (writes SQL → runs sqlfluff → fixes errors automatically).

### FastAPI Server (optional)
For programmatic access:
```bash
venv/bin/uvicorn src.agent:app --host 0.0.0.0 --port 8000
```
Endpoints:
- `POST /convert_talend` — Deterministic conversion
- `POST /generate_model` — LLM-based generation
- `POST /validate_project` — Runs `dbt compile`

> ⚠️ For FastAPI, do **not** use `uvicorn --reload` - the agent writes to `models/generated/` which triggers the file watcher in an infinite loop.
