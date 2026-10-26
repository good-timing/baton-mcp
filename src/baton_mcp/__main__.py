"""Entry point: serve the metrics tools over Streamable HTTP (remote-first)."""

from __future__ import annotations

import os

from baton_mcp.server import build_mcp


def main() -> None:
    mcp = build_mcp()
    mcp.run(
        transport="http",
        host=os.environ.get("BATON_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("BATON_MCP_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
