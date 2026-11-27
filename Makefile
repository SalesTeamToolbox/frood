.PHONY: install install-dev test test-verbose test-security lint format check security run run-headless clean help
SHELL := /bin/bash

PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/python -m pytest
RUFF := $(VENV)/bin/ruff

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev:  ## Install development dependencies (testing, linting, security)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	@if [ -f $(VENV)/bin/pre-commit ]; then $(VENV)/bin/pre-commit install; fi

test:  ## Run test suite (stop on first failure; waits for the box-wide suite lock)
	@if [ "$${FROOD_SUITE_LOCK_HELD:-0}" = "1" ]; then exec $(PYTEST) tests/ -x -q; fi; \
	. "$(CURDIR)/orchestrator/ops/workstation/suite-lock.sh"; \
	suite_lock_acquire "frood make test ($(CURDIR))" || exit 1; \
	pid=; \
	cleanup_term() { if [ -n "$$pid" ]; then kill -TERM $$pid 2>/dev/null; \
	  i=0; while kill -0 $$pid 2>/dev/null && [ $$i -lt 20 ]; do sleep 0.1; i=$$((i+1)); done; \
	  kill -KILL $$pid 2>/dev/null; wait $$pid 2>/dev/null; fi; \
	  suite_lock_release; exit 143; }; \
	cleanup_int() { if [ -n "$$pid" ]; then kill -TERM $$pid 2>/dev/null; \
	  i=0; while kill -0 $$pid 2>/dev/null && [ $$i -lt 20 ]; do sleep 0.1; i=$$((i+1)); done; \
	  kill -KILL $$pid 2>/dev/null; wait $$pid 2>/dev/null; fi; \
	  suite_lock_release; exit 130; }; \
	trap cleanup_term TERM; trap cleanup_int INT; \
	FROOD_SUITE_LOCK_HELD=1 $(PYTEST) tests/ -x -q & pid=$$!; \
	wait $$pid; rc=$$?; \
	trap - TERM INT; \
	suite_lock_release; exit $$rc

test-verbose:  ## Run tests with verbose output
	$(PYTEST) tests/ -v

test-security:  ## Run security-focused tests only
	$(PYTEST) tests/test_security.py tests/test_sandbox.py tests/test_command_filter.py -v

lint:  ## Run linter (ruff check)
	$(RUFF) check .

format:  ## Format code (ruff format + auto-fix)
	$(RUFF) format .
	$(RUFF) check --fix .

check:  ## Run all checks (lint + tests)
	@$(MAKE) lint
	@$(MAKE) test

security:  ## Run security scanning (bandit + safety)
	$(VENV)/bin/bandit -r . -x tests,.venv,venv -ll
	$(VENV)/bin/safety check -r requirements.txt 2>/dev/null || true

run:  ## Start Frood (dashboard at http://localhost:8000)
	$(VENV)/bin/python frood.py

run-headless:  ## Start Frood without dashboard
	$(VENV)/bin/python frood.py --no-dashboard

clean:  ## Remove generated files and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
