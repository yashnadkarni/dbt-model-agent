"""
Tests for the connection manager module (src/connections.py).

Covers:
  - ConnectionConfig creation, validation, and from_env
  - ConnectionManager profile generation (DuckDB + Snowflake + Databricks)
  - ConnectionManager DuckDB connection test
  - Snowflake / Databricks connection test (mocked — no real credentials needed)
  - Dialect-specific function overrides
  - Converter integration with dialect parameter
"""

import os
import pytest
import yaml
from unittest.mock import patch, MagicMock
from dataclasses import asdict

from src.connections import (
    ConnectionConfig,
    ConnectionManager,
    SUPPORTED_ADAPTERS,
    SQLFLUFF_DIALECT_MAP,
    DIALECT_FUNCTION_OVERRIDES,
    get_default_config,
)
from src.converter import (
    TalendToDbtConverter,
    get_function_map,
    translate_expression,
    validate_sql,
)


# ---------------------------------------------------------------------------
# ConnectionConfig Tests
# ---------------------------------------------------------------------------

class TestConnectionConfig:
    """Test ConnectionConfig creation, validation, and properties."""

    def test_default_is_duckdb(self):
        config = ConnectionConfig()
        assert config.adapter == "duckdb"

    def test_duckdb_config_no_missing_fields(self):
        config = ConnectionConfig(adapter="duckdb")
        assert config.validate() == []

    def test_snowflake_config_missing_fields(self):
        config = ConnectionConfig(adapter="snowflake")
        missing = config.validate()
        assert "account" in missing
        assert "user" in missing
        assert "password" in missing
        assert "warehouse" in missing
        assert "database" in missing
        assert "schema" in missing

    def test_snowflake_config_all_fields_set(self):
        config = ConnectionConfig(
            adapter="snowflake",
            account="test.us-east-1",
            user="testuser",
            password="testpass",
            warehouse="WH",
            database="DB",
            schema="SCH",
        )
        assert config.validate() == []

    def test_databricks_config_missing_fields(self):
        config = ConnectionConfig(adapter="databricks")
        missing = config.validate()
        assert "host" in missing
        assert "token" in missing
        assert "http_path" in missing
        assert "schema" in missing

    def test_databricks_config_all_fields_set(self):
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            schema="default",
        )
        assert config.validate() == []

    def test_databricks_config_catalog_optional(self):
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            schema="default",
            catalog="",  # optional
        )
        assert config.validate() == []

    def test_unsupported_adapter_raises(self):
        with pytest.raises(ValueError, match="Unsupported adapter"):
            ConnectionConfig(adapter="postgres")

    def test_source_schema_duckdb(self):
        config = ConnectionConfig(adapter="duckdb")
        assert config.source_schema == "main"

    def test_source_schema_snowflake(self):
        config = ConnectionConfig(adapter="snowflake", schema="MY_SCHEMA")
        assert config.source_schema == "MY_SCHEMA"

    def test_source_schema_databricks(self):
        config = ConnectionConfig(adapter="databricks", schema="my_schema")
        assert config.source_schema == "my_schema"

    def test_sqlfluff_dialect_duckdb(self):
        config = ConnectionConfig(adapter="duckdb")
        assert config.sqlfluff_dialect == "duckdb"

    def test_sqlfluff_dialect_snowflake(self):
        config = ConnectionConfig(adapter="snowflake")
        assert config.sqlfluff_dialect == "snowflake"

    def test_sqlfluff_dialect_databricks(self):
        config = ConnectionConfig(adapter="databricks")
        assert config.sqlfluff_dialect == "sparksql"

    def test_function_overrides_duckdb_empty(self):
        config = ConnectionConfig(adapter="duckdb")
        assert config.function_overrides == {}

    def test_function_overrides_snowflake_has_to_char(self):
        config = ConnectionConfig(adapter="snowflake")
        overrides = config.function_overrides
        assert overrides.get("TalendDate.formatDate") == "TO_CHAR"

    def test_function_overrides_databricks_has_date_format(self):
        config = ConnectionConfig(adapter="databricks")
        overrides = config.function_overrides
        assert overrides.get("TalendDate.formatDate") == "DATE_FORMAT"

    def test_from_env_duckdb(self):
        config = ConnectionConfig.from_env("duckdb")
        assert config.adapter == "duckdb"

    def test_from_env_snowflake(self):
        env_vars = {
            "SNOWFLAKE_ACCOUNT": "test.us-east-1",
            "SNOWFLAKE_USER": "testuser",
            "SNOWFLAKE_PASSWORD": "testpass",
            "SNOWFLAKE_ROLE": "ROLE",
            "SNOWFLAKE_WAREHOUSE": "WH",
            "SNOWFLAKE_DATABASE": "DB",
            "SNOWFLAKE_SCHEMA": "SCH",
        }
        with patch.dict(os.environ, env_vars):
            config = ConnectionConfig.from_env("snowflake")
        assert config.adapter == "snowflake"
        assert config.account == "test.us-east-1"
        assert config.user == "testuser"
        assert config.warehouse == "WH"

    def test_from_env_databricks(self):
        env_vars = {
            "DATABRICKS_HOST": "dbc-test.cloud.databricks.com",
            "DATABRICKS_TOKEN": "dapi-testtoken",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_CATALOG": "main",
            "DATABRICKS_SCHEMA": "default",
        }
        with patch.dict(os.environ, env_vars):
            config = ConnectionConfig.from_env("databricks")
        assert config.adapter == "databricks"
        assert config.host == "dbc-test.cloud.databricks.com"
        assert config.token == "dapi-testtoken"
        assert config.http_path == "/sql/1.0/warehouses/abc123"
        assert config.catalog == "main"

    def test_from_env_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported adapter"):
            ConnectionConfig.from_env("mysql")


