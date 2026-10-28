"""Tests for the HTTP surface: /health alongside the /mcp/ MCP endpoint."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from baton_mcp import __version__
from baton_mcp.server import SPEC_PATH, _fetch_spec, build_mcp

SOURCE_PATH = SPEC_PATH.with_name("source.openapi.json")


def _client() -> TestClient:
    return TestClient(build_mcp().http_app())


def test_health_serves_at_root():
    with _client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "version": __version__}


def test_mcp_endpoint_still_serves_alongside_health():
    with _client() as client:
        resp = client.post("/mcp/", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
        assert resp.status_code == 406
        assert resp.json()["jsonrpc"] == "2.0"


def test_fetch_spec_loads_vendored_file():
    spec = _fetch_spec()
    assert spec is not None
    assert "/v0/metrics/demand_intents" in spec["paths"]


def test_fetch_spec_strips_include_facet():
    spec = _fetch_spec()
    assert spec is not None
    for path, ops in spec["paths"].items():
        if not path.startswith("/v0/metrics/"):
            continue
        params = [p["name"] for op in ops.values() for p in op.get("parameters", [])]
        assert "include" not in params, path


def test_vendored_spec_is_already_overlay_patched():
    spec = json.loads(SPEC_PATH.read_text())
    for path, ops in spec["paths"].items():
        if not path.startswith("/v0/metrics/"):
            continue
        params = [p["name"] for op in ops.values() for p in op.get("parameters", [])]
        assert "include" not in params, path


def test_source_spec_keeps_include_for_the_overlay():
    spec = json.loads(SOURCE_PATH.read_text())
    for path, ops in spec["paths"].items():
        if not path.startswith("/v0/metrics/"):
            continue
        params = [p["name"] for op in ops.values() for p in op.get("parameters", [])]
        assert "include" in params, path
