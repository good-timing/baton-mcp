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
- **Token thrift:** the full API `Answer` carries a per-row `signal_ids` audit
  trail; the MCP tools project it down to headline + ranked rows + coverage
  counts.

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
| `BATON_MCP_HOST` / `BATON_MCP_PORT` | `0.0.0.0` / `8000` | Listen address |
| `BATON_API_TIMEOUT` | `30` | API call timeout, seconds |

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

## Dev proxy

`BATON_DEV_PROXY=1` turns on a **dev-only** catch-all: every URL the MCP
server does not own is reverse-proxied to the console named by
`BATON_API_BASE_URL`, so both ends live on one origin during development.
Headers pass through untouched (Authorization, `X-Baton-Tenant-Id`); hop-by-hop
headers are dropped. The API and the proxy always use the same URL — there is
one knob, not two.

- `make dev` — console on `:8000` (`make dev` in `baton-console/`), baton-mcp
  on `:8010`, both data plane and proxy -> `:8000`.
- `make prod` — proxies to the **real** console (`baton.goodtiming.ai`), so
  the MCP tools return real answers and any console page you open through it
  acts on prod data with real credentials. Port `:8011`.

Unset means a plain server; there is no prod path to it.

Point a client at it:

```sh
claude mcp add --transport http baton https://mcp.goodtiming.ai \
  --header "Authorization: Bearer $BATON_API_KEY" \
  --header "X-Baton-Tenant-Id: $BATON_TENANT_ID"
```

## Development

Needs [uv](https://docs.astral.sh/uv/) — it builds the venv from the committed
`uv.lock` and supplies the interpreter, so a system Python is not a prerequisite.

```sh
make install    # installs in .venv, from uv.lock
make test       # pytest
make ci         # lint + format-check + typecheck + test
make dev        # dev proxy: serve on :8010, forward non-MCP URLs to a locally
                # running console on :8000 (`make dev` in baton-console/)
make prod       # proxy non-MCP URLs to the REAL console — see the warning
```

After changing a dependency, run `uv lock` here and commit the lock.

## License

Apache-2.0 — see [LICENSE](LICENSE).
