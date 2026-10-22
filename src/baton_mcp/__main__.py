"""Entry point: serve the metrics tools over Streamable HTTP (remote-first).

With ``BATON_DEV_PROXY=1``, every non-MCP URL is dev-proxied to the console
named by ``BATON_API_BASE_URL`` (see baton_mcp/dev_proxy.py) — dev only, no
prod path reaches this branch.
"""

from __future__ import annotations

import os

from baton_mcp.server import build_mcp


def main() -> None:
    host = os.environ.get("BATON_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("BATON_MCP_PORT", "8000"))

    if os.environ.get("BATON_DEV_PROXY", "").lower() in {"1", "true", "yes", "on"}:
        import uvicorn

        from baton_mcp.dev_proxy import create_dev_app

        app = create_dev_app()
        uvicorn.run(app, host=host, port=port)
        return

    mcp = build_mcp()
    mcp.run(
        transport="http",
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