# ---------------------------------------------------------------------------
# ConnectionManager Profile Generation Tests
# ---------------------------------------------------------------------------

class TestConnectionManagerProfiles:
    """Test dynamic profiles.yml generation."""

    def test_duckdb_profile_structure(self):
        config = ConnectionConfig(adapter="duckdb")
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()

        assert "jaffle_shop" in profiles
        output = profiles["jaffle_shop"]["outputs"]["dev"]
        assert output["type"] == "duckdb"
        assert output["path"] == "jaffle_shop.duckdb"
        assert output["threads"] == 4

    def test_snowflake_profile_structure(self):
        config = ConnectionConfig(
            adapter="snowflake",
            account="test.us-east-1",
            user="user",
            password="pass",
            role="ROLE",
            warehouse="WH",
            database="DB",
            schema="SCH",
        )
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()

        output = profiles["jaffle_shop"]["outputs"]["dev"]
        assert output["type"] == "snowflake"
        assert output["account"] == "test.us-east-1"
        assert output["user"] == "user"
        assert output["password"] == "pass"
        assert output["role"] == "ROLE"
        assert output["warehouse"] == "WH"
        assert output["database"] == "DB"
        assert output["schema"] == "SCH"

    def test_snowflake_profile_without_role(self):
        config = ConnectionConfig(
            adapter="snowflake",
            account="test.us-east-1",
            user="user",
            password="pass",
            warehouse="WH",
            database="DB",
            schema="SCH",
            role="",  # no role
        )
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()
        output = profiles["jaffle_shop"]["outputs"]["dev"]
        assert "role" not in output

    def test_databricks_profile_structure(self):
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            catalog="main",
            schema="default",
        )
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()

        output = profiles["jaffle_shop"]["outputs"]["dev"]
        assert output["type"] == "databricks"
        assert output["host"] == "dbc-test.cloud.databricks.com"
        assert output["token"] == "dapi-testtoken"
        assert output["http_path"] == "/sql/1.0/warehouses/abc123"
        assert output["catalog"] == "main"
        assert output["schema"] == "default"

    def test_databricks_profile_without_catalog(self):
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            schema="default",
            catalog="",  # no catalog
        )
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()
        output = profiles["jaffle_shop"]["outputs"]["dev"]
        assert "catalog" not in output

    def test_write_profiles_yml(self, tmp_path):
        config = ConnectionConfig(adapter="duckdb")
        mgr = ConnectionManager(config)
        path = mgr.write_profiles_yml(output_dir=str(tmp_path))

        assert os.path.isfile(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["jaffle_shop"]["outputs"]["dev"]["type"] == "duckdb"

    def test_write_snowflake_profiles_yml(self, tmp_path):
        config = ConnectionConfig(
            adapter="snowflake",
            account="test.us-east-1",
            user="user",
            password="pass",
            warehouse="WH",
            database="DB",
            schema="SCH",
        )
        mgr = ConnectionManager(config)
        path = mgr.write_profiles_yml(output_dir=str(tmp_path))

        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["jaffle_shop"]["outputs"]["dev"]["type"] == "snowflake"

    def test_write_databricks_profiles_yml(self, tmp_path):
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            schema="default",
        )
        mgr = ConnectionManager(config)
        path = mgr.write_profiles_yml(output_dir=str(tmp_path))

        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["jaffle_shop"]["outputs"]["dev"]["type"] == "databricks"

    def test_custom_profile_name(self, tmp_path):
        config = ConnectionConfig(adapter="duckdb", profile_name="my_project")
        mgr = ConnectionManager(config)
        profiles = mgr.generate_profiles_dict()
        assert "my_project" in profiles


