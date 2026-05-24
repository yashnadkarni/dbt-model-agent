.PHONY: install test lint ui server seed compile clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install all dependencies
	python3 -m venv venv
	venv/bin/pip install -e ".[dev]"

test: ## Run the full pytest suite
	venv/bin/python -m pytest tests/ -v

lint: ## Run sqlfluff on all generated models
	venv/bin/sqlfluff lint models/generated/

ui: ## Launch the Streamlit UI
	venv/bin/streamlit run src/ui.py

server: ## Start the FastAPI server
	venv/bin/uvicorn src.agent:app

seed: ## Load seed data into DuckDB
	venv/bin/dbt seed

compile: ## Run dbt compile to validate the full project
	venv/bin/dbt compile

clean: ## Remove generated models and build artifacts
	rm -rf models/generated/*.sql models/generated/*_schema.yml
	rm -rf target/ logs/ __pycache__/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
