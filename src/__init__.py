"""
dbt Model Agent — Source Package

Centralized path configuration. Every module in this package imports
paths from here instead of computing them via __file__.
"""

import os
import shutil

# Project root is one level up from src/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# dbt project paths
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
GENERATED_MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "generated")
SEEDS_DIR = os.path.join(PROJECT_ROOT, "seeds")

# Test fixtures
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "fixtures")
TALEND_JOBS_DIR = os.path.join(PROJECT_ROOT, "fixtures", "talend_jobs")

# Logs
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

# Virtual environment binaries
# Attempt to find binaries in the local venv first, then fallback to system PATH
_local_sqlfluff = os.path.join(PROJECT_ROOT, "venv", "bin", "sqlfluff")
SQLFLUFF_BIN = _local_sqlfluff if os.path.exists(_local_sqlfluff) else (shutil.which("sqlfluff") or "sqlfluff")

_local_dbt = os.path.join(PROJECT_ROOT, "venv", "bin", "dbt")
DBT_BIN = _local_dbt if os.path.exists(_local_dbt) else (shutil.which("dbt") or "dbt")
