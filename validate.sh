#!/bin/bash
set -e

echo "=== Running Unit Tests ==="
venv/bin/python -m pytest tests/ -v

echo ""
echo "=== Generating Models deterministically ==="
# Clean up previously generated models to prevent stale files from polluting validation
rm -rf models/generated/*
venv/bin/python -c "
from dataclasses import asdict
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter, write_dbt_files
import os, glob
for f in sorted(glob.glob('fixtures/talend_jobs/*.item')):
    parsed = asdict(parse_talend_job(f))
    result = TalendToDbtConverter(parsed).convert(source_schema='main')
    write_dbt_files(result)
    print(f'  ✓ {os.path.basename(f):40s} → {result.model_name}.sql')
"

echo ""
echo "=== Linting generated SQL ==="
venv/bin/sqlfluff lint models/generated/

echo ""
echo "=== Compiling dbt models ==="
venv/bin/dbt compile --profiles-dir .

echo ""
echo "=== Running models against DuckDB ==="
venv/bin/dbt run --profiles-dir .

echo ""
echo "=== Running data quality tests ==="
venv/bin/dbt test --profiles-dir .

echo ""
echo "=== Validation finished ==="
