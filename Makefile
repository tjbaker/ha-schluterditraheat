.PHONY: help venv install test coverage lint format-check type-check check \
	docker-up docker-restart docker-logs docker-logs-schluter docker-status \
	docker-shell docker-pull docker-down docker-reset

PYTHON ?= python3.14
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PY := $(BIN)/python
COMPOSE ?= docker compose
# Host port for the dev Home Assistant; override to run beside another instance
# (make docker-up HA_PORT=8124). Exported so docker-compose.yml sees it too.
HA_PORT ?= 8123
export HA_PORT

venv: ## Create the virtualenv
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: venv ## Install dev requirements into the virtualenv
	$(PIP) install -r requirements-dev.txt

test: ## Run all tests
	$(PY) -m pytest tests/ -v --tb=short

coverage: ## Run tests with a coverage report
	$(PY) -m pytest tests/ --cov=custom_components/schluterditraheat --cov-report=term-missing

lint: ## Run Ruff
	$(PY) -m ruff check .

format-check: ## Check Black formatting
	$(PY) -m black --check --line-length 100 --include '\.py$$' custom_components/ tests/

type-check: ## Run mypy
	$(PY) -m mypy custom_components/schluterditraheat --check-untyped-defs

check: coverage lint format-check type-check ## Run every check CI runs

# --- Local Home Assistant in Docker (see docker-compose.yml, dev-config/) ---

docker-up: ## Start the dev Home Assistant (port 8123, or HA_PORT=...)
	$(COMPOSE) up -d
	@echo "Home Assistant: http://localhost:$(HA_PORT)"

docker-restart: ## Restart the container to pick up code changes
	$(COMPOSE) restart

docker-logs: ## Follow the container log, starting from the last 100 lines
	$(COMPOSE) logs -f --tail=100

docker-logs-schluter: ## Follow only this integration's log lines
	$(COMPOSE) logs -f --tail=100 | grep --line-buffered -i schluterditraheat

docker-status: ## Show container state and health
	$(COMPOSE) ps

docker-shell: ## Open a shell inside the container
	$(COMPOSE) exec homeassistant bash

docker-pull: ## Pull the image pinned in docker-compose.yml
	$(COMPOSE) pull

docker-down: ## Stop and remove the container, keeping its config volume
	$(COMPOSE) down

docker-reset: ## Delete the config volume and start fresh (wipes all HA data)
	$(COMPOSE) down -v
	$(COMPOSE) up -d
	@echo "Home Assistant: http://localhost:$(HA_PORT) (onboarding required again)"
