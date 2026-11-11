"""The caller's workspace reaches baton-sdk as an Organization."""

from __future__ import annotations

import pytest
from baton import Organization, PrincipalResolutionContext

from baton_mcp import server
from baton_mcp.server import _make_principal_resolver, _parse_labels

TEN_A = "ten_e7cc0910"
TEN_B = "ten_0123456789abcdef0123456789abcdef"


def _context(headers: dict[str, str] | None) -> PrincipalResolutionContext:
    return PrincipalResolutionContext(headers=headers, meta=None, tool_name="t", arguments={})


def test_caller_with_tenant_header_gets_that_organization():
    resolve = _make_principal_resolver({})
    assert resolve(_context({"X-Baton-Tenant-Id": TEN_A})) == Organization(organization_id=TEN_A)
    assert resolve(_context({"x-baton-tenant-id": TEN_B})) == Organization(organization_id=TEN_B)


def test_mapped_workspace_gets_its_labels():
    resolve = _make_principal_resolver(_parse_labels(f"{TEN_A}:internal,{TEN_B}:beta"))
    assert resolve(_context({"x-baton-tenant-id": TEN_A})).labels == ("internal",)
    assert resolve(_context({"x-baton-tenant-id": "ten_00000000"})).labels == ()


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {},
        {"x-baton-tenant-id": ""},
        {"x-baton-tenant-id": f"{TEN_A} "},
        {"x-baton-tenant-id": "ten_E7CC0910"},
        {"x-baton-tenant-id": "ten_" + "a" * 10_000},
        {"x-baton-tenant-id": "anything"},
    ],
)
def test_caller_without_a_workspace_id_gets_none(headers):
    assert _make_principal_resolver({TEN_A: ("internal",)})(_context(headers)) is None


def test_resolver_ignores_authorization():
    resolve = _make_principal_resolver({})
    assert resolve(_context({"Authorization": "Bearer secret-key"})) is None
    with_tenant = {"Authorization": "Bearer secret-key", "x-baton-tenant-id": TEN_A}
    assert resolve(_context(with_tenant)) == Organization(organization_id=TEN_A)


def test_parse_labels_skips_malformed_entries():
    raw = f" {TEN_A}:internal, junk, :x, {TEN_B}:, {TEN_A}:beta ,"
    assert _parse_labels(raw) == {TEN_A: ("internal", "beta")}
    assert _parse_labels("") == {}


@pytest.mark.parametrize("dsn", ["https://baton_pk_x@example.invalid/ten_e7cc0910/srv-1", ""])
def test_instrument_passes_resolver(monkeypatch, dsn):
    captured = []
    monkeypatch.setenv("BATON_DSN", dsn)
    monkeypatch.setenv(server.LABELS_ENV, f"{TEN_A}:internal")
    monkeypatch.setattr(
        "baton.integrations.standalone.install_baton", lambda mcp, config: captured.append(config)
    )
    server._instrument(object())  # type: ignore[arg-type]
    (config,) = captured
    org = config.resolve_principal(_context({"x-baton-tenant-id": TEN_A}))
    assert org == Organization(organization_id=TEN_A, labels=("internal",))