# ---------------------------------------------------------------------------
# ConnectionManager Connection Tests
# ---------------------------------------------------------------------------

class TestConnectionManagerConnect:
    """Test connection testing (DuckDB real, Snowflake mocked)."""

    def test_duckdb_connection_success(self):
        """Test DuckDB connection with the real jaffle_shop.duckdb file."""
        config = ConnectionConfig(adapter="duckdb")
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is True
        assert "tables" in result["details"]

    def test_duckdb_connection_bad_path(self):
        config = ConnectionConfig(adapter="duckdb", duckdb_path="/nonexistent/db.duckdb")
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        # DuckDB creates a new file if it doesn't exist, so this might succeed
        # but with 0 tables. Either way it shouldn't crash.
        assert isinstance(result["success"], bool)

    def test_snowflake_connection_missing_fields(self):
        config = ConnectionConfig(adapter="snowflake")
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is False
        assert "Missing" in result["message"]

    @patch("src.connections.ConnectionManager._test_snowflake")
    def test_snowflake_connection_success_mocked(self, mock_test):
        mock_test.return_value = {
            "success": True,
            "message": "Connected to Snowflake v8.40.0",
            "details": {"version": "8.40.0", "warehouse": "WH", "database": "DB", "schema": "SCH"},
        }
        config = ConnectionConfig(
            adapter="snowflake",
            account="test.us-east-1",
            user="user",
            password="pass",
            warehouse="WH",
            database="DB",
            schema="SCH",
        )
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is True
        assert "Snowflake" in result["message"]

    @patch("src.connections.ConnectionManager._test_snowflake")
    def test_snowflake_connection_failure_mocked(self, mock_test):
        mock_test.return_value = {
            "success": False,
            "message": "Snowflake connection failed: 250001: Could not connect",
            "details": {},
        }
        config = ConnectionConfig(
            adapter="snowflake",
            account="bad",
            user="user",
            password="pass",
            warehouse="WH",
            database="DB",
            schema="SCH",
        )
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is False

    def test_databricks_connection_missing_fields(self):
        config = ConnectionConfig(adapter="databricks")
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is False
        assert "Missing" in result["message"]

    @patch("src.connections.ConnectionManager._test_databricks")
    def test_databricks_connection_success_mocked(self, mock_test):
        mock_test.return_value = {
            "success": True,
            "message": "Connected to Databricks (catalog: main)",
            "details": {"catalog": "main", "schema": "default", "host": "dbc-test.cloud.databricks.com"},
        }
        config = ConnectionConfig(
            adapter="databricks",
            host="dbc-test.cloud.databricks.com",
            token="dapi-testtoken",
            http_path="/sql/1.0/warehouses/abc123",
            schema="default",
        )
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is True
        assert "Databricks" in result["message"]

    @patch("src.connections.ConnectionManager._test_databricks")
    def test_databricks_connection_failure_mocked(self, mock_test):
        mock_test.return_value = {
            "success": False,
            "message": "Databricks connection failed: Could not connect",
            "details": {},
        }
        config = ConnectionConfig(
            adapter="databricks",
            host="bad-host",
            token="bad-token",
            http_path="/bad",
            schema="default",
        )
        mgr = ConnectionManager(config)
        result = mgr.test_connection()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Dialect-Aware Function Map Tests
