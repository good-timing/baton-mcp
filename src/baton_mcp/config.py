"""Configuration: where the Baton API lives.

The MCP server is a pure client of the public HTTP API — it never reads the
database and imports nothing from ``baton_console`` (see plan/proposal.md).
The one thing it must know is the API base URL, supplied via env so the same
image runs against beta and prod.
"""

from __future__ import annotations

import os

# Tenant auth key travels in this transport header, mirroring the console's
# ingest/auth.py TENANT_HEADER so the two ends cannot drift apart. Spelled here
# (not imported) because baton-mcp depends only on the HTTP surface.
TENANT_HEADER = "x-baton-tenant-id"

DEFAULT_API_BASE_URL = "https://baton.goodtiming.ai"


def api_base_url() -> str:
    """Baton API origin, from ``BATON_API_BASE_URL`` (no trailing slash).

    Falls back to the prod host so a bare `baton-mcp` run points somewhere
    real; tests and self-hosters override it.
    """
    return os.environ.get("BATON_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
