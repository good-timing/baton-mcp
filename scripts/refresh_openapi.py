"""Refresh the vendored OpenAPI spec from a locally running baton-console.

Fetches ``/openapi.json`` from the console named by ``--base-url`` (default
``http://localhost:8000`` — start the console first, e.g. ``make dev`` there),
reduces it to exactly what ``FastMCP.from_openapi`` consumes, and writes two
files under ``src/baton_mcp/``:

- ``source.openapi.json``: the fetched spec with only paths under
  ``/v0/metrics/`` kept (the route maps exclude the rest, but vendoring a
  87-path spec makes the commit and the tool source slower to review than it
  needs to be), and with schemas that only those dropped paths referenced
  removed from ``components.schemas``;
- ``openapi.json``: ``source.openapi.json`` with ``overlay.json`` applied.
  This is the file the server ships and loads at startup.

Both files are written with sorted, pretty-printed JSON so refreshes diff
cleanly. Refreshing fails rather than silently writing an unpatched spec when
the overlay cannot be applied or leaves an agent-useless parameter behind.

``--check`` skips the fetch: it applies ``overlay.json`` to the committed
``source.openapi.json`` and fails, printing a diff, when ``openapi.json`` is
not the byte-for-byte result. ``make fresh-openapi`` uses it in CI.

Deliberately a script (not part of the package): it needs the live console,
which is exactly what the vendored spec exists to avoid depending on.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

import httpx
from oas_patch.file_utils import load_file  # type: ignore[import-untyped]
from oas_patch.overlay import apply_overlay  # type: ignore[import-untyped]

from baton_mcp.server import SPEC_PATH

METRICS_PREFIX = "/v0/metrics/"
SCHEMA_REF_PREFIX = "#/components/schemas/"

# Written next to the shipped spec: the pre-overlay source and the overlay that
# turns it into the agent-facing surface.
SOURCE_PATH = SPEC_PATH.with_name("source.openapi.json")
OVERLAY_PATH = SPEC_PATH.with_name("overlay.json")


def _iter_refs(node: object):
    """Yield every ``$ref`` string anywhere under ``node``."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref
        for key, value in node.items():
            if key != "$ref":
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def _schema_name(ref: str) -> str | None:
    """Return the ``components.schemas`` name a ``$ref`` points at, if any."""
    if not ref.startswith(SCHEMA_REF_PREFIX):
        return None
    return ref[len(SCHEMA_REF_PREFIX) :].split("/", 1)[0] or None


def prune_unused_schemas(spec: dict[str, object]) -> dict[str, object]:
    """Drop ``components.schemas`` entries the remaining paths cannot reach.

    Keeps every schema referenced directly by a path, plus schemas reachable
    through those schemas' own ``$ref``s. Schemas only the filtered-out paths
    used would otherwise ship unused.
    """
    components = spec.get("components")
    if not isinstance(components, dict):
        return spec
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return spec

    reachable: set[str] = set()
    pending = [name for ref in _iter_refs(spec.get("paths")) if (name := _schema_name(ref))]
    while pending:
        name = pending.pop()
        if name in reachable or name not in schemas:
            continue
        reachable.add(name)
        pending.extend(nested for ref in _iter_refs(schemas[name]) if (nested := _schema_name(ref)))

    components["schemas"] = {name: schema for name, schema in schemas.items() if name in reachable}
    return spec


def prepare_spec(spec: dict[str, object]) -> dict[str, object]:
    """Reduce a fetched console spec to the vendored form."""
    paths = spec.get("paths")
    assert isinstance(paths, dict)
    spec["paths"] = {path: ops for path, ops in paths.items() if path.startswith(METRICS_PREFIX)}
    return prune_unused_schemas(spec)


def apply_agent_overlay(spec: dict[str, object]) -> dict[str, object]:
    """Apply ``overlay.json``, prune orphaned schemas, and verify the result."""
    try:
        overlay = load_file(str(OVERLAY_PATH))
    except (OSError, ValueError) as e:
        sys.exit(f"refresh-openapi: overlay not readable at {OVERLAY_PATH}: {e}")
    try:
        patched = apply_overlay(spec, overlay)
    except Exception as e:
        sys.exit(f"refresh-openapi: overlay at {OVERLAY_PATH} could not be applied: {e}")
    # An overlay can remove the only reference to a schema, so prune
    # the patched document.
    patched = prune_unused_schemas(patched)

    for path, ops in patched["paths"].items():
        params = [p["name"] for op in ops.values() for p in op.get("parameters", [])]
        if "include" in params:
            sys.exit(f"refresh-openapi: overlay left 'include' on {path}")
    return patched


def render_spec(spec: dict[str, object]) -> str:
    return json.dumps(spec, indent=4, sort_keys=True).rstrip("\n") + "\n"


def write_spec(path: Path, spec: dict[str, object]) -> None:
    path.write_text(render_spec(spec))


def check_fresh() -> None:
    """Fail unless ``openapi.json`` is exactly ``source.openapi.json`` + overlay.

    Never writes. This is what keeps the committed artifact honest in CI: a
    source or overlay edit that was not followed by ``make refresh-openapi``
    shows up here as a diff.
    """
    try:
        source = json.loads(SOURCE_PATH.read_text())
    except OSError as e:
        sys.exit(f"refresh-openapi: source spec not readable at {SOURCE_PATH}: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"refresh-openapi: source spec at {SOURCE_PATH} is not valid JSON: {e}")

    patched = apply_agent_overlay(source)
    expected = render_spec(patched)

    try:
        actual = SPEC_PATH.read_text()
    except OSError as e:
        sys.exit(f"refresh-openapi: spec not readable at {SPEC_PATH}: {e}")

    if actual != expected:
        diff = difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=str(SPEC_PATH),
            tofile=f"{SPEC_PATH} (source.openapi.json + overlay.json)",
            lineterm="",
        )
        print("\n".join(diff))  # noqa: T201
        sys.exit("refresh-openapi: openapi.json is stale; run `make refresh-openapi`")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="console origin to fetch /openapi.json from",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify openapi.json matches source.openapi.json + overlay.json; fetch and write nothing",
    )
    args = parser.parse_args()

    if args.check:
        check_fresh()
        print("openapi.json is fresh")  # noqa: T201
        return

    resp = httpx.get(f"{args.base_url.rstrip('/')}/openapi.json", timeout=10.0)
    resp.raise_for_status()
    source = prepare_spec(json.loads(resp.text))

    write_spec(SOURCE_PATH, source)
    patched = apply_agent_overlay(source)
    write_spec(SPEC_PATH, patched)

    paths = patched.get("paths")
    assert isinstance(paths, dict)
    print(  # noqa: T201
        f"wrote {SOURCE_PATH} and {SPEC_PATH} ({len(paths)} metrics paths, overlay applied)"
    )


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as e:
        sys.exit(f"refresh-openapi: {e}")
