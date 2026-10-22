"""HTTP client for the Baton metrics API — the whole data plane of baton-mcp.

One request per tool call: ``GET {base}/v0/metrics/{answer_type}`` with the
workspace credential passed through and the facets as query params, exactly
as the console's JSON adapter (``metrics/routes.py``) defines them:

- The **Authorization header travels through untouched** — baton-mcp never
  inspects, transforms, or stores the workspace token. It is the same bearer
  the owner would send to the API with curl.
- The tenant auth key rides in the ``X-Baton-Tenant-Id`` header end to end
  (the console's MCP adapter reads it from the transport; the JSON API takes
  it as a query param, which is what we send it as).
- HTTP error statuses map onto :class:`ToolError` so the message reaches the
  calling agent: 401/403 auth, 422 bad facets, anything else surfaced as-is.
"""

from __future__ import annotations

import logging
import os
import sys

import httpx
from fastmcp.exceptions import ToolError

from baton_mcp.config import TENANT_HEADER
from baton_mcp.types import AgentAnswer, AgentAnswerRow

logger = logging.getLogger("baton_mcp.client")
if os.environ.get("BATON_MCP_DEBUG"):
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        _handler = logging.StreamHandler(sys.stderr)
        _handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(_handler)

# answer_type -> required facet. The four types the API ships (routes.py);
# the mapping lives here so the catalog change is one place.
ANSWER_TYPES: dict[str, tuple[str, ...]] = {
    "top_friction_by_tool": ("vendor_id",),
    "top_gaps_clustered": ("vendor_id",),
    "failure_modes_for_tool": ("vendor_id", "tool_name"),
    "demand_intents": ("vendor_id",),
}


class BatonApiError(ToolError):
    """A Baton API failure, message intact for the calling agent."""


def project_answer(payload: dict) -> AgentAnswer:  # type: ignore[type-arg]
    """Full ``Answer`` JSON -> lean ``AgentAnswer`` (drops the audit trail)."""
    return AgentAnswer(
        answer_type=payload["answer_type"],
        headline=payload["headline"],
        rows=[AgentAnswerRow(label=row["label"], value=row["value"]) for row in payload["rows"]],
        n_signals=payload["coverage"]["n_signals"],
        n_sessions=payload["coverage"]["n_sessions"],
        embedding_available=payload["coverage"]["embedding_available"],
        computed_at=payload["computed_at"],
    )


async def answer_for(
    base_url: str,
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_id: str | None,
    answer_type: str,
    vendor_id: str,
    tool_name: str | None = None,
    window_days: int | None = None,
    signal_type: str | None = None,
) -> AgentAnswer:
    """Auth check -> one API call -> lean answer. Header-free so it is
    directly testable (tool wrappers read the transport headers and come here)."""
    if answer_type not in ANSWER_TYPES:
        raise BatonApiError(f"unknown answer_type {answer_type!r}")
    if not authorization:
        raise BatonApiError("missing Authorization header (workspace API key bearer)")
    if not tenant_id:
        raise BatonApiError(f"missing {TENANT_HEADER} header")

    params: dict[str, str | int] = {"tenant_id": tenant_id, "vendor_id": vendor_id}
    if tool_name is not None:
        params["tool_name"] = tool_name
    if window_days is not None:
        params["window_days"] = window_days
    if signal_type is not None:
        params["signal_type"] = signal_type

    if os.environ.get("BATON_MCP_DEBUG"):
        logger.debug(
            "baton-mcp -> %s/v0/metrics/%s tenant=%s params=%s",
            base_url,
            answer_type,
            tenant_id,
            params,
        )

    try:
        resp = await client.get(
            f"{base_url}/v0/metrics/{answer_type}",
            params=params,
            headers={"Authorization": authorization},
        )
    except httpx.HTTPError as e:
        raise BatonApiError(f"baton api unreachable: {e}") from e

    if resp.status_code in (401, 403):
        raise BatonApiError(f"auth failed: {_detail(resp)}")
    if resp.status_code == 422:
        raise BatonApiError(f"bad facets: {_detail(resp)}")
    if resp.is_error:
        raise BatonApiError(f"baton api error (HTTP {resp.status_code}): {_detail(resp)}")

    return project_answer(resp.json())


def _detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = None
    return str(detail) if detail else resp.text or "no detail"
