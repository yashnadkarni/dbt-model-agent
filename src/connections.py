"""
Connection Manager — Multi-adapter support for dbt profiles.

Supports DuckDB (default, local), Snowflake, and Databricks (cloud warehouses).
Generates dynamic profiles.yml files and provides dialect-specific
configuration for sqlfluff and the converter.

Usage:
    from src.connections import ConnectionManager, ConnectionConfig

    # DuckDB (default — no credentials needed)
    config = ConnectionConfig(adapter="duckdb")
    mgr = ConnectionManager(config)
    mgr.write_profiles_yml()

    # Snowflake
    config = ConnectionConfig(
        adapter="snowflake",
        account="xy12345.us-east-1",
        user="transform_user",
        password="secret",
        role="TRANSFORM_ROLE",
        warehouse="TRANSFORM_WH",
        database="ANALYTICS",
        schema="DBT_DEV",
    )
    mgr = ConnectionManager(config)
    mgr.test_connection()   # raises on failure
    mgr.write_profiles_yml()
"""

import os
import logging
from dataclasses import dataclass, field

import yaml

from src import PROJECT_ROOT

logger = logging.getLogger("agent.connections")

# ---------------------------------------------------------------------------
# Supported Adapters
# ---------------------------------------------------------------------------
SUPPORTED_ADAPTERS = ("duckdb", "snowflake", "databricks")

# Adapter → sqlfluff dialect mapping
SQLFLUFF_DIALECT_MAP = {
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "databricks": "sparksql",   # sqlfluff uses 'sparksql' for Databricks SQL
}

# Adapter → dbt adapter package name (for install instructions)
DBT_ADAPTER_PACKAGES = {
    "duckdb": "dbt-duckdb",
    "snowflake": "dbt-snowflake",
    "databricks": "dbt-databricks",
}

# Adapter → default source schema
DEFAULT_SOURCE_SCHEMA = {
    "duckdb": "main",         # DuckDB seeds land in the 'main' schema
    "snowflake": "",          # User provides via ConnectionConfig.schema
    "databricks": "",         # User provides via ConnectionConfig.schema
}

# Adapter-specific function overrides for the converter.
# Keys that differ from the DuckDB defaults in converter.TALEND_FUNCTION_MAP.
DIALECT_FUNCTION_OVERRIDES = {
    "duckdb": {},  # DuckDB is the baseline — no overrides needed
    "snowflake": {
        "TalendDate.formatDate": "TO_CHAR",       # DuckDB uses STRFTIME
        "TalendDate.getCurrentDate": "CURRENT_DATE",  # Same in Snowflake
    },
    "databricks": {
        "TalendDate.formatDate": "DATE_FORMAT",   # Spark/Databricks date→string
        "TalendDate.getCurrentDate": "CURRENT_DATE",
    },
}


# ---------------------------------------------------------------------------
# Connection Config
# ---------------------------------------------------------------------------

