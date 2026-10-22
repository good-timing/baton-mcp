"""Tests for the HTTP surface: /mcp/health alongside the /mcp/ MCP endpoint."""

from __future__ import annotations

from starlette.testclient import TestClient

from baton_mcp import __version__
from baton_mcp.server import build_mcp


def _client() -> TestClient:
    return TestClient(build_mcp().http_app())


def test_health_serves_at_root():
    with _client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "version": __version__}


def test_mcp_endpoint_still_serves_alongside_health():
    """The custom route must not shadow (or be shadowed by) the MCP endpoint.

    406 rather than 404: the route exists and answered, rejecting a request
    that is not a valid MCP session handshake — the expected shape for a
    non-protocol POST against the endpoint.
    """
    with _client() as client:
        resp = client.post("/mcp/", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
        assert resp.status_code == 406
        assert resp.json()["jsonrpc"] == "2.0"
