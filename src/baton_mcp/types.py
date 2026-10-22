"""The agent-facing answer shape — ported from the console's metrics/mcp.py.

The full ``Answer`` the JSON API returns carries the per-row and top-level
``signal_ids`` audit trail — right for drill-down, but on an agent-facing
tool (whose whole point is token reduction) that is a wall of opaque UUIDs
the agent can't use and pays for on every call. The MCP server projects it
down client-side: drop the ids, keep what the agent reasons over.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AgentAnswerRow(BaseModel):
    """A ranked row for the agent: the entity + its metric, no audit trail."""

    label: str
    value: int


class AgentAnswer(BaseModel):
    """The token-thrifty projection of an ``Answer`` for an agent consumer."""

    answer_type: str
    headline: str
    rows: list[AgentAnswerRow]
    n_signals: int
    n_sessions: int
    embedding_available: bool
    computed_at: datetime
