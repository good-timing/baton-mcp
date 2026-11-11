"""MCP server built from the Console's OpenAPI spec.

This server is generated from the Console's OpenAPI document at
``/openapi.json`` using ``FastMCP.from_openapi``. Only routes under
``/v0/metrics/`` are exposed; everything else (ingest, auth, …) is excluded
via a ``RouteMap``.

Auth mirrors the Console's JSON adapter: the workspace credential travels in
the **transport headers** (Bearer token + ``X-Baton-Tenant-Id``), never the
tool schema. Because ``from_openapi`` shares one ``httpx.AsyncClient`` across
all generated tools, per-request auth is injected by a custom transport that
reads the active MCP HTTP request (``get_http_request``) at call time — the
same context the generated tool handlers run in.

The OpenAPI spec is vendored inside the package (``baton_mcp/openapi.json``,
refreshed from a local console via ``make refresh-openapi``), so the server
never depends on a live console being reachable — including in prod, where the
console disables its docs endpoint. ``make refresh-openapi`` applies
``overlay.json`` and writes the result there. If the file is missing or
corrupt, the server fails to start rather than serving no tools.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.providers.openapi import MCPType, RouteMap
from starlette.responses import JSONResponse

from baton_mcp import __version__
from baton_mcp.config import TENANT_HEADER, WORKSPACE_RE, api_base_url

if TYPE_CHECKING:
    from baton import PrincipalResolutionContext, ResolvePrincipalHook

# Per-request timeout for upstream Console API calls. Hardcoded (not env-driven)
# to keep the surface small; bump here if a metrics query needs more room.
API_TIMEOUT = 30.0

# The vendored spec lives inside the package, so it ships with any wheel /
# installed copying of baton_mcp (not just repository checkouts).
SPEC_PATH = Path(__file__).resolve().parent / "openapi.json"


class _AuthInjectingTransport(httpx.AsyncHTTPTransport):
    """Inject per-request auth headers into every upstream call.

    ``from_openapi`` shares one ``httpx.AsyncClient`` across all generated
    tools, so the client's headers are fixed at construction. This transport
    runs inside the same async task as the generated tool handler, where
    ``get_http_request()`` returns the active MCP HTTP request — so we can
    pull the bearer token and tenant id from the transport headers and add
    them to the outgoing request at call time.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            mcp_request = get_http_request()
            auth = mcp_request.headers.get("authorization")
            tenant = mcp_request.headers.get(TENANT_HEADER)
            if auth:
                request.headers["Authorization"] = auth
            if tenant:
                request.headers[TENANT_HEADER] = tenant
        except RuntimeError:
            # No active MCP request (startup, tests, non-HTTP context) — pass
            # through without auth; the upstream will 401, which is correct.
            pass
        if os.environ.get("BATON_MCP_DEBUG"):
            _debug_upstream_requests(request)
        return await super().handle_async_request(request)


_debug_handler_installed = False


def _debug_upstream_requests(request: httpx.Request) -> None:
    """Install (once) a stderr handler and emit one line per upstream call.

    The flag-gated level dance and handler belong at setup time, not per
    request — a bare ``logger.debug`` gets dropped without a handler, because
    a handlerless logger propagates to root, and root's lastResort only emits
    WARNING and above.
    """
    global _debug_handler_installed
    if not _debug_handler_installed:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.propagate = False
        _debug_handler_installed = True
    logging.getLogger(__name__).debug("baton-mcp -> %s %s", request.method, request.url)


def _fetch_spec() -> dict[str, object]:
    """Load the OpenAPI spec vendored inside the package.

    The spec ships with the package (compile-time, not startup-fetched), so
    the server works identically in dev, CI and prod where the console
    disables its ``/openapi.json`` endpoint. The overlay is applied when the
    spec is refreshed, not here.

    Raises ``RuntimeError`` when the file is missing or unreadable: a server
    with no tools must not start and look healthy.
    """
    try:
        raw = SPEC_PATH.read_text()
    except OSError as e:
        raise RuntimeError(f"baton-mcp OpenAPI spec not readable at {SPEC_PATH}: {e}") from e
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"baton-mcp OpenAPI spec at {SPEC_PATH} is not valid JSON: {e}") from e
    if not isinstance(spec, dict):
        raise RuntimeError(f"baton-mcp OpenAPI spec at {SPEC_PATH} is not a JSON object")
    return spec


