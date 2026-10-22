# baton-mcp — same targets and philosophy as baton-console's Makefile.
#
# uv is the entry point for everything: it builds the venv from the committed
# uv.lock and supplies the interpreter, so a system Python is not a prerequisite.
# PYTHON_VERSION matches the console's pin (python:3.11-slim in prod) so the
# venv you test in is the interpreter that runs in prod.

PYTHON_VERSION ?= 3.11
VENV ?= .venv
BIN = $(VENV)/bin

.PHONY: install dev prod test lint format format-check typecheck ci

# `--locked` FAILS on a stale lock rather than re-resolving, which is what
# makes this venv the same tree CI builds. Run `uv lock` here after changing
# a dependency.
install:
	UV_PROJECT_ENVIRONMENT=$(abspath $(VENV)) uv sync --locked --extra dev --python $(PYTHON_VERSION)

# Dev server (Streamable HTTP). Overridable via env-style args:
# `make run BATON_MCP_PORT=8001` or `BATON_API_BASE_URL=http://localhost:8000 make run`
# The dev proxy needs the app's own port knob regardless of which target:
BATON_MCP_PORT ?= 8010

# Console in another shell first: `make dev` from baton-console/ (uvicorn :8000).

# ⚠ `make prod` proxies to the REAL console: every console page you open
# through it runs against prod data and prod spend (signup, sign-in, account
# settings are all no-different). That is the point — dogfooding the MCP tools
# against real answers — but treat the browser at :8011 as prod.
BATON_PROD_CONSOLE_URL ?= https://baton.goodtiming.ai
BATON_PROD_PORT ?= 8011

# Command-line make vars are NOT exported to recipes by default, so the env
# vars ride on the command itself — `make run BATON_MCP_PORT=8001` would
# otherwise be accepted by make and silently ignored by the app.
# `dev` runs BOTH the data plane (BATON_API_BASE_URL) and the browser proxy
# (BATON_DEV_CONSOLE_URL) against the local console, so a tool call shows up
# in the console's uvicorn log AND the browser pages you open on :8010 land on
# the local console. `prod` keeps the data plane on prod (real answers) and
# proxies browser pages to prod.
dev:
	BATON_API_BASE_URL=http://localhost:8000 \
	BATON_MCP_DEBUG=1 BATON_DEV_PROXY=1 \
	BATON_MCP_PORT=$(BATON_MCP_PORT) \
	$(BIN)/python -m baton_mcp

prod:
	BATON_API_BASE_URL=$(BATON_PROD_CONSOLE_URL) \
	BATON_MCP_DEBUG=1 BATON_DEV_PROXY=1 \
	BATON_MCP_PORT=$(BATON_PROD_PORT) \
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
