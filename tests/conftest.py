"""
Shared test fixtures and configuration for the dbt-model-agent test suite.
"""

import os
import pytest
from dataclasses import asdict

from src import PROJECT_ROOT, TALEND_JOBS_DIR
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _load_and_convert(filename: str) -> dict:
    """Parse a Talend job and run the deterministic converter."""
    filepath = os.path.join(TALEND_JOBS_DIR, filename)
    parsed = parse_talend_job(filepath)
    parsed_dict = asdict(parsed)
    converter = TalendToDbtConverter(parsed_dict)
    result = converter.convert()
    return {
        "parsed": parsed_dict,
        "result": result,
    }


@pytest.fixture
def filter_job():
    """Simple filter: source → tFilterRow → target."""
    return _load_and_convert("filter_active_customers.item")


@pytest.fixture
def join_job():
    """Medium join: 2 sources → tMap LEFT JOIN → target."""
    return _load_and_convert("join_orders_customers.item")


@pytest.fixture
def aggregate_job():
    """Complex aggregation: source → tMap → tAggregateRow → target."""
    return _load_and_convert("aggregate_payments.item")


@pytest.fixture
def multi_filter_job():
    """Multiple WHERE conditions: status = completed AND amount > 1000."""
    return _load_and_convert("04_multi_filter.item")


@pytest.fixture
def join_with_filter_job():
    """JOIN + WHERE combined: join orders+customers then filter completed."""
    return _load_and_convert("05_join_with_filter.item")


@pytest.fixture
def full_pipeline_job():
    """Full pipeline: 2 sources → INNER JOIN → transform → aggregate."""
    return _load_and_convert("06_full_pipeline.item")
