SHELL := /bin/bash

UV := uv
NPM := npm

API_HOST ?= 0.0.0.0
API_PORT ?= 8000
RESEARCH_HOST ?= 0.0.0.0
RESEARCH_PORT ?= 5001
MOCK_AGENT_HOST ?= 0.0.0.0
MOCK_AGENT_PORT ?= 6123

.PHONY: help sync db-init test lint lint-python format format-check typecheck check check-all smoke smoke-api smoke-research api research mock-agent frontend-install frontend-dev frontend-lint registry-sync stripe-webhook

help:
	@printf "Available targets:\n"
	@printf "  make sync             Create/update the Python environment with uv\n"
	@printf "  make db-init          Apply Alembic migrations to the local database\n"
	@printf "  make test             Run the backend test suite\n"
	@printf "  make lint             Run ruff and frontend lint\n"
	@printf "  make lint-python      Run ruff against the Python codebase\n"
	@printf "  make format           Format Python code with ruff format\n"
	@printf "  make format-check     Check Python formatting with ruff format\n"
	@printf "  make typecheck        Run mypy across the Python codebase\n"
	@printf "  make smoke            Import-check the API and research apps\n"
	@printf "  make check            Run the passing day-to-day verification set\n"
	@printf "  make check-all        Run tests, lint, typecheck, and smoke checks\n"
	@printf "  make api              Start the FastAPI API server\n"
	@printf "  make research         Start the research agents server\n"
	@printf "  make mock-agent       Start the mock marketplace agent\n"
	@printf "  make frontend-install Install frontend dependencies\n"
	@printf "  make frontend-dev     Start the Next.js frontend\n"
	@printf "  make frontend-lint    Run frontend lint checks\n"
	@printf "  make registry-sync    Force a registry sync\n"
	@printf "  make stripe-webhook   Start Stripe webhook listener using STRIPE_SECRET_KEY from .env\n"

sync:
	$(UV) sync

db-init:
	$(UV) run alembic upgrade head

test:
	$(UV) run pytest tests

lint-python:
	$(UV) run ruff check .

frontend-lint:
	$(NPM) --prefix frontend run lint

lint: lint-python frontend-lint

format:
	$(UV) run ruff format .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy api agents shared scripts tests

smoke-api:
	$(UV) run python -c "from api.main import app; print(app.title)"

smoke-research:
	$(UV) run python -c "from agents.research.main import app; print(app.title)"

smoke: smoke-api smoke-research

check: test smoke

check-all: test lint typecheck smoke

api:
	$(UV) run python -m uvicorn api.main:app --reload --host $(API_HOST) --port $(API_PORT)

research:
	$(UV) run python -m uvicorn agents.research.main:app --reload --host $(RESEARCH_HOST) --port $(RESEARCH_PORT)

mock-agent:
	$(UV) run python -m uvicorn agents.mock_marketplace_agent.server:app --reload --host $(MOCK_AGENT_HOST) --port $(MOCK_AGENT_PORT)

frontend-install:
	$(NPM) --prefix frontend install

frontend-dev:
	$(NPM) --prefix frontend run dev

registry-sync:
	$(UV) run python scripts/sync_agents_from_registry.py --force

stripe-webhook:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	if [ -z "$$STRIPE_SECRET_KEY" ]; then \
		echo "STRIPE_SECRET_KEY is missing. Set it in .env before running make stripe-webhook."; \
		exit 1; \
	fi; \
	echo "Forwarding Stripe webhooks to http://localhost:$(API_PORT)/api/credits/webhook using STRIPE_SECRET_KEY from .env"; \
	stripe listen --api-key "$$STRIPE_SECRET_KEY" --forward-to localhost:$(API_PORT)/api/credits/webhook
