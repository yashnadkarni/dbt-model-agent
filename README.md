# dbt-model-agent

An AI-powered agent and deterministic converter that generates production-ready [dbt](https://www.getdbt.com/) models — from JSON schemas or Talend ETL jobs. Built with **LangGraph**, **FastAPI**, and **DuckDB**.

## Features

### Phase 1 — AI Agent (JSON Schema → dbt)
Give the agent a JSON schema and it autonomously generates a validated dbt model:
- Generates `.sql` model + `.yml` schema with `not_null`, `unique`, `accepted_values` tests
- Self-corrects using `sqlfluff lint` feedback in a retry loop
- Merges source definitions across multiple requests

### Phase 2 — Talend Converter (Talend XML → dbt)
Drop in a Talend `.item` export and get a dbt model — **no LLM required**:
- Parses Talend XML (tMap, tFilterRow, tAggregateRow)
- Translates Java expressions to SQL deterministically
- Generates CTE-based dbt SQL with `{{ source() }}` macros
- Passes `sqlfluff lint` and `dbt compile` validation

### Streamlit UI — Visual Demo
A polished web interface for live demos:
- Paste XML or upload `.item` files
- One-click sample jobs for instant results
- Side-by-side SQL + YAML output with pipeline visualization
- Download generated dbt project as a zip file

---

## Before / After: Talend → dbt

### Example 1: Filter (`tFilterRow`)

<table>
<tr><th>Talend XML (input)</th><th>dbt SQL (output)</th></tr>
<tr>
<td>

```xml
<node componentName="tMysqlInput">
  <elementParameter name="TABLE"
    value="&quot;raw_customers&quot;"/>
</node>

<node componentName="tFilterRow">
  <elementParameter name="CONDITIONS">
    <elementValue elementRef="INPUT_COLUMN"
      value="status"/>
    <elementValue elementRef="OPERATOR"
      value="=="/>
    <elementValue elementRef="RVALUE"
      value="&quot;active&quot;"/>
  </elementParameter>
</node>

<node componentName="tMysqlOutput">
  <elementParameter name="TABLE"
    value="&quot;active_customers&quot;"/>
</node>
```

</td>
<td>

```sql
{{ config(materialized='table') }}

SELECT
    id,
    first_name,
    last_name,
    email,
    status
FROM {{ source('jaffle_shop', 'raw_customers') }}
WHERE status = 'active'
```

</td>
</tr>
</table>

### Example 2: Join (`tMap` with LEFT JOIN)

<table>
<tr><th>Talend XML (input)</th><th>dbt SQL (output)</th></tr>
<tr>
<td>

```xml
<!-- Two inputs: orders + customers -->
<inputTables name="row1">  <!-- orders -->
  <mapperTableEntries name="id"/>
  <mapperTableEntries name="user_id"/>
</inputTables>

<inputTables name="row2" innerJoin="false">
  <!-- LEFT JOIN: row2.id = row1.user_id -->
  <mapperTableEntries name="id"
    expression="row1.user_id"/>
  <mapperTableEntries name="first_name"/>
  <mapperTableEntries name="last_name"/>
</inputTables>

<outputTables name="out1">
  <mapperTableEntries name="order_id"
    expression="row1.id"/>
  <mapperTableEntries name="customer_name"
    expression='row2.first_name + " " 
    + row2.last_name'/>
  <mapperTableEntries name="amount_dollars"
    expression="row1.amount / 100.0"/>
</outputTables>
```

</td>
<td>

```sql
{{ config(materialized='table') }}

WITH orders AS (
    SELECT * FROM {{ source('jaffle_shop',
      'raw_orders') }}
),

customers AS (
    SELECT * FROM {{ source('jaffle_shop',
      'raw_customers') }}
)

SELECT
    orders.id AS order_id,
    orders.user_id AS customer_id,
    orders.order_date,
    orders.status,
    customers.first_name || ' '
      || customers.last_name
      AS customer_name,
    orders.amount / 100.0 AS amount_dollars
FROM orders
LEFT JOIN customers
    ON orders.user_id = customers.id
```

</td>
</tr>
</table>

### Example 3: Aggregation (`tMap` + `tAggregateRow`)

<table>
<tr><th>Talend XML (input)</th><th>dbt SQL (output)</th></tr>
<tr>
<td>

```xml
<!-- tMap: rename + transform -->
<outputTables name="out1">
  <mapperTableEntries name="payment_id"
    expression="row1.id"/>
  <mapperTableEntries name="payment_method"
    expression="StringHandling.UPCASE(
      row1.payment_method)"/>
  <mapperTableEntries name="amount_dollars"
    expression="row1.amount / 100.0"/>
</outputTables>

<!-- tAggregateRow: GROUP BY -->
<elementParameter name="GROUP_BY">
  <elementValue elementRef="INPUT_COLUMN"
    value="payment_method"/>
</elementParameter>
<elementParameter name="OPERATIONS">
  <elementValue elementRef="INPUT_COLUMN"
    value="amount_dollars"/>
  <elementValue elementRef="FUNCTION"
    value="sum"/>
  <elementValue elementRef="OUTPUT_COLUMN"
    value="total_amount"/>
</elementParameter>
```

</td>
<td>

```sql
{{ config(materialized='table') }}

WITH payments AS (
    SELECT * FROM {{ source('jaffle_shop',
      'raw_payments') }}
),

transformed AS (
    SELECT
        payments.id AS payment_id,
        payments.order_id,
        UPPER(payments.payment_method)
          AS payment_method,
        payments.amount / 100.0
          AS amount_dollars
    FROM payments
)

SELECT
    payment_method,
    SUM(amount_dollars) AS total_amount,
    COUNT(payment_id) AS transaction_count
FROM transformed
GROUP BY payment_method
```

</td>
</tr>
</table>

---

## Architecture

```
                    Phase 1 (AI Agent)                          Phase 2 (Deterministic)
              ┌─────────────────────────┐                ┌──────────────────────────────┐
              │                         │                │                              │
JSON Schema ──▶  POST /generate_model   │   Talend XML ──▶  POST /convert_talend       │
              │                         │                │                              │
              │  LangGraph Agent Loop   │                │  talend_parser.py            │
              │    ├─ generate_sources  │                │    └─ Parse XML structure    │
              │    └─ generate_model    │                │  talend_to_dbt.py            │
              │       ├─ sqlfluff lint  │                │    ├─ Translate expressions  │
              │       └─ self-correct   │                │    ├─ Generate CTE SQL       │
              │                         │                │    └─ Generate schema YAML   │
              └────────┬────────────────┘                └──────────┬───────────────────┘
                       │                                            │
                       └──────────────┐  ┌──────────────────────────┘
                                      ▼  ▼
                              models/generated/
                              ├── *.sql          (dbt models)
                              ├── *_schema.yml   (tests)
                              └── *_sources.yml  (source defs)
                                      │
                                      ▼
                                 dbt compile ✓
```

## Project Structure

```
dbt-model-agent/
├── streamlit_app.py            # Streamlit UI — visual demo interface
├── agent.py                    # FastAPI server + LangGraph agent + tools
├── talend_parser.py            # Talend XML parser — extracts components and data flow
├── talend_to_dbt.py            # Deterministic Talend → dbt converter
├── test_api.py                 # Phase 1 test client (JSON schemas → agent)
├── test_talend_conversion.py   # Phase 2 test suite (Talend XML → dbt)
├── demo_schemas.json           # 3 JSON schemas for Phase 1 testing
├── talend_jobs/                # Sample Talend job exports
│   ├── filter_active_customers.item
│   ├── join_orders_customers.item
│   └── aggregate_payments.item
├── .streamlit/config.toml      # Dark theme config
├── models/
│   ├── generated/              # All agent/converter output lands here
│   │   ├── active_customers.sql
│   │   ├── order_details.sql
│   │   ├── payment_summary.sql
│   │   ├── stg_customers.sql
│   │   ├── stg_orders.sql
│   │   ├── stg_payments.sql
│   │   ├── *_schema.yml
│   │   └── jaffle_shop_sources.yml
│   ├── customers.sql           # Existing downstream model
│   └── orders.sql              # Existing downstream model
├── seeds/                      # Raw CSV data (loaded via dbt seed)
├── logs/                       # Rotating log files (auto-created)
├── .env.example                # Template for API keys
├── dbt_project.yml
└── pyproject.toml
```

## Quick Start

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install dbt-core dbt-duckdb sqlfluff fastapi uvicorn langchain langchain-openai langgraph python-dotenv pyyaml streamlit
```

### 2. Seed the Database

```bash
dbt seed
```

### 3. Launch the Streamlit UI (Recommended for Demos)

```bash
streamlit run streamlit_app.py
```

Open http://localhost:8501 → click any sample in the sidebar → see it convert instantly.

### 4. Run Phase 2 (Talend → dbt) — CLI

```bash
python3 test_talend_conversion.py
```

Expected output:
```
✓  filter_active_customers.item  → active_customers   (lint: pass)
✓  join_orders_customers.item    → order_details       (lint: pass)
✓  aggregate_payments.item       → payment_summary     (lint: pass)
✓  dbt compile: PASSED
🎉 All tests passed!
```

### 5. Run Phase 1 (AI Agent) — Requires OpenAI Key

```bash
cp .env.example .env
# Edit .env: OPENAI_API_KEY=sk-your-key-here

# Terminal 1: Start server
uvicorn agent:app

# Terminal 2: Run demo
python3 test_api.py
```

> **Note:** Do not use `uvicorn --reload` — the agent writes files to `models/`, which triggers the file watcher.

## API Endpoints

| Endpoint | Method | LLM Required | Description |
|---|---|---|---|
| `/generate_model` | POST | Yes | Generate a dbt model from a JSON schema (AI agent) |
| `/convert_talend` | POST | No | Convert a Talend `.item` file to a dbt model |
| `/validate_project` | POST | No | Run `dbt compile` on the full project |

### `POST /convert_talend` — Example

```bash
curl -X POST http://localhost:8000/convert_talend \
  -H "Content-Type: application/json" \
  -d '{"job_file": "talend_jobs/filter_active_customers.item"}'
```

### `POST /generate_model` — Example

```bash
curl -X POST http://localhost:8000/generate_model \
  -H "Content-Type: application/json" \
  -d '{
    "schema_def": {
      "table_name": "stg_customers",
      "source_name": "jaffle_shop",
      "source_table": "raw_customers",
      "columns": [
        {"name": "customer_id", "type": "int", "description": "Primary key"},
        {"name": "first_name", "type": "string", "description": "First name"}
      ],
      "transformations": "Select id as customer_id. Uppercase first_name."
    }
  }'
