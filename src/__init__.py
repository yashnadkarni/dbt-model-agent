"""
dbt Model Agent — Source Package

Centralized path configuration. Every module in this package imports
paths from here instead of computing them via __file__.
"""

import os

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
VENV_BIN = os.path.join(PROJECT_ROOT, "venv", "bin")
SQLFLUFF_BIN = os.path.join(VENV_BIN, "sqlfluff")
DBT_BIN = os.path.join(VENV_BIN, "dbt")