@dataclass
class ConnectionConfig:
    """
    Configuration for a dbt profile connection.

    For DuckDB: only `adapter` and optionally `duckdb_path` are needed.
    For Snowflake: account, user, password, warehouse, database, schema
    are required. role and threads are optional.
    For Databricks: host, token, http_path, schema are required.
    catalog and threads are optional.
    """
    adapter: str = "duckdb"

    # DuckDB-specific
    duckdb_path: str = "jaffle_shop.duckdb"

    # Snowflake-specific
    account: str = ""
    user: str = ""
    password: str = ""
    role: str = ""
    warehouse: str = ""
    database: str = ""
    schema: str = ""

    # Databricks-specific
    host: str = ""            # e.g. dbc-xxxxx.cloud.databricks.com
    token: str = ""           # Personal Access Token
    http_path: str = ""       # e.g. /sql/1.0/warehouses/abcdef123456
    catalog: str = ""         # Unity Catalog name (optional, defaults to 'hive_metastore')

    # Common
    threads: int = 4
    profile_name: str = "jaffle_shop"
    target_name: str = "dev"

    def __post_init__(self):
        if self.adapter not in SUPPORTED_ADAPTERS:
            raise ValueError(
                f"Unsupported adapter: '{self.adapter}'. "
                f"Supported: {', '.join(SUPPORTED_ADAPTERS)}"
            )

    @classmethod
    def from_env(cls, adapter: str = "duckdb") -> "ConnectionConfig":
        """
        Create a ConnectionConfig from environment variables.

        DuckDB: No env vars needed (uses defaults).
        Snowflake: Reads SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, etc.
        Databricks: Reads DATABRICKS_HOST, DATABRICKS_TOKEN, etc.
        """
        if adapter == "duckdb":
            return cls(adapter="duckdb")

        if adapter == "snowflake":
            return cls(
                adapter="snowflake",
                account=os.environ.get("SNOWFLAKE_ACCOUNT", ""),
                user=os.environ.get("SNOWFLAKE_USER", ""),
                password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
                role=os.environ.get("SNOWFLAKE_ROLE", ""),
                warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
                database=os.environ.get("SNOWFLAKE_DATABASE", ""),
                schema=os.environ.get("SNOWFLAKE_SCHEMA", ""),
            )

        if adapter == "databricks":
            return cls(
                adapter="databricks",
                host=os.environ.get("DATABRICKS_HOST", ""),
                token=os.environ.get("DATABRICKS_TOKEN", ""),
                http_path=os.environ.get("DATABRICKS_HTTP_PATH", ""),
                catalog=os.environ.get("DATABRICKS_CATALOG", ""),
                schema=os.environ.get("DATABRICKS_SCHEMA", ""),
            )

        raise ValueError(f"Unsupported adapter: '{adapter}'")

    def validate(self) -> list[str]:
        """
        Validate that all required fields are set for the chosen adapter.
        Returns a list of missing field names (empty = valid).
        """
        missing = []
        if self.adapter == "snowflake":
            for fld in ("account", "user", "password", "warehouse", "database", "schema"):
                if not getattr(self, fld):
                    missing.append(fld)
        elif self.adapter == "databricks":
            for fld in ("host", "token", "http_path", "schema"):
                if not getattr(self, fld):
                    missing.append(fld)
        return missing

    @property
    def source_schema(self) -> str:
        """
        Return the appropriate source schema for the converter.
        DuckDB seeds land in 'main'. Snowflake/Databricks use the configured schema.
        """
        if self.adapter == "duckdb":
            return "main"
        if self.adapter in ("snowflake", "databricks"):
            return self.schema
        return ""

    @property
    def sqlfluff_dialect(self) -> str:
        """Return the sqlfluff dialect string for this adapter."""
        return SQLFLUFF_DIALECT_MAP.get(self.adapter, "ansi")

    @property
    def function_overrides(self) -> dict:
        """Return dialect-specific function translation overrides."""
        return DIALECT_FUNCTION_OVERRIDES.get(self.adapter, {})


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Manages dbt profile generation, connection testing, and dialect
    configuration for the active adapter.
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config

    def generate_profiles_dict(self) -> dict:
        """
        Generate the profiles.yml dict structure for the configured adapter.
        """
        if self.config.adapter == "duckdb":
            return {
                self.config.profile_name: {
                    "target": self.config.target_name,
                    "outputs": {
                        self.config.target_name: {
                            "type": "duckdb",
                            "path": self.config.duckdb_path,
                            "threads": self.config.threads,
                        }
                    }
                }
            }

        if self.config.adapter == "snowflake":
            output = {
                "type": "snowflake",
                "account": self.config.account,
                "user": self.config.user,
                "password": self.config.password,
                "warehouse": self.config.warehouse,
                "database": self.config.database,
                "schema": self.config.schema,
                "threads": self.config.threads,
            }
            # Only include role if set
            if self.config.role:
                output["role"] = self.config.role

            return {
                self.config.profile_name: {
                    "target": self.config.target_name,
                    "outputs": {
                        self.config.target_name: output,
                    }
                }
            }

        if self.config.adapter == "databricks":
            output = {
                "type": "databricks",
                "host": self.config.host,
                "token": self.config.token,
                "http_path": self.config.http_path,
                "schema": self.config.schema,
                "threads": self.config.threads,
            }
            # Only include catalog if set (defaults to hive_metastore)
            if self.config.catalog:
                output["catalog"] = self.config.catalog

            return {
                self.config.profile_name: {
                    "target": self.config.target_name,
                    "outputs": {
                        self.config.target_name: output,
                    }
                }
            }

        raise ValueError(f"Unsupported adapter: {self.config.adapter}")

    def write_profiles_yml(self, output_dir: str = PROJECT_ROOT) -> str:
        """
        Write a profiles.yml file to the specified directory.
        Returns the path to the written file.
        """
        profiles = self.generate_profiles_dict()
        profiles_path = os.path.join(output_dir, "profiles.yml")

        with open(profiles_path, "w") as fh:
            yaml.dump(profiles, fh, default_flow_style=False, sort_keys=False)

        logger.info("Wrote profiles.yml for adapter '%s' → %s",
                     self.config.adapter, profiles_path)
        return profiles_path

    def test_connection(self) -> dict:
        """
        Test the connection to the configured adapter.

        Returns:
            dict with keys: success (bool), message (str), details (dict)
        """
        if self.config.adapter == "duckdb":
            return self._test_duckdb()
        if self.config.adapter == "snowflake":
            return self._test_snowflake()
        if self.config.adapter == "databricks":
            return self._test_databricks()
        return {"success": False, "message": f"Unsupported adapter: {self.config.adapter}"}

    def _test_duckdb(self) -> dict:
        """Test DuckDB connection by opening the database file."""
        db_path = self.config.duckdb_path
        if not os.path.isabs(db_path):
            db_path = os.path.join(PROJECT_ROOT, db_path)

        try:
            import duckdb
            conn = duckdb.connect(db_path, read_only=True)
            tables = conn.execute("SHOW TABLES").fetchall()
            conn.close()
            table_names = [t[0] for t in tables]
            return {
                "success": True,
                "message": f"Connected to DuckDB ({len(table_names)} tables found)",
                "details": {"tables": table_names, "path": db_path},
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"DuckDB connection failed: {exc}",
                "details": {},
            }

    def _test_snowflake(self) -> dict:
        """
        Test Snowflake connection using snowflake-connector-python.

        Verifies credentials, warehouse, database, and schema access.
        """
        # First validate required fields
        missing = self.config.validate()
        if missing:
            return {
                "success": False,
                "message": f"Missing required Snowflake fields: {', '.join(missing)}",
                "details": {"missing_fields": missing},
            }

        try:
            import snowflake.connector
        except ImportError:
            return {
                "success": False,
                "message": (
                    "snowflake-connector-python is not installed. "
                    "Run: pip install snowflake-connector-python"
                ),
                "details": {},
            }

        try:
            conn = snowflake.connector.connect(
                account=self.config.account,
                user=self.config.user,
                password=self.config.password,
                role=self.config.role or None,
                warehouse=self.config.warehouse,
                database=self.config.database,
                schema=self.config.schema,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT CURRENT_VERSION()")
            version = cursor.fetchone()[0]
            cursor.execute("SELECT CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()")
            wh, db, sch = cursor.fetchone()
            cursor.close()
            conn.close()

            return {
                "success": True,
                "message": f"Connected to Snowflake v{version}",
                "details": {
                    "version": version,
                    "warehouse": wh,
                    "database": db,
                    "schema": sch,
                    "account": self.config.account,
                },
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Snowflake connection failed: {exc}",
                "details": {},
            }

    def _test_databricks(self) -> dict:
        """
        Test Databricks connection using databricks-sql-connector.

        Verifies host, token, http_path, and schema access.
        """
        # First validate required fields
        missing = self.config.validate()
        if missing:
            return {
                "success": False,
                "message": f"Missing required Databricks fields: {', '.join(missing)}",
                "details": {"missing_fields": missing},
            }

        try:
            from databricks import sql as databricks_sql
        except ImportError:
            return {
                "success": False,
                "message": (
                    "databricks-sql-connector is not installed. "
                    "Run: pip install databricks-sql-connector"
                ),
                "details": {},
            }

        try:
            # Ensure host doesn't include https://
            host = self.config.host.replace("https://", "").replace("http://", "").rstrip("/")

            conn = databricks_sql.connect(
                server_hostname=host,
                http_path=self.config.http_path,
                access_token=self.config.token,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT current_catalog(), current_schema()")
            cat, sch = cursor.fetchone()
            cursor.close()
            conn.close()

            return {
                "success": True,
                "message": f"Connected to Databricks (catalog: {cat})",
                "details": {
                    "catalog": cat,
                    "schema": sch,
                    "host": host,
                },
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Databricks connection failed: {exc}",
                "details": {},
            }


# ---------------------------------------------------------------------------
# Helper: Get default config (DuckDB)
# ---------------------------------------------------------------------------

def get_default_config() -> ConnectionConfig:
    """Return the default DuckDB connection config."""
    return ConnectionConfig(adapter="duckdb")
