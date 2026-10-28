"""Tests for the OpenAPI overlay applied to the vendored spec."""

from __future__ import annotations

from oas_patch.file_utils import load_file  # type: ignore[import-untyped]
from oas_patch.overlay import apply_overlay  # type: ignore[import-untyped]

from baton_mcp.server import SPEC_PATH

OVERLAY_PATH = SPEC_PATH.with_name("overlay.json")


def _spec(*param_names: str) -> dict[str, object]:
    return {
        "paths": {
            "/v0/metrics/x": {
                "get": {
                    "parameters": [{"name": name, "in": "query"} for name in param_names],
                }
            }
        }
    }


def test_overlay_removes_include_and_keeps_other_params():
    overlay = load_file(str(OVERLAY_PATH))
    patched = apply_overlay(_spec("include", "vendor_id"), overlay)
    params = patched["paths"]["/v0/metrics/x"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["vendor_id"]


def test_target_matching_nothing_is_a_no_op():
    overlay = {
        "overlay": "1.0.0",
        "info": {"title": "test", "version": "1.0.0"},
        "actions": [
            {
                "target": "$.paths[*][*].parameters[?(@.name == 'absent')]",
                "remove": True,
            }
        ],
    }
    assert apply_overlay(_spec("include"), overlay) == _spec("include")
