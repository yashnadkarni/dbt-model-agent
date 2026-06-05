# dbt Model Agent

Convert Talend ETL jobs into production-ready dbt models deterministically with optional LLM enhancement. Deploy to **DuckDB** (local), **Snowflake**, or **Databricks**. Check it out: https://talend-to-dbt.streamlit.app/

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
2. Click **"🚀 Convert to dbt"** to generate the dbt model
3. Review the generated SQL, schema YAML, and source YAML
4. Click **"⬇️ Download"** to get a zip of all generated files
5. Click **"🔍 Validate with dbt"** to run the full dbt pipeline (sqlfluff lint → dbt compile → dbt run → dbt test) and see pass/fail results
6. (Optional) Toggle "Use LLM" in the sidebar to compare AI vs deterministic output — validation runs side-by-side for both

### 5. Verify Everything Works

Run the full validation pipeline:

```bash
# Run the full validation pipeline (tests, parsing, conversion, sqlfluff linting, dbt compile/run/test)
./validate.sh
```

Expected results:
- **pytest**: 120+ tests pass
- **sqlfluff**: "All Finished!"
- **dbt run**: 6 models created, 0 errors
- **dbt test**: 14 data tests pass, 0 failures

## Project Structure

```
dbt-model-agent/
├── src/
│   ├── __init__.py          # Centralized path config
│   ├── parser.py            # Talend XML parser → TalendJob dataclass
│   ├── converter.py         # TalendJob → dbt SQL/YAML converter (dialect-aware)
│   ├── connections.py       # Connection manager (DuckDB, Snowflake)
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
├── profiles.yml             # dbt connection config (DuckDB default)
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

## Snowflake Deployment

### Prerequisites
- A Snowflake account (sign up at [snowflake.com](https://snowflake.com) → choose **AI Data Cloud for Enterprise**)
- `dbt-snowflake` adapter: `pip install dbt-snowflake`
- `snowflake-connector-python`: `pip install snowflake-connector-python`

### 1. Snowflake Setup (One-Time)

In your Snowflake account, run these SQL commands to create the required objects:

```sql
-- Create a warehouse for dbt transformations
CREATE WAREHOUSE IF NOT EXISTS TRANSFORM_WH
  WAREHOUSE_SIZE = 'X-SMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

-- Create a database and schema
CREATE DATABASE IF NOT EXISTS ANALYTICS;
CREATE SCHEMA IF NOT EXISTS ANALYTICS.DBT_DEV;

-- Create a role (optional but recommended)
CREATE ROLE IF NOT EXISTS TRANSFORM_ROLE;
GRANT USAGE ON WAREHOUSE TRANSFORM_WH TO ROLE TRANSFORM_ROLE;
GRANT ALL ON DATABASE ANALYTICS TO ROLE TRANSFORM_ROLE;
GRANT ALL ON SCHEMA ANALYTICS.DBT_DEV TO ROLE TRANSFORM_ROLE;
GRANT ROLE TRANSFORM_ROLE TO USER your_username;
```

### 2. Configure Credentials

Add your Snowflake credentials to `.env`:

```bash
SNOWFLAKE_ACCOUNT=ORGNAME-ACCOUNTNAME
SNOWFLAKE_USER=your-username
SNOWFLAKE_PASSWORD=your-password
SNOWFLAKE_ROLE=TRANSFORM_ROLE
SNOWFLAKE_WAREHOUSE=TRANSFORM_WH
SNOWFLAKE_DATABASE=ANALYTICS
SNOWFLAKE_SCHEMA=DBT_DEV
```

> 💡 Your Snowflake account identifier is in one of two formats:
> - **Modern (org-based):** `ORGNAME-ACCOUNTNAME` (e.g., `TDDRXUV-HN35889`) — found in your Snowflake URL as `https://app.snowflake.com/TDDRXUV/HN35889`
> - **Legacy (locator):** `xy12345.us-east-1` — the part before `.snowflakecomputing.com` in the older URL format

### 3. Deploy via the UI

