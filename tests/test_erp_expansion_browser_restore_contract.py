"""Restore orchestration contracts without a PostgreSQL or Docker workload."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from tests import erp_expansion_browser_restore as restore
from tests import gfo_browser_restore as snapshot
from tests.manufacturing_execution_browser import MANUFACTURING_EXECUTION_TABLES


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def fetchone(self) -> Any:
        return self.values[0] if self.values else None

    def fetchall(self) -> list[Any]:
        return self.values

    def __iter__(self) -> Any:
        return iter(self.values)


class Connection:
    def __init__(self, *, foreign: bool = False, refuse: bool = True) -> None:
        self.foreign, self.refuse = foreign, refuse

    def execute(self, statement: Any, parameters: Any = None) -> Rows:
        if statement == "TAMPER" and self.refuse:
            raise psycopg.errors.CheckViolation("Original immutable guard")
        if isinstance(statement, str) and "rolsuper" in statement:
            return Rows([(False, False)])
        if isinstance(statement, str) and "pg_database" in statement:
            return Rows([])
        return Rows([{"n": 0}] if self.foreign else [(0,)])

    @contextmanager
    def transaction(self) -> Any:
        yield self

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class Runtime:
    def __init__(self, factory: Any = None, admin_dsn: str = "postgresql://postgres@localhost/postgres",
                 tenant: str = "synthetic", password: str = "fixture-only") -> None:
        self.factory = factory or SimpleNamespace(settings=SimpleNamespace(dsn="postgresql://app@localhost/postgres"))
        self.admin_dsn, self.tenant, self.password = admin_dsn, tenant, password
        self.actors: list[str] = []

    @contextmanager
    def actor(self, name: str) -> Any:
        self.actors.append(name)
        yield Connection(), None, None


def harness(monkeypatch: pytest.MonkeyPatch, *, damage: str | None = None) -> tuple[Runtime, list[tuple[str, ...]], list[Runtime]]:
    protected = tuple(dict.fromkeys(restore.FINANCIAL_TABLES + restore.EXPANSION_TABLES + MANUFACTURING_EXECUTION_TABLES))
    calls: list[tuple[str, ...]] = []
    restored: list[Runtime] = []
    original = {"tables": {name: {"rows": 1, "sha256": "original-" + name} for name in protected},
                "objects": {"relations": {"count": len(protected), "sha256": "original-acl-force-rls"}},
                "head": restore.POSTGRES_MIGRATION_REVISIONS[-1], "forced_rls_financial_tables": len(protected)}

    def database_snapshot(dsn: str, *, financial_tables: tuple[str, ...]) -> dict[str, Any]:
        calls.append(financial_tables)
        assert len(financial_tables) == len(set(financial_tables))
        assert set(financial_tables) == set(protected)
        value = copy.deepcopy(original)
        if len(calls) == 2 and damage == "rows":
            value["tables"][protected[-1]]["sha256"] = "altered-populated-rows"
        if len(calls) == 2 and damage == "acl_rls":
            value["objects"]["relations"]["sha256"] = "altered-acl-force-rls"
        return value

    def receipt_runtime(*args: Any) -> Runtime:
        runtime = Runtime(*args)
        restored.append(runtime)
        return runtime

    class Boundary:
        def __init__(self, factory: Any) -> None:
            pass

        @contextmanager
        def transaction(self, tenant: str, **scope: Any) -> Any:
            assert scope == {"workspace_id": "foreign", "organization_id": "org", "legal_entity_id": "entity"}
            yield Connection(foreign=True)

    monkeypatch.setattr(restore, "database_snapshot", database_snapshot)
    monkeypatch.setattr(restore, "ReceiptRuntime", receipt_runtime)
    monkeypatch.setattr(restore, "PostgresTenantBoundary", Boundary)
    monkeypatch.setattr(restore, "PostgresConnectionFactory", lambda settings: SimpleNamespace(settings=settings))
    monkeypatch.setattr(restore.psycopg, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(restore.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"PGDMPoriginal-native-dump"))
    return Runtime(), calls, restored


def execute(runtime: Runtime, **kwargs: Any) -> dict[str, Any]:
    return restore.verify_expansion_native_restore(runtime, "owned-test-only",
        verify_cycles=lambda _: {"native_effect": "same-original-effect"},
        extension_tables=restore.EXPANSION_TABLES + MANUFACTURING_EXECUTION_TABLES,
        tamper_statements=("TAMPER",), **kwargs)


def test_complete_unique_native_and_module_union_keeps_exact_row_catalog_and_default_actor_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, calls, restored = harness(monkeypatch)
    result = execute(runtime)
    assert result["status"] == "passed" and result["tamper_refusals"] == 1
    assert len(calls) == 4 and all(names == calls[0] for names in calls)
    assert len(calls[0]) == 48 and set(calls[0]) == set(restore.FINANCIAL_TABLES + restore.EXPANSION_TABLES + MANUFACTURING_EXECUTION_TABLES)
    assert restored[0].actors == ["browser-poster"]
    assert result["snapshot"] == result["probe_checkpoint"]


@pytest.mark.parametrize("damage", ["rows", "acl_rls"])
def test_dedup_preserves_exact_populated_rows_and_catalog_refusal(monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    runtime, _, _ = harness(monkeypatch, damage=damage)
    with pytest.raises(AssertionError, match="Full populated rows/catalog/ACL/RLS"):
        execute(runtime)


@pytest.mark.parametrize("refuse", [True, False])
def test_explicit_actor_context_is_used_without_weakening_tamper_refusal(monkeypatch: pytest.MonkeyPatch, refuse: bool) -> None:
    runtime, _, restored = harness(monkeypatch)
    seen = []

    @contextmanager
    def scoped_actor(value: Runtime) -> Any:
        seen.append(value)
        yield Connection(refuse=refuse), None, None

    if refuse:
        assert execute(runtime, tamper_actor=scoped_actor)["tamper_refusals"] == 1
    else:
        with pytest.raises(AssertionError, match="Restored immutable guards"):
            execute(runtime, tamper_actor=scoped_actor)
    assert seen == restored and restored[0].actors == []


@pytest.mark.parametrize("guard", ["enabled", "forced", "missing"])
def test_actual_snapshot_requires_every_distinct_relation_enabled_and_force_rls(monkeypatch: pytest.MonkeyPatch, guard: str) -> None:
    names = ("native_financial", "owned_manufacturing")

    class SnapshotConnection(Connection):
        def execute(self, statement: Any, parameters: Any = None) -> Rows:
            if isinstance(statement, str) and "c.relkind='r'" in statement:
                return Rows([(name,) for name in names])
            if isinstance(statement, str) and statement.startswith("SELECT version_num"):
                return Rows([(restore.POSTGRES_MIGRATION_REVISIONS[-1],)])
            if isinstance(statement, str) and "c.relname=ANY" in statement:
                rows = [(name, not(guard == "enabled" and index == 1), not(guard == "forced" and index == 1)) for index, name in enumerate(names)]
                return Rows(rows[:1] if guard == "missing" else rows)
            return Rows([])

    monkeypatch.setattr(snapshot.psycopg, "connect", lambda *args, **kwargs: SnapshotConnection())
    with pytest.raises(AssertionError, match="Native restore invariant"):
        snapshot.database_snapshot("fixture-only", financial_tables=names)
