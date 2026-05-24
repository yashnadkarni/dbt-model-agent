"""
Parser unit tests — verifies that talend_parser correctly extracts
sources, transformations, targets, and connections from XML.
"""

import os
import pytest
from dataclasses import asdict

from src import TALEND_JOBS_DIR
from src.parser import parse_talend_job


class TestParserExtraction:
    """Verify the parser extracts correct component counts and properties."""

    def test_filter_job_structure(self, filter_job):
        p = filter_job["parsed"]
        assert len(p["sources"]) == 1
        assert len(p["transformations"]) == 1
        assert len(p["targets"]) == 1
        assert p["transformations"][0]["component_type"] == "tFilterRow"

    def test_join_job_structure(self, join_job):
        p = join_job["parsed"]
        assert len(p["sources"]) == 2
        assert len(p["transformations"]) == 1
        assert p["transformations"][0]["component_type"] == "tMap"
        assert len(p["transformations"][0]["joins"]) >= 1

    def test_aggregate_job_structure(self, aggregate_job):
        p = aggregate_job["parsed"]
        assert len(p["sources"]) == 1
        # Should have tMap + tAggregateRow = 2 transformations
        assert len(p["transformations"]) == 2
        types = {t["component_type"] for t in p["transformations"]}
        assert "tMap" in types
        assert "tAggregateRow" in types

    def test_source_table_names(self, filter_job, join_job):
        assert filter_job["parsed"]["sources"][0]["table_name"] == "raw_customers"
        tables = {s["table_name"] for s in join_job["parsed"]["sources"]}
        assert "raw_orders" in tables
        assert "raw_customers" in tables

    def test_filter_conditions_parsed(self, filter_job):
        filt = filter_job["parsed"]["transformations"][0]
        assert len(filt["filters"]) >= 1
        cond = filt["filters"][0]
        assert cond["input_column"] == "status"
        assert cond["operator"] == "=="
        assert cond["value"] == "active"

    def test_connections_exist(self, filter_job):
        conns = filter_job["parsed"]["connections"]
        assert len(conns) >= 2
        labels = {c["label"] for c in conns}
        assert "row1" in labels

    def test_multi_filter_has_two_conditions(self, multi_filter_job):
        p = multi_filter_job["parsed"]
        filt = p["transformations"][0]
        assert filt["component_type"] == "tFilterRow"
        assert len(filt["filters"]) == 2

    def test_full_pipeline_has_join_and_aggregate(self, full_pipeline_job):
        p = full_pipeline_job["parsed"]
        assert len(p["sources"]) == 2
        types = {t["component_type"] for t in p["transformations"]}
        assert "tMap" in types
        assert "tAggregateRow" in types