1. Run the Streamlit app: `venv/bin/streamlit run src/ui.py`
2. In the sidebar under **❄️ Warehouse Connection**, select **Snowflake**
3. Enter your credentials and click **🔌 Test Connection**
4. Convert a Talend job as usual
5. Click **🚀 Deploy to Snowflake** to run `dbt run` + `dbt test` against your warehouse

> ⚠️ For Snowflake deployment, your source tables must already exist in the target database/schema. The seed data (raw_customers, raw_orders, raw_payments) can be loaded via `dbt seed` after switching the profile.

### 4. Deploy via CLI (Alternative)

You can also generate a Snowflake profiles.yml from Python:

```python
from src.connections import ConnectionConfig, ConnectionManager

config = ConnectionConfig.from_env("snowflake")
mgr = ConnectionManager(config)
mgr.write_profiles_yml()  # writes profiles.yml to project root

# Then run dbt commands as usual:
# dbt seed --profiles-dir .
# dbt run --profiles-dir .
# dbt test --profiles-dir .
```

## Databricks Deployment

### Prerequisites
- A Databricks workspace (sign up at [databricks.com/try](https://www.databricks.com/try-databricks) → choose **Personal / Community Edition** to start free)
- `dbt-databricks` adapter: `pip install dbt-databricks`
- `databricks-sql-connector`: `pip install databricks-sql-connector`

### 1. Databricks Setup (One-Time)

1. **Create a SQL Warehouse**:
   - Go to your Databricks workspace → SQL Warehouses → Create SQL Warehouse
   - Choose "Serverless" or "Pro" (smallest size is fine)
   - Note the **HTTP Path** from the Connection Details tab

2. **Generate a Personal Access Token (PAT)**:
   - Settings → Developer → Access Tokens → Generate New Token
   - Give it a name (e.g., "dbt-agent") and copy the token

3. **Note down your workspace host**:
   - This is the URL of your workspace, e.g., `dbc-xxxxx.cloud.databricks.com`

### 2. Configure Credentials

Add your Databricks credentials to `.env`:

```bash
DATABRICKS_HOST=dbc-xxxxx.cloud.databricks.com
DATABRICKS_TOKEN=dapi-your-personal-access-token
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abcdef123456
DATABRICKS_CATALOG=hive_metastore
DATABRICKS_SCHEMA=default
```

> 💡 `DATABRICKS_CATALOG` is optional. If omitted, Databricks defaults to `hive_metastore`. If your workspace uses Unity Catalog, set it to your catalog name.

### 3. Deploy via the UI

1. Run the Streamlit app: `venv/bin/streamlit run src/ui.py`
2. In the sidebar under **❄️ Warehouse Connection**, select **Databricks**
3. Enter your credentials (or click **📂 Load from .env**) and click **🔌 Test Connection**
4. Convert a Talend job as usual
5. Click **🚀 Deploy to Databricks** to run `dbt seed + dbt run + dbt test`

## GitHub Integration (Push to GitHub / Create PR)

### Prerequisites
- A GitHub account with access to the target repository
- A **Personal Access Token (PAT)** with `repo` scope
- `PyGithub`: `pip install PyGithub`

### 1. Create a GitHub PAT (One-Time)

1. Go to [GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Give it a name (e.g., "dbt-model-agent")
4. Select the `repo` scope (full control of private repositories)
5. Click **Generate token** and copy it

### 2. Configure Credentials

Add to your `.env` file:

```bash
GITHUB_TOKEN=ghp_your-personal-access-token
GITHUB_REPO=owner/repo-name
```

### 3. Use via the UI

1. Run the Streamlit app: `venv/bin/streamlit run src/ui.py`
2. In the sidebar under **🐙 GitHub Integration**, enter your token and repository
3. Click **🔌 Test GitHub Connection**
4. Convert a Talend job as usual
5. Scroll down to **🐙 Push to GitHub** and click **🚀 Create Pull Request**

This will:
- Create a new branch: `dbt/migrate-<model_name>-<timestamp>`
- Commit the SQL model, schema YAML, and source YAML
- Open a Pull Request with validation results in the description
