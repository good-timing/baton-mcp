"""Refresh the vendored OpenAPI spec from a locally running baton-console.

Fetches ``/openapi.json`` from the console named by ``--base-url`` (default
``http://localhost:8000`` — start the console first, e.g. ``make dev`` there),
reduces it to exactly what ``FastMCP.from_openapi`` consumes, and writes the
result to ``src/baton_mcp/openapi.json``:

- only paths under ``/v0/metrics/`` are kept (the route maps exclude the rest,
  but vendoring a 87-path spec makes the commit and the tool source slower to
  review than it needs to be);
- agent-useless facets (``include`` etc., mirroring
  ``baton_mcp.server.AGENT_USELESS_PARAMS``) are stripped so a refresh cannot
  reintroduce token-bloat into the tool schemas;
- keys are sorted recursively (``sort_keys``) and output is pretty-printed, so
  the JSON is diff-stable to the last refresh.

Deliberately a script (not part of the package): it needs the live console,
which is exactly what the vendored spec exists to avoid depending on.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from baton_mcp.server import SPEC_PATH, _strip_agent_useless_params

METRICS_PREFIX = "/v0/metrics/"


def prepare_spec(spec: dict[str, object]) -> dict[str, object]:
    """Reduce a fetched console spec to the vendored form."""
    paths = spec.get("paths")
    assert isinstance(paths, dict)
    spec["paths"] = {path: ops for path, ops in paths.items() if path.startswith(METRICS_PREFIX)}
    return _strip_agent_useless_params(spec)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="console origin to fetch /openapi.json from",
    )
    args = parser.parse_args()

    resp = httpx.get(f"{args.base_url.rstrip('/')}/openapi.json", timeout=10.0)
    resp.raise_for_status()
    spec = prepare_spec(json.loads(resp.text))

    rugged = json.dumps(spec, indent=4, sort_keys=True).rstrip("\n") + "\n"
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(rugged)
    paths = spec.get("paths")
    assert isinstance(paths, dict)
    print(f"wrote {SPEC_PATH} ({len(paths)} metrics paths, agent-useless params stripped)")  # noqa: T201


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as e:
        sys.exit(f"refresh-openapi: {e}")