# ---------------------------------------------------------------------------

class TestDialectFunctionMap:
    """Test get_function_map returns correct functions per dialect."""

    def test_duckdb_uses_strftime(self):
        func_map = get_function_map("duckdb")
        assert func_map["TalendDate.formatDate"] == "STRFTIME"

    def test_snowflake_uses_to_char(self):
        func_map = get_function_map("snowflake")
        assert func_map["TalendDate.formatDate"] == "TO_CHAR"

    def test_databricks_uses_date_format(self):
        func_map = get_function_map("databricks")
        assert func_map["TalendDate.formatDate"] == "DATE_FORMAT"

    def test_common_functions_same(self):
        duckdb_map = get_function_map("duckdb")
        snowflake_map = get_function_map("snowflake")
        databricks_map = get_function_map("databricks")
        # UPPER, LOWER, TRIM should be the same across all dialects
        for key in ("StringHandling.UPCASE", "StringHandling.DOWNCASE", "StringHandling.TRIM"):
            assert duckdb_map[key] == snowflake_map[key] == databricks_map[key]

    def test_unknown_dialect_returns_base(self):
        func_map = get_function_map("unknown_dialect")
        assert func_map["TalendDate.formatDate"] == "STRFTIME"  # base default


# ---------------------------------------------------------------------------
# Dialect-Aware Converter Tests
# ---------------------------------------------------------------------------

class TestDialectConverter:
    """Test that TalendToDbtConverter respects dialect parameter."""

    def _make_simple_job(self):
        """Create a minimal parsed Talend job dict for testing."""
        return {
            "filename": "test_job.item",
            "sources": [{
                "component_id": "tMysqlInput_1",
                "component_type": "tMysqlInput",
                "table_name": "raw_orders",
                "database": "jaffle_shop",
                "columns": [
                    {"name": "id", "type": "id_Integer", "key": True, "nullable": False},
                    {"name": "created_at", "type": "id_Date", "key": False, "nullable": True},
                ],
            }],
            "targets": [{
                "component_id": "tMysqlOutput_1",
                "component_type": "tMysqlOutput",
                "table_name": "orders_clean",
                "database": "jaffle_shop",
                "columns": [
                    {"name": "id", "type": "id_Integer", "key": True, "nullable": False},
                    {"name": "formatted_date", "type": "id_String", "key": False, "nullable": True},
                ],
            }],
            "transformations": [{
                "component_id": "tMap_1",
                "component_type": "tMap",
                "column_mappings": [
                    {"output_column": "id", "expression": "row1.id"},
                    {"output_column": "formatted_date", "expression": "TalendDate.formatDate(row1.created_at)"},
                ],
                "joins": [],
                "filters": [],
            }],
            "connections": [{
                "source": "tMysqlInput_1",
                "target": "tMap_1",
                "label": "row1",
                "type": "FLOW",
            }],
        }

    def test_duckdb_dialect_uses_strftime(self):
        converter = TalendToDbtConverter(self._make_simple_job(), dialect="duckdb")
        sql = converter.generate_sql()
        assert "STRFTIME(" in sql
        assert "TO_CHAR(" not in sql

    def test_snowflake_dialect_uses_to_char(self):
        converter = TalendToDbtConverter(self._make_simple_job(), dialect="snowflake")
        sql = converter.generate_sql()
        assert "TO_CHAR(" in sql
        assert "STRFTIME(" not in sql

    def test_databricks_dialect_uses_date_format(self):
        converter = TalendToDbtConverter(self._make_simple_job(), dialect="databricks")
        sql = converter.generate_sql()
        assert "DATE_FORMAT(" in sql
        assert "STRFTIME(" not in sql
        assert "TO_CHAR(" not in sql

    def test_default_dialect_is_duckdb(self):
        converter = TalendToDbtConverter(self._make_simple_job())
        assert converter.dialect == "duckdb"

    def test_convert_returns_result_with_dialect(self):
        converter = TalendToDbtConverter(self._make_simple_job(), dialect="snowflake")
        result = converter.convert(source_schema="MY_SCHEMA")
        assert result.model_name == "orders_clean"
        assert "TO_CHAR(" in result.sql_content
        # Source YAML should have the schema
        source_data = yaml.safe_load(result.source_yaml)
        sources = source_data["sources"]
        assert sources[0].get("schema") == "MY_SCHEMA"


