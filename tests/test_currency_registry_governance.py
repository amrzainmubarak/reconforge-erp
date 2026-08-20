from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.db import connect, run_migrations
from reconforge.platform import PlatformError
from reconforge.platform.master_data import MasterDataService
from reconforge.utils.currency_registry_governance import reconcile_currency_registry
from reconforge.utils.money import CurrencyRegistry, CurrencyRegistryContext, CurrencySpec, InvalidAmountError


def setup_function() -> None:
    CurrencyRegistry.reset_to_bundled()


def teardown_function() -> None:
    CurrencyRegistry.reset_to_bundled()


def test_reconciliation_is_order_independent_and_digest_bound() -> None:
    rows = [
        {"code": "USD", "minor_units": 2, "active": True, "name": "synthetic name"},
        {"code": "JPY", "minor_units": 0, "active": False},
    ]

    first = reconcile_currency_registry(rows, scope="workspace:default")
    second = reconcile_currency_registry(list(reversed(rows)), scope="workspace:default")

    assert first.ok is True
    assert first.status == "consistent"
    assert first.master_currency_count == 2
    assert first.active_master_currency_count == 1
    assert first.input_digest == second.input_digest
    assert first.to_dict()["registry"] == {
        "registry_version": CurrencyRegistry.manifest().registry_version,
        "digest": CurrencyRegistry.manifest().digest,
    }
    assert "synthetic name" not in str(first.to_dict())


def test_reconciliation_surfaces_precision_unknown_duplicate_and_invalid_rows_without_raw_values() -> None:
    result = reconcile_currency_registry(
        [
            {"code": "USD", "minor_units": 3, "active": True, "name": "do-not-echo"},
            {"code": "USD", "minor_units": 3, "active": True},
            {"code": "ZZZ", "minor_units": 2, "active": True},
            {"code": "BAD1", "minor_units": 2, "active": True},
        ],
        scope="tenant:synthetic",
    )

    assert result.ok is False
    assert {issue.code for issue in result.issues} == {
        "master_currency_duplicate",
        "master_currency_invalid",
        "minor_units_mismatch",
        "registry_currency_missing",
    }
    rendered = str(result.to_dict())
    assert "do-not-echo" not in rendered
    assert "ZZZ" in rendered
    assert result.to_dict()["status"] == "inconsistent"


def test_reconciliation_tracks_installed_registry_policy_digest() -> None:
    bundled = reconcile_currency_registry(
        [{"code": "USD", "minor_units": 2, "active": True}],
        scope="workspace:default",
    )
    CurrencyRegistry.register(
        CurrencySpec(code="USD", name="US Dollar policy", minor_units=3),
        registry_version="governance-test-v2",
        source="Synthetic governance test",
    )
    selected = reconcile_currency_registry(
        [{"code": "USD", "minor_units": 3, "active": True}],
        scope="workspace:default",
    )

    assert bundled.registry_digest != selected.registry_digest
    assert bundled.input_digest != selected.input_digest
    assert selected.ok is True


def test_reconciliation_detects_unbound_current_and_drifted_workspace_binding() -> None:
    rows = [{"code": "USD", "minor_units": 2, "active": True}]
    unbound = reconcile_currency_registry(rows, scope="workspace:default")
    assert unbound.ok is True
    assert unbound.to_dict()["binding"] == {"status": "unbound"}

    manifest = CurrencyRegistry.manifest()
    current = reconcile_currency_registry(
        rows,
        scope="workspace:default",
        binding={
            "registry_version": manifest.registry_version,
            "registry_digest": manifest.digest,
            "bound_at": "2026-08-11T00:00:00Z",
            "bound_by": "controller",
        },
    )
    assert current.ok is True
    assert current.to_dict()["binding"]["status"] == "current"

    drifted = reconcile_currency_registry(
        rows,
        scope="workspace:default",
        binding={
            "registry_version": "old-snapshot",
            "registry_digest": "0" * 64,
            "bound_at": "2026-08-11T00:00:00Z",
            "bound_by": "controller",
        },
    )
    assert drifted.ok is False
    assert drifted.to_dict()["binding"]["status"] == "drifted"


def test_reconciliation_rejects_malformed_binding_without_echoing_sensitive_fields() -> None:
    result = reconcile_currency_registry(
        [{"code": "USD", "minor_units": 2, "active": True}],
        scope="workspace:default",
        binding={"registry_version": "bad snapshot", "registry_digest": "secret"},
    )
    assert result.ok is False
    assert {issue.code for issue in result.issues} == {"registry_binding_invalid"}
    assert "secret" not in str(result.to_dict())


def test_reconciliation_uses_explicit_operation_context_after_registry_changes() -> None:
    rows = [{"code": "USD", "minor_units": 2, "active": True}]
    context = CurrencyRegistry.context()

    CurrencyRegistry.register(
        CurrencySpec(code="USD", name="USD context drift", minor_units=3),
        registry_version="governance-context-v2",
        source="Synthetic governance context test",
    )

    frozen = reconcile_currency_registry(rows, scope="workspace:context", registry_context=context)
    current = reconcile_currency_registry(rows, scope="workspace:context")

    assert frozen.status == "consistent"
    assert frozen.registry_digest == context.registry_manifest.digest
    assert current.status == "inconsistent"
    assert any(issue.code == "minor_units_mismatch" for issue in current.issues)


def test_sqlite_binding_selects_persisted_operation_context_and_reports_installed_drift(tmp_path: Path) -> None:
    database = tmp_path / "currency-context.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        service = MasterDataService(connection)
        service.upsert_organization(organization_code="CTX", name="Context Fixture")
        service.bind_currency_registry(workspace="default")
        bound_context = service.currency_registry_context(workspace="default")
        assert bound_context is not None
        original_digest = bound_context.registry_manifest.digest

        CurrencyRegistry.register(
            CurrencySpec(code="USD", name="USD changed after binding", minor_units=3),
            registry_version="governance-persisted-context-v2",
            source="Synthetic persisted context test",
        )

        result = service.currency_registry_reconciliation(workspace="default")
        assert result["registry"]["digest"] == original_digest
        assert result["binding"]["status"] == "drifted"
        assert result["status"] == "inconsistent"
        assert not any(issue["code"] == "minor_units_mismatch" for issue in result["issues"])

        connection.execute(
            "UPDATE currency_registry_snapshots SET snapshot_json = ? WHERE registry_digest = ?",
            ('{"schema_version":1}', original_digest),
        )
        connection.commit()
        with pytest.raises(InvalidAmountError):
            CurrencyRegistryContext.from_snapshot({"schema_version": 1})
        with pytest.raises(PlatformError, match="Bound currency registry snapshot is invalid"):
            service.currency_registry_context(workspace="default")
    finally:
        connection.close()


def test_reconciliation_schema_is_closed_and_accepts_current_output() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "docs" / "schemas" / "currency_registry_reconciliation.schema.json").read_text(encoding="utf-8")
    )
    result = reconcile_currency_registry(
        [{"code": "USD", "minor_units": 2, "active": True}],
        scope="workspace:default",
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.to_dict())
