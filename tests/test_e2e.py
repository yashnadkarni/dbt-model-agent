"""
End-to-end integration tests — writes files to disk and validates with sqlfluff.
"""

import os
import tempfile
import pytest
from dataclasses import asdict

from src import TALEND_JOBS_DIR
from src.parser import parse_talend_job
from src.converter import TalendToDbtConverter, write_dbt_files, validate_sql


ALL_JOBS = [
    "filter_active_customers.item",
    "join_orders_customers.item",
    "aggregate_payments.item",
    "04_multi_filter.item",
    "05_join_with_filter.item",
    "06_full_pipeline.item",
    "07_compute_revenue_delta.item",
]


@pytest.mark.parametrize("job_file", ALL_JOBS)
class TestEndToEnd:
    """Run the full pipeline for each job: parse → convert → write → lint."""

    def test_parse_succeeds(self, job_file):
        filepath = os.path.join(TALEND_JOBS_DIR, job_file)
        job = parse_talend_job(filepath)
        assert len(job.sources) >= 1
        assert len(job.targets) >= 1

    def test_convert_produces_sql(self, job_file):
        filepath = os.path.join(TALEND_JOBS_DIR, job_file)
        parsed = asdict(parse_talend_job(filepath))
        converter = TalendToDbtConverter(parsed)
        result = converter.convert()

        assert result.model_name
        assert result.sql_content
        assert "{{ config(materialized='table') }}" in result.sql_content
        assert result.schema_yaml
        assert result.source_yaml

    def test_write_and_lint(self, job_file, tmp_path):
        filepath = os.path.join(TALEND_JOBS_DIR, job_file)
        parsed = asdict(parse_talend_job(filepath))
        converter = TalendToDbtConverter(parsed)
        result = converter.convert()

        # Write to temp directory
        paths = write_dbt_files(result, output_dir=str(tmp_path))

        # Verify files exist
        assert os.path.isfile(paths["sql_path"])
        assert os.path.isfile(paths["schema_path"])
        assert os.path.isfile(paths["source_path"])

        # Verify SQL ends with single newline (LT12)
        with open(paths["sql_path"]) as f:
            content = f.read()
        assert content.endswith("\n")
        assert not content.endswith("\n\n")

        # Run sqlfluff lint
        lint = validate_sql(paths["sql_path"])
        assert lint["passed"], f"sqlfluff lint failed for {job_file}: {lint['output']}"
