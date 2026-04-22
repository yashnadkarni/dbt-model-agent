# dbt-model-agent

An AI-powered agent that generates production-ready [dbt](https://www.getdbt.com/) model files from JSON schema definitions. Built with **LangGraph**, **FastAPI**, and **DuckDB**.

## What It Does

Give the agent a JSON schema describing a table (columns, types, transformations) and it will:

1. **Generate a dbt source definition** (`.yml`) declaring raw table dependencies
2. **Write a dbt SQL model** (`.sql`) with proper Jinja macros and functional transformations
3. **Create a schema test file** (`.yml`) with `not_null`, `unique`, and `accepted_values` tests
4. **Validate the output** using `sqlfluff lint` and `dbt compile`
5. **Self-correct** — if validation fails, the agent reads the error and fixes its code automatically

## Architecture

```
┌─────────────┐     POST /generate_model      ┌───────────────┐
│ test_api.py │ ──────────────────────────▶   │   FastAPI     │
│  (client)   │                               │   (agent.py)  │
└─────────────┘     ◀──────────────────────── │               │
                         JSON response        │  LangGraph    │
                                              │  Agent Loop   │
                                              │    │    │     │
                                              │    ▼    ▼     │
                                              │ Tool1  Tool2  │
                                              └──┬───────┬────┘
                                                 │       │
                                    ┌────────────┘       └────────────┐
                                    ▼                                  ▼
                          generate_dbt_sources()            generate_dbt_model()
                          → writes sources .yml             → writes .sql + schema .yml
                          → merges tables                   → runs sqlfluff lint
                                                            → removes name conflicts
```

## Project Structure

```
dbt-model-agent/
├── agent.py               # FastAPI server + LangGraph agent + tools
├── test_api.py            # Demo client — fires requests from demo_schemas.json
├── demo_schemas.json      # 3 real-world schema definitions (customers, orders, payments)
├── .env                   # API keys (not committed)
├── .env.example           # Template for .env
├── models/
│   ├── generated/         # AI-generated models land here
│   │   ├── stg_customers.sql
│   │   ├── stg_customers_schema.yml
│   │   ├── stg_orders.sql
│   │   ├── stg_orders_schema.yml
│   │   ├── stg_payments.sql
│   │   ├── stg_payments_schema.yml
│   │   └── jaffle_shop_sources.yml
│   ├── customers.sql      # Existing downstream model
│   ├── orders.sql         # Existing downstream model
│   └── schema.yml         # Existing schema
├── seeds/                 # Raw CSV data (loaded via dbt seed)
│   ├── raw_customers.csv
│   ├── raw_orders.csv
│   └── raw_payments.csv
├── logs/                  # Log files (auto-created)
│   ├── agent.log          # Server-side logs
│   └── test_api.log       # Client-side logs
└── pyproject.toml
```

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 2. Set Up API Keys

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key:
# OPENAI_API_KEY=sk-your-key-here
```

### 3. Seed the Database

```bash
dbt seed
```

### 4. Start the Server

```bash
uvicorn agent:app
```

> **Note:** Do not use `--reload` — the agent writes files to `models/`, which triggers uvicorn's file watcher and kills active requests.

### 5. Run the Demo

In a second terminal:

```bash
source venv/bin/activate
python test_api.py
```

This sends 3 real-world schemas (customers, orders, payments) to the API and validates the full project with `dbt compile` at the end.

## API Endpoints

### `POST /generate_model`

Generate a dbt model from a JSON schema.

**Request body:**
```json
{
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
}
```

### `POST /validate_project`

Runs `dbt compile` on the full project and returns pass/fail status.

## Logging

The project uses Python's `logging` module with `RotatingFileHandler`:

| Log File | Source | Contains |
|---|---|---|
| `logs/agent.log` | Server (`agent.py`) | Agent reasoning, tool calls, validation results, errors |
| `logs/test_api.log` | Client (`test_api.py`) | Request/response status, timing, validation summary |

Both log files are also mirrored to the console. Log files rotate at 5 MB with 3 backups.

## Switching LLM Providers

The agent currently uses OpenAI (`gpt-4o-mini`). To switch providers, modify the `llm` initialization in `agent.py`:

```python
# OpenAI (current)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Google Gemini (cheapest — free tier available)
from langchain_google_genai import ChatGoogleGenerativeAI
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

# Anthropic Claude
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
```

## Tech Stack

- **Agent Framework:** LangGraph + LangChain
- **LLM:** OpenAI gpt-4o-mini (configurable)
- **API Framework:** FastAPI + Uvicorn
- **Data Warehouse:** DuckDB
- **dbt:** dbt-core + dbt-duckdb adapter
- **SQL Linting:** sqlfluff
- **Build:** on top of [jaffle_shop_duckdb](https://github.com/dbt-labs/jaffle_shop_duckdb) by dbt Labs (Apache 2.0).

