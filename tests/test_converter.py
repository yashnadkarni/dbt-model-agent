"""
Converter tests — 6 test cases of increasing complexity.

Each test validates:
  - SQL contains expected patterns (source refs, JOINs, WHERE, GROUP BY)
  - Model name matches expected target table
  - Schema YAML is well-formed
  - Source YAML declares correct tables
"""

import pytest
import yaml


class TestSimpleFilter:
    """Test 1: source → tFilterRow → target (WHERE clause)."""

    def test_model_name(self, filter_job):
        assert filter_job["result"].model_name == "active_customers"

    def test_sql_has_source_ref(self, filter_job):
        sql = filter_job["result"].sql_content
        assert "source('jaffle_shop', 'raw_customers')" in sql

    def test_sql_has_where_clause(self, filter_job):
        sql = filter_job["result"].sql_content
        assert "WHERE" in sql
        assert "status = 'active'" in sql

    def test_sql_has_no_join(self, filter_job):
        sql = filter_job["result"].sql_content
        assert "JOIN" not in sql

    def test_schema_yaml_valid(self, filter_job):
        schema = yaml.safe_load(filter_job["result"].schema_yaml)
        assert "models" in schema
        assert schema["models"][0]["name"] == "active_customers"


class TestJoinTwoTables:
    """Test 2: 2 sources → tMap LEFT JOIN → target."""

    def test_model_name(self, join_job):
        assert join_job["result"].model_name == "order_details"

    def test_sql_has_both_sources(self, join_job):
        sql = join_job["result"].sql_content
        assert "source('jaffle_shop', 'raw_orders')" in sql
        assert "source('jaffle_shop', 'raw_customers')" in sql

    def test_sql_has_left_join(self, join_job):
        sql = join_job["result"].sql_content
        assert "LEFT JOIN" in sql
        assert "customers" in sql

    def test_sql_has_ctes(self, join_job):
        sql = join_job["result"].sql_content
        assert "WITH" in sql
        assert "orders AS" in sql
        assert "customers AS" in sql

    def test_sql_has_concat_expression(self, join_job):
        sql = join_job["result"].sql_content
        assert "||" in sql  # string concatenation


class TestAggregation:
    """Test 3: source → tMap → tAggregateRow → target (GROUP BY)."""

    def test_model_name(self, aggregate_job):
        assert aggregate_job["result"].model_name == "payment_summary"

    def test_sql_has_group_by(self, aggregate_job):
        sql = aggregate_job["result"].sql_content
        assert "GROUP BY" in sql
        assert "payment_method" in sql

    def test_sql_has_aggregate_functions(self, aggregate_job):
        sql = aggregate_job["result"].sql_content
        assert "SUM(" in sql
        assert "COUNT(" in sql

    def test_sql_has_transformed_cte(self, aggregate_job):
        sql = aggregate_job["result"].sql_content
        assert "transformed AS" in sql

    def test_sql_has_upper_function(self, aggregate_job):
        sql = aggregate_job["result"].sql_content
        assert "UPPER(" in sql


class TestMultiFilter:
    """Test 4: Multiple WHERE conditions (AND)."""

    def test_model_name(self, multi_filter_job):
        assert multi_filter_job["result"].model_name == "high_value_orders"

    def test_sql_has_multiple_conditions(self, multi_filter_job):
        sql = multi_filter_job["result"].sql_content
        assert "WHERE" in sql
        assert "status = 'completed'" in sql
        assert "amount > 1000" in sql

    def test_sql_has_and_operator(self, multi_filter_job):
        sql = multi_filter_job["result"].sql_content
        assert "AND" in sql

    def test_source_tables(self, multi_filter_job):
        assert multi_filter_job["result"].source_tables == ["raw_orders"]


class TestJoinWithFilter:
    """Test 5: JOIN + WHERE combined."""

    def test_model_name(self, join_with_filter_job):
        assert join_with_filter_job["result"].model_name == "completed_order_details"

    def test_sql_has_join_and_where(self, join_with_filter_job):
        sql = join_with_filter_job["result"].sql_content
        assert "JOIN" in sql
        assert "WHERE" in sql

    def test_sql_has_both_sources(self, join_with_filter_job):
        sql = join_with_filter_job["result"].sql_content
        assert "raw_orders" in sql
        assert "raw_customers" in sql

    def test_source_tables(self, join_with_filter_job):
        tables = set(join_with_filter_job["result"].source_tables)
        assert "raw_orders" in tables
        assert "raw_customers" in tables


class TestFullPipeline:
    """Test 6: 2 sources → INNER JOIN → transform → aggregate (most complex)."""

    def test_model_name(self, full_pipeline_job):
        assert full_pipeline_job["result"].model_name == "order_payment_summary"

    def test_sql_has_inner_join(self, full_pipeline_job):
        sql = full_pipeline_job["result"].sql_content
        assert "INNER JOIN" in sql

    def test_sql_has_group_by(self, full_pipeline_job):
        sql = full_pipeline_job["result"].sql_content
        assert "GROUP BY" in sql

    def test_sql_has_aggregate_functions(self, full_pipeline_job):
        sql = full_pipeline_job["result"].sql_content
        assert "SUM(" in sql
        assert "COUNT(" in sql

    def test_sql_has_both_sources(self, full_pipeline_job):
        sql = full_pipeline_job["result"].sql_content
        assert "raw_orders" in sql
        assert "raw_payments" in sql

    def test_sql_has_upper_function(self, full_pipeline_job):
        sql = full_pipeline_job["result"].sql_content
        assert "UPPER(" in sql

    def test_schema_has_key_tests(self, full_pipeline_job):
        schema = yaml.safe_load(full_pipeline_job["result"].schema_yaml)
        model = schema["models"][0]
        key_cols = [c for c in model["columns"] if "tests" in c and "unique" in c["tests"]]
        assert len(key_cols) >= 1, "Primary key column should have unique test"
