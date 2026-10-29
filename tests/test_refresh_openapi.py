"""Tests for the vendored-spec refresh script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh_openapi.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("refresh_openapi", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refresh_openapi = _load_script()


def _schema_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _response(schema: str) -> dict[str, object]:
    return {"200": {"content": {"application/json": {"schema": _schema_ref(schema)}}}}


def test_prepare_spec_drops_schemas_only_the_dropped_paths_used():
    spec = {
        "paths": {
            "/v0/metrics/x": {"get": {"responses": _response("Used")}},
            "/v0/other": {"post": {"responses": _response("Unused")}},
        },
        "components": {
            "schemas": {
                "Used": {"properties": {"row": _schema_ref("Row")}},
                "Row": {"type": "object"},
                "Unused": {"type": "object"},
                "Orphan": {"type": "object"},
            }
        },
    }

    result = refresh_openapi.prepare_spec(spec)

    assert list(result["paths"]) == ["/v0/metrics/x"]
    assert set(result["components"]["schemas"]) == {"Used", "Row"}


def test_apply_agent_overlay_prunes_unused_schemas():
    spec = {
        "paths": {
            "/v0/metrics/x": {
                "get": {
                    "parameters": [{"name": "include", "in": "query"}],
                    "responses": _response("Used"),
                }
            }
        },
        "components": {
            "schemas": {
                "Used": {"type": "object"},
                "Unused": {"type": "object"},
            }
        },
    }

    result = refresh_openapi.apply_agent_overlay(spec)

    assert set(result["components"]["schemas"]) == {"Used"}
