# baton-mcp

Open-source MCP server exposing Baton answers to an owner's agent. It is a
**thin client of the Baton HTTP API** — it never reads the database and imports
nothing from `baton-console` — the same as any customer integration.

Ships the initial four metrics tools (one per catalog answer-type), ported from
the console's metrics MCP adapter; the tool surface is identical, the data
plane is the public `/v0/metrics` JSON API.

- **Transport:** MCP over Streamable HTTP (remote-first; no local transports).
- **Auth:** the workspace credential travels in the transport headers —
  `Authorization: Bearer <workspace API key>` + `X-Baton-Tenant-Id` — never in
  the tool schema. The token is passed through to the Baton API untouched.

## Tools

| Tool | Facets |
| --- | --- |
| `top_friction_by_tool` | `vendor_id`, `window_days?`, `signal_type?` |
| `top_gaps_clustered` | `vendor_id`, `window_days?` |
| `failure_modes_for_tool` | `vendor_id`, `tool_name`, `window_days?` |
| `demand_intents` | `vendor_id`, `window_days?` |

## Configuration

| Env | Default | Meaning |
| --- | --- | --- |
| `BATON_API_BASE_URL` | `https://baton.goodtiming.ai` | Baton API origin |
| `BATON_MCP_HOST` / `BATON_MCP_PORT` | `::` (dual-stack) / `8000` | Listen address |

## Running

```sh
make install
uv run baton-mcp   # serves MCP on http://0.0.0.0:8000/mcp/
```

Two HTTP surfaces on one port:

- `/mcp` — the MCP Streamable HTTP endpoint (the path is fastmcp's default,
  not defined in this repo).
- `/health` — liveness probe: `{"status": "ok", "version": ...}`. It does
  **not** ping the Baton API, on purpose: a probe that fans out an upstream
  call per poll turns a console blip into this service flapping too.

Point a client at it:


```sh
claude mcp add --transport http baton https://mcp.goodtiming.ai/mcp \
  --header "Authorization: Bearer $BATON_API_KEY" \
  --header "X-Baton-Tenant-Id: $BATON_TENANT_ID"
```

## Development

Needs [uv](https://docs.astral.sh/uv/) — it builds the venv from the committed
`uv.lock` and supplies the interpreter, so a system Python is not a prerequisite.

```sh
make install    # installs in .venv, from uv.lock
make test       # pytest
make ci         # lint + format-check + typecheck + test + spec freshness
make dev        # local dev: serve on :8010, MCP tools call local baton-console
make live-dev   # dev with live prod data, MCP tools call prod API
```

After changing a dependency, run `uv lock` here and commit the lock.

## License

Apache-2.0 — see [LICENSE](LICENSE).
