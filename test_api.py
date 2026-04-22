"""
dbt Model Agent — Demo Test Client

Reads demo_schemas.json and fires sequential POST requests to the
agent API, then runs a full dbt compile validation.
"""

import json
import logging
import time
from logging.handlers import RotatingFileHandler

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = "http://127.0.0.1:8000/generate_model"
VALIDATE_URL = "http://127.0.0.1:8000/validate_project"
REQUEST_TIMEOUT = 300  # seconds
RATE_LIMIT_DELAY = 15  # seconds between requests

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("test_api")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

# File handler — writes to logs/test_api.log
file_handler = RotatingFileHandler(
    "logs/test_api.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logger.info("Loading demo_schemas.json…")

    try:
        with open("demo_schemas.json", "r") as fh:
            schemas = json.load(fh)
    except FileNotFoundError:
        logger.error("demo_schemas.json not found. Place it in the project root.")
        return
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in demo_schemas.json: %s", exc)
        return

    successes, failures = 0, 0

    for i, schema in enumerate(schemas, start=1):
        table_name = schema.get("table_name", "unknown")
        logger.info("=" * 50)
        logger.info("[%d/%d] Generating model: %s", i, len(schemas), table_name)
        logger.info("=" * 50)

        try:
            response = requests.post(
                API_URL,
                json={"schema_def": schema},
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                data = response.json()
                tools_called = [
                    step["tool"]
                    for step in data.get("agent_transcript", [])
                    if step.get("tool")
                ]
                logger.info(
                    "✓ %s completed — tools called: %s",
                    table_name,
                    ", ".join(tools_called) or "none",
                )
                successes += 1
            else:
                logger.error(
                    "✗ %s failed (HTTP %d): %s",
                    table_name,
                    response.status_code,
                    response.text[:300],
                )
                failures += 1

        except requests.exceptions.Timeout:
            logger.error("✗ %s timed out after %ds", table_name, REQUEST_TIMEOUT)
            failures += 1
        except requests.exceptions.ConnectionError:
            logger.error("✗ Cannot connect to API at %s — is the server running?", API_URL)
            failures += 1
            break
        except requests.exceptions.RequestException as exc:
            logger.error("✗ %s request failed: %s", table_name, exc)
            failures += 1

        # Rate-limit delay between requests
        if i < len(schemas):
            logger.info("Waiting %ds before next request…", RATE_LIMIT_DELAY)
            time.sleep(RATE_LIMIT_DELAY)

    # --- Full project validation ---
    logger.info("=" * 50)
    logger.info("Running full dbt compile validation…")
    logger.info("=" * 50)

    try:
        response = requests.post(VALIDATE_URL, timeout=60)
        data = response.json()
        if data.get("success"):
            logger.info("✓ dbt compile PASSED — all models are valid")
        else:
            logger.error(
                "✗ dbt compile FAILED:\n%s\n%s",
                data.get("stderr", ""),
                data.get("stdout", ""),
            )
            failures += 1
    except requests.exceptions.RequestException as exc:
        logger.error("✗ Validation request failed: %s", exc)
        failures += 1

    # --- Summary ---
    logger.info("=" * 50)
    logger.info("DONE — %d succeeded, %d failed", successes, failures)
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
