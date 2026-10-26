# baton-mcp — same targets and philosophy as baton-console's Makefile.
#
# uv is the entry point for everything: it builds the venv from the committed
# uv.lock and supplies the interpreter, so a system Python is not a prerequisite.
# PYTHON_VERSION matches the console's pin (python:3.11-slim in prod) so the
# venv you test in is the interpreter that runs in prod.

PYTHON_VERSION ?= 3.11
VENV ?= .venv
BIN = $(VENV)/bin

.PHONY: install dev live-dev test lint format format-check typecheck ci

# `--locked` FAILS on a stale lock rather than re-resolving, which is what
# makes this venv the same tree CI builds. Run `uv lock` here after changing
# a dependency.
install:
	UV_PROJECT_ENVIRONMENT=$(abspath $(VENV)) uv sync --locked --extra dev --python $(PYTHON_VERSION)

# Dev server (Streamable HTTP). Overridable via env-style args:
# Console in another shell first: `make dev` from baton-console/ (uvicorn :8000).
# `dev` runs BOTH the data plane (BATON_API_BASE_URL) against the local console,
# so a tool call shows up in the console's uvicorn log
dev:
	BATON_API_BASE_URL=http://localhost:8000 \
	BATON_MCP_PORT=8010 \
	BATON_MCP_DEBUG=1 \
	$(BIN)/python -m baton_mcp

# ⚠ `make dev-live` calls the REAL console API
# That is the point — dogfooding the MCP tools against real answers
# Treat the browser at :8011 as prod.
live-dev:
	BATON_MCP_PORT=8011 \
	BATON_MCP_DEBUG=1 \
	$(BIN)/python -m baton_mcp

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check src tests

format:
	$(BIN)/ruff format src tests

typecheck:
	$(BIN)/mypy src/baton_mcp

# Names the fix. ruff's own output says which files differ but never that
# `make format` exists — the most common way `make ci` fails mid-edit.
format-check:
	@$(BIN)/ruff format --check src tests || { \
	  printf '\n  ^ formatting differs. Fix with:\n\n      make format\n\n  then re-run.\n\n'; \
	  exit 1; \
	}

# CI gate — lint + format-check + typecheck + test
ci: lint format-check typecheck test

# Refresh the vendored OpenAPI spec from a locally running baton-console.
# Run `make dev` in baton-console/ first (uvicorn :8000, docs enabled in dev).
# The script keeps only /v0/metrics/ paths, strips agent-useless facets, and
# writes stable (sorted, pretty) JSON so refreshes diff cleanly.
refresh-openapi:
	$(BIN)/python scripts/refresh_openapi.py
