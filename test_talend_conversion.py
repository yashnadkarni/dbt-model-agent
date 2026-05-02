"""
Talend-to-dbt Conversion Test Suite

Tests the full pipeline: Parse Talend XML → Convert to dbt → Write files → Validate.
No LLM or API server required — runs entirely locally.

Usage:
    python3 test_talend_conversion.py
"""

import os
import sys
import subprocess
import logging
from dataclasses import asdict

from talend_parser import parse_talend_job
from talend_to_dbt import TalendToDbtConverter, write_dbt_files, validate_sql

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("test_talend")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(PROJECT_ROOT, "talend_jobs")
GENERATED_DIR = os.path.join(PROJECT_ROOT, "models", "generated")


def test_single_job(filepath: str) -> dict:
    """
    Test the full conversion pipeline for a single Talend job.

    Steps:
      1. Parse the Talend XML
      2. Convert to dbt (deterministic — no LLM)
      3. Write .sql, .yml, sources.yml files
      4. Run sqlfluff lint on the generated SQL
      5. Return results
    """
    job_name = os.path.basename(filepath)
    logger.info("=" * 60)
    logger.info("Testing: %s", job_name)
    logger.info("=" * 60)

    # Step 1: Parse
    logger.info("[1/4] Parsing Talend XML…")
    parsed = parse_talend_job(filepath)
    parsed_dict = asdict(parsed)
    logger.info(
        "  Sources: %d, Transformations: %d, Targets: %d, Connections: %d",
        len(parsed_dict["sources"]),
        len(parsed_dict["transformations"]),
        len(parsed_dict["targets"]),
        len(parsed_dict["connections"]),
    )

    # Step 2: Convert
    logger.info("[2/4] Converting to dbt…")
    converter = TalendToDbtConverter(parsed_dict)
    result = converter.convert()
    logger.info("  Model name: %s", result.model_name)
    logger.info("  Source tables: %s", ", ".join(result.source_tables))
    if result.warnings:
        for w in result.warnings:
            logger.warning("  ⚠ %s", w)

    # Print the generated SQL
    logger.info("  Generated SQL:")
    for line in result.sql_content.strip().split("\n"):
        logger.info("    %s", line)

    # Step 3: Write files
    logger.info("[3/4] Writing dbt files…")
    paths = write_dbt_files(result)
    logger.info("  SQL:     %s", paths["sql_path"])
    logger.info("  Schema:  %s", paths["schema_path"])
    logger.info("  Sources: %s", paths["source_path"])

    # Step 4: Validate
    logger.info("[4/4] Running sqlfluff lint…")
    lint_result = validate_sql(paths["sql_path"])
    if lint_result["passed"]:
        logger.info("  ✓ sqlfluff lint PASSED")
    else:
        logger.error("  ✗ sqlfluff lint FAILED:\n%s", lint_result["output"])

    return {
        "job": job_name,
        "model": result.model_name,
        "sql_valid": lint_result["passed"],
        "warnings": result.warnings,
    }


def run_dbt_compile() -> bool:
    """Run dbt compile to validate the full project after all conversions."""
    logger.info("=" * 60)
    logger.info("Running full dbt compile validation…")
    logger.info("=" * 60)

    venv_dbt = os.path.join(PROJECT_ROOT, "venv", "bin", "dbt")
    try:
        result = subprocess.run(
            [venv_dbt, "compile"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("✓ dbt compile PASSED — all models valid")
            return True
        else:
            logger.error("✗ dbt compile FAILED:\n%s\n%s", result.stderr, result.stdout)
            return False
    except FileNotFoundError:
        logger.error("dbt binary not found at %s", venv_dbt)
        return False


def main():
    """Test all Talend jobs in order of increasing complexity."""
    # Ordered from simplest to most complex
    job_files = [
        "filter_active_customers.item",    # Simple: source → filter → target
        "join_orders_customers.item",      # Medium: 2 sources → join → target
        "aggregate_payments.item",         # Complex: source → transform → aggregate → target
    ]

    results = []
    for job_file in job_files:
        filepath = os.path.join(JOBS_DIR, job_file)
        if not os.path.exists(filepath):
            logger.error("Job file not found: %s", filepath)
            continue
        result = test_single_job(filepath)
        results.append(result)
        print()  # visual separator

    # Run dbt compile on the full project
    dbt_ok = run_dbt_compile()

    # --- Summary ---
    print()
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    all_passed = True
    for r in results:
        status = "✓" if r["sql_valid"] else "✗"
        logger.info(
            "  %s  %-35s → %-20s (lint: %s)",
            status,
            r["job"],
            r["model"],
            "pass" if r["sql_valid"] else "FAIL",
        )
        if not r["sql_valid"]:
            all_passed = False

    dbt_status = "✓" if dbt_ok else "✗"
    logger.info("  %s  dbt compile: %s", dbt_status, "PASSED" if dbt_ok else "FAILED")

    if all_passed and dbt_ok:
        logger.info("\n🎉 All tests passed!")
    else:
        logger.error("\n❌ Some tests failed — review output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