# ---------------------------------------------------------------------------
# Translate Expression with Dialect Tests
# ---------------------------------------------------------------------------

class TestTranslateExpressionDialect:
    """Test translate_expression with different dialects."""

    def test_strftime_duckdb(self):
        expr = "TalendDate.formatDate(row1.created_at)"
        result = translate_expression(expr, {"row1": "orders"}, dialect="duckdb")
        assert "STRFTIME(orders.created_at)" == result

    def test_to_char_snowflake(self):
        expr = "TalendDate.formatDate(row1.created_at)"
        result = translate_expression(expr, {"row1": "orders"}, dialect="snowflake")
        assert "TO_CHAR(orders.created_at)" == result

    def test_date_format_databricks(self):
        expr = "TalendDate.formatDate(row1.created_at)"
        result = translate_expression(expr, {"row1": "orders"}, dialect="databricks")
        assert "DATE_FORMAT(orders.created_at)" == result

    def test_upper_same_all_dialects(self):
        expr = "StringHandling.UPCASE(row1.name)"
        duckdb_result = translate_expression(expr, {"row1": "customers"}, dialect="duckdb")
        snowflake_result = translate_expression(expr, {"row1": "customers"}, dialect="snowflake")
        databricks_result = translate_expression(expr, {"row1": "customers"}, dialect="databricks")
        assert duckdb_result == snowflake_result == databricks_result == "UPPER(customers.name)"


# ---------------------------------------------------------------------------
# validate_sql Dialect Tests
# ---------------------------------------------------------------------------

class TestValidateSqlDialect:
    """Test that validate_sql passes the dialect to sqlfluff."""

    def test_validate_sql_accepts_dialect(self, tmp_path):
        """Verify the dialect parameter is wired through."""
        sql_file = tmp_path / "test_model.sql"
        sql_file.write_text("{{ config(materialized='table') }}\n\nSELECT 1 AS id\n")
        # This should not raise — just verifying it accepts the param
        result = validate_sql(str(sql_file), dialect="duckdb")
        assert isinstance(result, dict)
        assert "passed" in result


# ---------------------------------------------------------------------------
# Helper: get_default_config
# ---------------------------------------------------------------------------

class TestGetDefaultConfig:
    """Test the get_default_config helper."""

    def test_returns_duckdb(self):
        config = get_default_config()
        assert config.adapter == "duckdb"
        assert config.duckdb_path == "jaffle_shop.duckdb"


# ---------------------------------------------------------------------------
# Constants Tests
# ---------------------------------------------------------------------------

class TestConstants:
    """Test that module-level constants are correctly defined."""

    def test_supported_adapters(self):
        assert "duckdb" in SUPPORTED_ADAPTERS
        assert "snowflake" in SUPPORTED_ADAPTERS
        assert "databricks" in SUPPORTED_ADAPTERS

    def test_sqlfluff_dialect_map(self):
        assert SQLFLUFF_DIALECT_MAP["duckdb"] == "duckdb"
        assert SQLFLUFF_DIALECT_MAP["snowflake"] == "snowflake"
        assert SQLFLUFF_DIALECT_MAP["databricks"] == "sparksql"

    def test_dialect_overrides_duckdb_empty(self):
        assert DIALECT_FUNCTION_OVERRIDES["duckdb"] == {}

    def test_dialect_overrides_snowflake_has_entries(self):
        assert len(DIALECT_FUNCTION_OVERRIDES["snowflake"]) > 0

    def test_dialect_overrides_databricks_has_entries(self):
        assert len(DIALECT_FUNCTION_OVERRIDES["databricks"]) > 0
        assert DIALECT_FUNCTION_OVERRIDES["databricks"]["TalendDate.formatDate"] == "DATE_FORMAT"
