.PHONY: venv install test coverage lint format-check type-check check \
	ha-up ha-down ha-restart ha-logs ha-reset

PYTHON ?= python3.14
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PY := $(BIN)/python

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip

install: venv
	$(PIP) install -r requirements-dev.txt

test:
	$(PY) -m pytest tests/ -v --tb=short

coverage:
	$(PY) -m pytest tests/ --cov=custom_components/schluterditraheat --cov-report=term-missing

lint:
	$(PY) -m ruff check .

format-check:
	$(PY) -m black --check --line-length 100 --include '\.py$$' custom_components/ tests/

type-check:
	$(PY) -m mypy custom_components/schluterditraheat --check-untyped-defs

check: coverage lint format-check type-check

# Local Home Assistant in Docker (see dev-config/README.md)
COMPOSE ?= docker compose

ha-up:
	$(COMPOSE) up -d
	@echo "Home Assistant: http://localhost:$${HA_PORT:-8123}"

ha-down:
	$(COMPOSE) down

ha-restart:
	$(COMPOSE) restart

ha-logs:
	$(COMPOSE) logs -f --tail=100

# Wipes the HA config volume: onboarding, config entries and statistics
ha-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d
	@echo "Home Assistant (fresh): http://localhost:$${HA_PORT:-8123}"
