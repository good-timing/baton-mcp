"""Tests for the HTTP surface: /health alongside the /mcp/ MCP endpoint."""

from __future__ import annotations

import json

import pytest
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


def _metrics_param_names(spec):
    return {
        path: [p["name"] for op in ops.values() for p in op.get("parameters", [])]
        for path, ops in spec["paths"].items()
        if path.startswith("/v0/metrics/")
    }


def test_fetch_spec_strips_include_facet():
    spec = _fetch_spec()
    assert spec is not None
    for path, names in _metrics_param_names(spec).items():
        assert "include" not in names, path


def test_fetch_spec_rejects_non_object_json(tmp_path, monkeypatch):
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text("[]")
    monkeypatch.setattr("baton_mcp.server.SPEC_PATH", spec_path)
    with pytest.raises(RuntimeError, match="is not a JSON object"):
        _fetch_spec()


def test_source_spec_has_include_and_vendored_spec_does_not():
    source = _metrics_param_names(json.loads(SOURCE_PATH.read_text()))
    vendored = _metrics_param_names(json.loads(SPEC_PATH.read_text()))
    assert source, "expected metrics paths in the source spec"
    for path, names in source.items():
        assert "include" in names, path
    for path, names in vendored.items():
        assert "include" not in names, path