def build_mcp() -> FastMCP:
    """Construct the metrics MCP server from the Console's OpenAPI spec.

    Only ``/v0/metrics/*`` routes are exposed. Self-instrumentation via
    baton-sdk registers middleware over the underlying MCP server, so it
    captures the generated tools like any other.
    """
    base_url = api_base_url()
    spec = _fetch_spec()

    transport = _AuthInjectingTransport()
    client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=API_TIMEOUT)

    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="baton-mcp",
        route_maps=[
            # Only metrics routes become tools.
            RouteMap(methods=["GET"], pattern=r"^/v0/metrics/", mcp_type=MCPType.TOOL),
            # Everything else (ingest, auth, UI, …) is dropped.
            RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
        ],
    )

    _instrument(mcp)
    _add_health(mcp)
    return mcp


def _add_health(mcp: FastMCP) -> None:
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request) -> JSONResponse:  # type: ignore[no-untyped-def]
        return JSONResponse({"status": "ok", "version": __version__})


LABELS_ENV = "BATON_MCP_LABELS"

_instrument_logger = logging.getLogger("baton_mcp.instrument")


def _parse_labels(raw: str) -> dict[str, tuple[str, ...]]:
    """Parse ``ten_a:internal,ten_a:beta,ten_b:beta`` into labels per workspace.

    Malformed entries are skipped, not raised: ``_instrument`` turns any
    exception into "telemetry off".
    """
    labels: dict[str, list[str]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        workspace, sep, label = (part.strip() for part in entry.partition(":"))
        if not sep or not workspace or not label:
            _instrument_logger.warning("%s: skipping malformed entry %r", LABELS_ENV, entry)
            continue
        labels.setdefault(workspace, []).append(label)
    return {workspace: tuple(names) for workspace, names in labels.items()}


def _make_principal_resolver(labels: dict[str, tuple[str, ...]]) -> ResolvePrincipalHook:
    """Name the caller by workspace, from the tenant header.

    The header is caller-supplied, so anything not shaped like a workspace id
    resolves to None rather than becoming an unbounded organization id.

    Never derives anything from ``Authorization``: the bearer is the caller's
    secret (``test_resolver_ignores_authorization``).
    """
    from baton import Organization

    def resolve(context: PrincipalResolutionContext) -> Organization | None:
        tenant = (context.headers or {}).get(TENANT_HEADER) or ""
        if not WORKSPACE_RE.fullmatch(tenant):
            return None
        return Organization(organization_id=tenant, labels=labels.get(tenant, ()))

    return resolve


def _instrument(mcp: FastMCP) -> None:
    """Self-instrumentation via baton-sdk. Always on."""
    dsn = os.environ.get("BATON_DSN", "").strip()
    try:
        from baton.integrations.standalone import VendorConfig, install_baton
        from baton.sinks import StdoutSink

        resolve_principal = _make_principal_resolver(_parse_labels(os.environ.get(LABELS_ENV, "")))
        config = (
            VendorConfig(dsn=dsn, settings="console", resolve_principal=resolve_principal)
            if dsn
            else VendorConfig(
                vendor_id="baton-mcp",
                vendor_display_name="Baton MCP",
                sink=StdoutSink(),
                resolve_principal=resolve_principal,
            )
        )
        install_baton(mcp, config)
        _instrument_logger.info("baton-mcp self-instrumentation enabled")
    except Exception as e:  # never take the server down over telemetry
        _instrument_logger.warning("baton-mcp self-instrumentation skipped: %s", e)
