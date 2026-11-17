"""start_autopilot hands the calling agent the baton-eval steps."""

from __future__ import annotations

from fastmcp import Client

from baton_mcp.autopilot import BATON_EVAL, autopilot_steps
from baton_mcp.server import build_mcp


def test_steps_name_the_server_and_pinned_baton_eval(monkeypatch):
    monkeypatch.setenv("BATON_API_BASE_URL", "https://console.example")
    steps = autopilot_steps("srv-abc123")
    assert f"npx -y {BATON_EVAL} init --server srv-abc123 " in steps
    assert f"npx -y {BATON_EVAL} run 2> baton-eval.log" in steps
    assert "https://console.example" in steps


def test_steps_keep_the_test_key_away_from_the_agent():
    steps = autopilot_steps("srv-abc123")
    assert "Never ask for the key, read it, or pass it to a tool" in steps
    assert "BATON_EVAL_DSN" in steps
    assert "wait for their yes" in steps


async def test_tool_is_listed_and_returns_the_steps():
    async with Client(build_mcp()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "start_autopilot" in tools
        assert "vendor_id" in tools["start_autopilot"].inputSchema["required"]
        result = await client.call_tool(
            "start_autopilot", {"vendor_id": "srv-abc123", "user_goal": "improve my server"}
        )
    assert result.content[0].text == autopilot_steps("srv-abc123")
