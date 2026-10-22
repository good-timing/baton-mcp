"""Tests for the API client: token pass-through, projection, error mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastmcp.exceptions import ToolError

from baton_mcp.client import answer_for, project_answer

ANSWER = {
    "answer_type": "top_friction_by_tool",
    "headline": "h",
    "rows": [
        {"label": "get_weather", "value": 3, "signal_ids": ["11111111-1111-1111-1111-111111111111"]}
    ],
    "facets_applied": {"vendor_id": "acme"},
    "source_signal_ids": ["11111111-1111-1111-1111-111111111111"],
    "coverage": {"n_signals": 5, "n_sessions": 4, "embedding_available": True},
    "computed_at": "2026-10-22T00:00:00Z",
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_token_passes_through_and_projection_drops_ids():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=ANSWER)

    got = await answer_for(
        "https://api.test",
        _client(handler),
        authorization="Bearer sk-workspace-token",
        tenant_id="tenant-key",
        answer_type="top_friction_by_tool",
        vendor_id="acme",
        window_days=7,
        signal_type="failure",
    )

    # The workspace token travels through untouched.
    assert seen["auth"] == "Bearer sk-workspace-token"
    # The JSON API takes the tenant auth key as a query param (routes.py).
    assert seen["params"]["tenant_id"] == "tenant-key"
    assert seen["params"]["vendor_id"] == "acme"
    assert seen["params"]["window_days"] == "7"
    assert seen["params"]["signal_type"] == "failure"
    # Lean projection: no audit trail reaches the agent.
    assert got.model_dump() == {
        "answer_type": "top_friction_by_tool",
        "headline": "h",
        "rows": [{"label": "get_weather", "value": 3}],
        "n_signals": 5,
        "n_sessions": 4,
        "embedding_available": True,
        "computed_at": datetime(2026, 10, 22, tzinfo=UTC),
    }


@pytest.mark.parametrize(
    ("status", "prefix"),
    [(401, "auth failed"), (403, "auth failed"), (422, "bad facets"), (500, "baton api error")],
)
async def test_error_statuses_become_tool_errors(status, prefix):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "boom"})

    with pytest.raises(ToolError, match=prefix):
        await answer_for(
            "https://api.test",
            _client(handler),
            authorization="Bearer t",
            tenant_id="k",
            answer_type="demand_intents",
            vendor_id="acme",
        )


async def test_missing_credentials_rejected_before_any_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls.append(request)
        return httpx.Response(200, json=ANSWER)

    with pytest.raises(ToolError, match="Authorization"):
        await answer_for(
            "https://api.test",
            _client(handler),
            authorization=None,
            tenant_id="k",
            answer_type="demand_intents",
            vendor_id="acme",
        )
    with pytest.raises(ToolError, match="x-baton-tenant-id"):
        await answer_for(
            "https://api.test",
            _client(handler),
            authorization="Bearer t",
            tenant_id=None,
            answer_type="demand_intents",
            vendor_id="acme",
        )
    assert calls == []


async def test_project_answer_rejects_unexpected_shape():
    with pytest.raises((KeyError, TypeError, json.JSONDecodeError)):
        project_answer({})