```

## Talend Component Support

| Talend Component | dbt Equivalent | Status |
|---|---|---|
| `tMysqlInput` / `tDBInput` | `{{ source('name', 'table') }}` | ✅ Supported |
| `tMap` (column mapping) | `SELECT col AS alias` | ✅ Supported |
| `tMap` (join) | `LEFT JOIN` / `INNER JOIN` | ✅ Supported |
| `tMap` (expressions) | `UPPER()`, `||`, math | ✅ Supported |
| `tFilterRow` | `WHERE` clause | ✅ Supported |
| `tAggregateRow` | `GROUP BY` + `SUM/COUNT/MIN/MAX/AVG` | ✅ Supported |
| `tMysqlOutput` / `tDBOutput` | Materialized dbt model | ✅ Supported |
| `tNormalize` / `tDenormalize` | `UNPIVOT` / `PIVOT` | ❌ Not yet |
| `tUnite` | `UNION ALL` | ❌ Not yet |
| `tSortRow` | `ORDER BY` | ❌ Not yet |

## Expression Translation

| Talend (Java) | SQL Output |
|---|---|
| `row1.column_name` | `alias.column_name` |
| `row1.amount / 100.0` | `alias.amount / 100.0` |
| `StringHandling.UPCASE(row1.col)` | `UPPER(alias.col)` |
| `StringHandling.DOWNCASE(row1.col)` | `LOWER(alias.col)` |
| `StringHandling.TRIM(row1.col)` | `TRIM(alias.col)` |
| `row1.first + " " + row1.last` | `alias.first \|\| ' ' \|\| alias.last` |

## Logging

| Log File | Source | Contains |
|---|---|---|
| `logs/agent.log` | Server (`agent.py`) | Agent reasoning, tool calls, validation results |
| `logs/test_api.log` | Client (`test_api.py`) | HTTP request/response status, timing |

Both log files rotate at 5 MB with 3 backups and mirror to console.

## Switching LLM Providers

The Phase 1 agent uses OpenAI `gpt-4o-mini`. To switch:

```python
# Google Gemini (free tier available)
from langchain_google_genai import ChatGoogleGenerativeAI
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

# Anthropic Claude
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
```

## Tech Stack

- **Agent Framework:** LangGraph + LangChain
- **LLM:** OpenAI gpt-4o-mini (configurable, Phase 1 only)
- **API Framework:** FastAPI + Uvicorn
- **UI:** Streamlit
- **Data Warehouse:** DuckDB
- **dbt:** dbt-core + dbt-duckdb
- **SQL Linting:** sqlfluff
- **Built on:** [jaffle_shop_duckdb](https://github.com/dbt-labs/jaffle_shop_duckdb) by dbt Labs (Apache 2.0)
