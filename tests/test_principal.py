"""The caller's workspace reaches baton-sdk as an Organization."""

from __future__ import annotations

from baton import Organization, PrincipalResolutionContext

from baton_mcp import server
from baton_mcp.server import _make_principal_resolver, _parse_labels


def _context(headers: dict[str, str] | None) -> PrincipalResolutionContext:
    return PrincipalResolutionContext(headers=headers, meta=None, tool_name="t", arguments={})


def test_caller_with_tenant_header_gets_that_organization():
    resolve = _make_principal_resolver({})
    org = resolve(_context({"X-Baton-Tenant-Id": "ten_abc"}))
    assert org == Organization(organization_id="ten_abc")


def test_mapped_workspace_gets_its_labels():
    resolve = _make_principal_resolver(_parse_labels("ten_abc:internal,ten_xyz:beta"))
    assert resolve(_context({"x-baton-tenant-id": "ten_abc"})).labels == ("internal",)
    assert resolve(_context({"x-baton-tenant-id": "ten_other"})).labels == ()


def test_caller_without_tenant_header_gets_none():
    resolve = _make_principal_resolver({"ten_abc": ("internal",)})
    assert resolve(_context({})) is None
    assert resolve(_context(None)) is None
    assert resolve(_context({"x-baton-tenant-id": "  "})) is None


def test_resolver_ignores_authorization():
    resolve = _make_principal_resolver({})
    assert resolve(_context({"Authorization": "Bearer secret-key"})) is None
    org = resolve(_context({"Authorization": "Bearer secret-key", "x-baton-tenant-id": "ten_abc"}))
    assert "secret-key" not in repr(org)


def test_parse_labels_skips_malformed_and_merges_repeats():
    assert _parse_labels(" ten_a:internal, junk, :x, ten_b:, ten_a:beta, ten_a:internal ,") == {
        "ten_a": ("internal", "beta"),
    }
    assert _parse_labels("") == {}


def test_instrument_passes_resolver_with_dsn(monkeypatch):
    captured = []
    monkeypatch.setenv("BATON_DSN", "https://baton_pk_x@example.invalid/ten_abc/srv-1")
    monkeypatch.setenv(server.LABELS_ENV, "ten_abc:internal")
    monkeypatch.setattr(
        "baton.integrations.standalone.install_baton", lambda mcp, config: captured.append(config)
    )
    server._instrument(object())  # type: ignore[arg-type]
    (config,) = captured
    assert config.settings == "console"
    org = config.resolve_principal(_context({"x-baton-tenant-id": "ten_abc"}))
    assert org == Organization(organization_id="ten_abc", labels=("internal",))
