"""Tests for the dev-only proxy: URL pass-through, header pass-through, gating."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from baton_mcp import __version__
from baton_mcp.dev_proxy import create_dev_app, install_dev_proxy
from baton_mcp.server import build_mcp

console_seen: dict = {}


@pytest.fixture(autouse=True)
def _fresh_console():
    console_seen.clear()
    yield


def _console_app() -> Starlette:
    async def echo(request):
        console_seen.update(
            method=request.method,
            path=request.url.path,
            auth=request.headers.get("authorization"),
            tenant=request.headers.get("x-baton-tenant-id"),
        )
        return JSONResponse(
            {"page": request.url.path, "tenant": request.headers.get("x-baton-tenant-id")}
        )

    return Starlette(routes=[Route("/", echo), Route("/{rest:path}", echo)])


def _fixture_console_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_console_app()),
        base_url="http://console.local",
    )


def _proxied_app(fixture: httpx.AsyncClient | None = None):
    mcp = build_mcp()
    install_dev_proxy(mcp, "http://console.local", client=fixture)
    return mcp.http_app()


def test_non_mcp_urls_reach_the_console_with_credentials_intact():
    with TestClient(_proxied_app(_fixture_console_client())) as client:
        resp = client.get(
            "/dashboard/things?x=1",
            headers={
                "Authorization": "Bearer sk-test",
                "X-Baton-Tenant-Id": "tenant-1",
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"page": "/dashboard/things", "tenant": "tenant-1"}
    # The workspace credential rode through untouched; the method did too
    # (query params forwarded separately, not folded into the path).
    assert console_seen["auth"] == "Bearer sk-test"
    assert console_seen["method"] == "GET"
    assert console_seen["path"] == "/dashboard/things"


def test_our_own_surface_is_not_proxied():
    with TestClient(_proxied_app(_fixture_console_client())) as client:
        assert client.get("/health").json() == {"status": "ok", "version": __version__}
        # /health and the MCP endpoint answered, so the catch-all shadowed neither.
        # /mcp/ goes through the re-created redirect to the exact-path endpoint.
        mc = client.post("/mcp/", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
        assert mc.status_code == 406  # MCP endpoint, not the proxy
        assert mc.json()["jsonrpc"] == "2.0"
        assert console_seen == {}


def test_console_down_is_a_502_not_a_crash():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("refused")

    down = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    with TestClient(_proxied_app(down)) as client:
        resp = client.get("/some/page")
        assert resp.status_code == 502
        assert "console unreachable" in resp.text


def test_no_env_no_proxy():
    """Absent BATON_DEV_PROXY: a plain server, no catch-all at all."""
    with TestClient(build_mcp().http_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/dashboard/things").status_code == 404


def test_factory_requires_the_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BATON_DEV_PROXY", raising=False)
    monkeypatch.delenv("BATON_API_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="BATON_DEV_PROXY"):
        create_dev_app()


def test_factory_builds_proxied_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BATON_DEV_PROXY", "1")
    monkeypatch.setenv("BATON_API_BASE_URL", "http://console.local")
    monkeypatch.setattr(
        "baton_mcp.dev_proxy._console_client", lambda target: _fixture_console_client()
    )
    with TestClient(create_dev_app()) as client:
        resp = client.get("/anything")
    assert resp.json()["page"] == "/anything"
