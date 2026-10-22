"""Dev-only reverse proxy: one local origin serves baton-mcp AND the console.

Only the MCP tools (`/mcp/`) and the healthcheck (`/health`) are ours; every
other URL is forwarded to a locally running baton-console. The point is to
exercise the two ends on one origin during development — e.g. the tool paths
running with the console's real landing/signup pages beside them — without
any infra work.

Gate: **env, not code.** `BATON_DEV_PROXY=1` turns the catch-all on;
unset = plain server with nothing extra listening. Never to be enabled in
prod, where there is exactly one thing behind the domain mapping.

The upstream target is `BATON_API_BASE_URL` — the SAME value the data plane
uses. The API and the proxy always point at the same console, so there is one
knob, not two (no separate `BATON_DEV_CONSOLE_URL`).

Console in one shell:
    make dev                     # from baton-console/  (uvicorn :8000)
baton-mcp in the next:
    make dev                     # :8010 serves both, data plane + proxy -> :8000
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp

from baton_mcp.config import api_base_url
from baton_mcp.server import build_mcp

# Headers about THIS hop (proxy-to-console), not the request itself — dropped
# either because the httpx client computes its own value or because RFC 9110
# makes them hop-by-hop. Everything else, critically Authorization and the
# tenant header, passes through untouched.
_HOP_DROP = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authorization",
    "proxy-authenticate",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "accept-encoding",
}

# The catch-all's methods: anything a browser or curl might send at the
# console. HEAD is automatic (Starlette adds it for GET routes).
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _proxy(request: Request, client: httpx.AsyncClient) -> Response:
    # The MCP route is exact-path "/mcp"; Starlette's trailing-slash redirect
    # would fix "/mcp/" — except the catch-all matches first. Re-create that
    # redirect here: 307 preserves the method, so e.g. POST /mcp/ still lands
    # on the MCP endpoint rather than the console's 405.
    if request.url.path == "/mcp/":
        return RedirectResponse("/mcp", status_code=307)

    body = await request.body()
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _HOP_DROP]
    try:
        upstream = await client.request(
            request.method,
            request.url.path,
            params=request.query_params,
            headers=headers,
            content=body if body else None,
        )
    except httpx.HTTPError as e:
        return Response(f"dev proxy: console unreachable: {e}", status_code=502)

    passthrough = dict(
        (k, v) for k, v in upstream.headers.multi_items() if k.lower() not in _HOP_DROP
    )
    return Response(
        content=upstream.read(),
        status_code=upstream.status_code,
        headers=passthrough,
    )


def _console_client(target: str) -> httpx.AsyncClient:
    """The upstream client (module-level so tests can inject a fixture)."""
    return httpx.AsyncClient(base_url=target)


def install_dev_proxy(
    mcp: FastMCP,
    target: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Add a catch-all route forwarding every URL the MCP server does not own.

    Registered via ``custom_route`` — fastmcp appends those AFTER the MCP and
    health routes, so the catch-all sits at the end of the match order and
    cannot shadow anything, including ``/health``. Injectable ``client`` is
    for tests (ASGITransport against a fixture app); unrestricted, it points
    at the locally running console.
    """
    http = client or _console_client(target)

    async def proxy(request: Request) -> Response:
        return await _proxy(request, http)

    mcp.custom_route("/{rest:path}", methods=_PROXY_METHODS)(proxy)


def create_dev_app() -> ASGIApp:
    """ASGI app factory (uvicorn --factory) with the dev proxy wired on."""
    if os.environ.get("BATON_DEV_PROXY", "").lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "BATON_DEV_PROXY must be set (e.g. BATON_DEV_PROXY=1): the dev "
            "proxy is opt-in, and its upstream target is BATON_API_BASE_URL."
        )
    target = api_base_url()
    mcp = build_mcp()
    install_dev_proxy(mcp, target)
    print(f"baton-mcp dev proxy: non-MCP URLs -> {target}")  # noqa: T201
    # FastMCP is not itself an ASGI callable — the Starlette app (carrying the
    # MCP route, /health, and the catch-all) is what uvicorn serves.
    return mcp.http_app()
