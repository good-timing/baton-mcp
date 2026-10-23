"""The baton-mcp server: four metrics tools over the Baton HTTP API.

The tool surface is copied 1:1 from the console's metrics MCP adapter
(``baton-console/backend/src/baton_console/metrics/mcp.py``) — same names,
same docstrings, same facets — because the initial four answer-types are the
same catalog. The data plane differs: each call goes to the public
``/v0/metrics`` JSON API (``metrics/routes.py``) with the workspace credential
passed through, so this process never reads the database or imports console
internals. It is a client of the API, the same as any customer integration.

Auth mirrors the console adapter exactly: the workspace credential travels in
the **transport headers** (Authorization bearer + ``X-Baton-Tenant-Id``), never
the tool schema — so the agent chooses only *facets* (``vendor_id``, window,
...).
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from starlette.responses import JSONResponse

from baton_mcp import __version__
from baton_mcp.client import BatonApiError, answer_for
from baton_mcp.config import TENANT_HEADER, api_base_url
from baton_mcp.types import AgentAnswer


def _instrument(mcp: FastMCP) -> None:
    """Opt-in self-instrumentation via baton-sdk. No-op when unconfigured."""
    import logging

    logger = logging.getLogger("baton_mcp.instrument")
    dsn = os.environ.get("BATON_DSN", "").strip()
    instrument = os.environ.get("BATON_INSTRUMENT", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not dsn and not instrument:
        return
    try:
        from baton.integrations.standalone import VendorConfig, install_baton
        from baton.sinks import StdoutSink

        if dsn:
            install_baton(mcp, dsn=dsn)
        else:
            install_baton(
                mcp,
                VendorConfig(
                    vendor_id="baton-mcp",
                    vendor_display_name="Baton MCP",
                    sink=StdoutSink(),
                ),
            )
        logger.info("baton-mcp self-instrumentation enabled")
    except Exception as e:  # never take the server down over telemetry
        logger.warning("baton-mcp self-instrumentation skipped: %s", e)


def _transport() -> tuple[str | None, str | None]:
    req = get_http_request()
    return req.headers.get("authorization"), req.headers.get(TENANT_HEADER)


def build_mcp() -> FastMCP:
    """Construct the metrics MCP server (one tool per answer-type)."""
    mcp: FastMCP = FastMCP("baton-mcp", version=__version__)

    # Self-instrumentation: wrap every tool registered below so calls to them
    # emit Baton friction events, the same way a customer's wrapped server
    # does. Opt-in via BATON_DSN (a packed DSN from /account) or, for local
    # dev, BATON_INSTRUMENT=1 (StdoutSink). With neither, install is skipped
    # and the server behaves exactly as if this call were absent. Wrapped in
    # try/except so a misconfigured DSN can never take the server down.
    _instrument(mcp)

    # Liveness probe. Deliberately NOT a Baton API reachability check: a probe
    # that fans out an upstream call per poll turns a console blip into this
    # service flapping too (and Cloud Run min-instances pays for it). This
    # answers "is the process serving", which is what a healthcheck is for.
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request) -> JSONResponse:  # type: ignore[no-untyped-def]
        return JSONResponse({"status": "ok", "version": __version__})

    @mcp.tool()
    async def top_friction_by_tool(
        vendor_id: str,
        window_days: int | None = None,
        signal_type: str | None = None,
    ) -> AgentAnswer:
        """Top friction on a vendor surface, ranked by distinct sessions per tool.

        vendor_id: the vendor surface to ask about. window_days: days back on
        event time (omit for all-time). signal_type: narrow to one type (e.g.
        'failure').
        """
        authorization, tenant_id = _transport()
        return await answer_tool(
            authorization,
            tenant_id,
            answer_type="top_friction_by_tool",
            vendor_id=vendor_id,
            window_days=window_days,
            signal_type=signal_type,
        )

    @mcp.tool()
    async def top_gaps_clustered(
        vendor_id: str,
        window_days: int | None = None,
    ) -> AgentAnswer:
        """Capability gaps agents ask a vendor to build, semantically clustered."""
        authorization, tenant_id = _transport()
        return await answer_tool(
            authorization,
            tenant_id,
            answer_type="top_gaps_clustered",
            vendor_id=vendor_id,
            window_days=window_days,
        )

    @mcp.tool()
    async def failure_modes_for_tool(
        vendor_id: str,
        tool_name: str,
        window_days: int | None = None,
    ) -> AgentAnswer:
        """Distinct ways agents have trouble with one tool on a vendor surface, including
        reports where they picked another tool when this one does the job, semantically
        clustered."""
        authorization, tenant_id = _transport()
        return await answer_tool(
            authorization,
            tenant_id,
            answer_type="failure_modes_for_tool",
            vendor_id=vendor_id,
            tool_name=tool_name,
            window_days=window_days,
        )

    @mcp.tool()
    async def demand_intents(
        vendor_id: str,
        window_days: int | None = None,
    ) -> AgentAnswer:
        """What agents arrive to do on a vendor surface, ranked by distinct sessions."""
        authorization, tenant_id = _transport()
        return await answer_tool(
            authorization,
            tenant_id,
            answer_type="demand_intents",
            vendor_id=vendor_id,
            window_days=window_days,
        )

    return mcp


async def answer_tool(
    authorization: str | None,
    tenant_id: str | None,
    *,
    answer_type: str,
    vendor_id: str,
    tool_name: str | None = None,
    window_days: int | None = None,
    signal_type: str | None = None,
) -> AgentAnswer:
    """Shared tool body: one API call, API failures surfaced as ToolError.

    Split out of the tool wrappers so they stay one-liners like the console's
    do, and so tests can drive ``answer_for`` without the FastMCP layer. The
    API validates the facet combination per answer-type (422), so passing an
    inapplicable facet is an error at the source, not here.
    """
    base = api_base_url()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(float(os.environ.get("BATON_API_TIMEOUT", "30"))),
    ) as client:
        try:
            return await answer_for(
                base,
                client,
                authorization=authorization,
                tenant_id=tenant_id,
                answer_type=answer_type,
                vendor_id=vendor_id,
                tool_name=tool_name,
                window_days=window_days,
                signal_type=signal_type,
            )
        except BatonApiError as e:
            raise ToolError(str(e)) from e
