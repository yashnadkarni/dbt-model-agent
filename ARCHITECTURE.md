# Architecture & Development Guide

## Project Overview

An AI-powered agent and deterministic converter that generates production-ready dbt models from **Talend ETL job exports** (`.item` XML) or **JSON schemas**. Built with LangGraph, FastAPI, DuckDB, and Streamlit.

## Quick Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Seed DuckDB with sample data
venv/bin/dbt seed --profiles-dir .

# Run the Streamlit UI (main entrypoint for demos)
venv/bin/streamlit run src/ui.py

# Run the FastAPI server (for API-based access)
venv/bin/uvicorn src.agent:app

# Run tests
venv/bin/python -m pytest tests/ -v

# Lint generated models
venv/bin/sqlfluff lint models/generated/

# dbt compile (validate all models)
venv/bin/dbt compile --profiles-dir .

# dbt run (execute all models against DuckDB)
venv/bin/dbt run --profiles-dir .

# dbt test (run data quality tests)
venv/bin/dbt test --profiles-dir .
```

## Architecture

```
src/
├── __init__.py       # Centralized path config (PROJECT_ROOT, GENERATED_MODELS_DIR, etc.)
├── parser.py         # Talend XML parser → structured TalendJob dataclass
├── converter.py      # Deterministic TalendJob → dbt SQL/YAML converter
├── agent.py          # FastAPI server + LangGraph ReAct agent + tool definitions
└── ui.py             # Streamlit UI (calls parser+converter directly, agent.py for LLM mode)
```

### Data Flow

**Deterministic mode** (no LLM):
```
Talend XML → parser.parse_talend_job() → TalendJob dataclass
           → converter.TalendToDbtConverter.convert() → ConversionResult
           → .sql + .yml files
```

**LLM mode** (requires OPENAI_API_KEY):
```
Talend XML → parser (same) → parsed_dict → ui.convert_with_llm()
           → agent.run_generation_agent() → LangGraph ReAct agent
           → tools: generate_dbt_sources(), generate_dbt_model()
           → writes files to models/generated/ + sqlfluff validation
```

**FastAPI endpoints**:
- `POST /generate_model` — JSON schema → LLM agent → dbt model (Phase 1)
- `POST /convert_talend` — Talend .item file path → deterministic converter (Phase 2)
- `POST /validate_project` — Runs `dbt compile` on the full project

## Key Design Decisions

1. **Dual modes**: The app supports deterministic (pattern-matched) and LLM-based conversion. The deterministic mode is the primary path; LLM mode is an optional enhancement shown side-by-side.

2. **Agent tools write to disk**: `generate_dbt_model()` and `generate_dbt_sources()` are LangGraph tools that write files to `models/generated/` and run `sqlfluff lint`. The agent self-corrects on lint failures.

3. **CTE-based SQL**: All generated SQL uses CTEs (`WITH ... AS`) referencing `{{ source() }}` macros — a dbt best practice.

4. **Source merging**: Both the agent tools and `write_dbt_files()` merge new source table definitions into existing `*_sources.yml` files to avoid overwrites.

## Module Details

### `parser.py`
- Parses Talend `.item` XML (XMI format) into structured `TalendJob` dataclass
- Supports: `tMysqlInput`, `tMysqlOutput`, `tMap`, `tFilterRow`, `tAggregateRow` (+ variants)
- Extracts: sources, targets, transformations (filters, joins, mappings, aggregations), connections
- CLI: `python -m src.parser [file.item]`

### `converter.py`
- Translates `TalendJob` dict → dbt SQL + schema YAML + source YAML
- Expression translation: Java (row1.col, StringHandling.UPCASE) → SQL (alias.col, UPPER)
- Filter operators: `==` → `=`, `contains` → `LIKE`, etc.
- Aggregate functions: sum→SUM, count→COUNT, etc.
- Handles: simple filter, join, join+filter, aggregate, join+aggregate pipelines
- Utilities: `write_dbt_files()`, `validate_sql()`, `derive_alias()`

### `agent.py`
- FastAPI app with 3 endpoints
- LangGraph ReAct agent using `gpt-4o-mini` with tools:
  - `generate_dbt_sources(source_name, yaml_content)` — writes source YAML
  - `generate_dbt_model(table_name, sql_content, yaml_content)` — writes SQL+schema, runs sqlfluff
- `run_generation_agent()` — reusable function for both FastAPI and Streamlit
- Logging: rotating file handler → `logs/agent.log`

### `ui.py`
- Streamlit app with paste/upload/sample-click input
- Deterministic conversion via direct `parser` + `converter` calls
- LLM mode toggle calls `agent.run_generation_agent()` for side-by-side comparison
- Zip download of generated files
- Custom CSS with dark theme, gradient headers, metric cards

## Environment Variables

```
OPENAI_API_KEY=sk-...    # Required only for LLM mode / Phase 1 agent
```

## File Output Location

All generated models go to: `models/generated/`
```
models/generated/
├── {model_name}.sql
├── {model_name}_schema.yml
└── {source_name}_sources.yml
```

## Testing

```bash
# Run all tests
venv/bin/python -m pytest tests/ -v

# Test structure:
# tests/conftest.py      — Shared fixtures loading all 6 sample Talend jobs
# tests/test_parser.py   — Parser extraction correctness
# tests/test_converter.py — SQL generation patterns (WHERE, JOIN, GROUP BY, etc.)
# tests/test_e2e.py       — Full pipeline: parse → convert → write → sqlfluff lint
```

## Coding Conventions

- All paths imported from `src/__init__.py` (never computed via `__file__` in modules)
- `venv/bin/` prefix for all tool binaries (sqlfluff, dbt) — see `__init__.py`
- Dataclasses for structured data (TalendJob, ConversionResult, etc.)
- PyYAML for all YAML generation (not string formatting)
- Logging via `logging.getLogger("agent")` or `logging.getLogger("agent.converter")`

## Common Gotchas

- `uvicorn --reload` causes infinite loops (agent writes to `models/` which triggers watcher)
- dbt enforces globally unique model names — `_remove_conflicting_models()` handles this
- sqlfluff rule CV06 (semicolon terminator) is excluded in `.sqlfluff` — dbt models must NOT end with semicolons
- sqlfluff rule LT12 requires single trailing newline — normalized in `generate_dbt_model()` tool
- sqlfluff rule ST09 requires FROM-table column on LEFT side of JOIN ON condition
- sqlfluff rule RF02 requires qualified column names when multiple tables are in scope
- DuckDB seeds land in the `main` schema — `converter.convert(source_schema='main')` adds `schema: main` to source YAML
- All dbt commands need `--profiles-dir .` since `profiles.yml` is in the project root
