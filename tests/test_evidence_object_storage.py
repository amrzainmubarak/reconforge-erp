from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from reconforge.application.evidence import EvidenceStorageScope
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.infrastructure.object_storage import LocalObjectStorageSettings, LocalObjectStore, StoredObject
from reconforge.platform.common import PlatformError
from reconforge.platform.evidence import (
    LOCAL_STORAGE_BACKEND,
    OBJECT_STORAGE_BACKEND,
    EvidenceRegistryService,
)


class FakeEvidenceObjectStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[tuple[str, str]] = []

    def put_bytes(
        self,
        tenant_id: str,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredObject:
        del retention_until
        tenant = tenant_id.lower()
        self.objects[(tenant, object_name)] = content
        self.put_calls.append((tenant, object_name))
        digest = hashlib.sha256(content).hexdigest()
        object_metadata = {"reconforge-tenant": tenant}
        object_metadata.update({str(key): str(value) for key, value in (metadata or {}).items()})
        return StoredObject(
            key=f"fake/tenant/{tenant}/{object_name}",
            content=content,
            sha256=digest,
            content_type=content_type,
            metadata=object_metadata,
            version_id="v1",
        )

    def get_bytes(self, tenant_id: str, object_name: str) -> StoredObject:
        tenant = tenant_id.lower()
        content = self.objects[(tenant, object_name)]
        return StoredObject(
            key=f"fake/tenant/{tenant}/{object_name}",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            content_type="text/plain",
            metadata={"reconforge-tenant": tenant},
            version_id="v1",
        )


def test_object_backed_evidence_is_registered_and_verified_without_local_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-object.db"
    source = tmp_path / "support.txt"
    source.write_text("tenant-a support\n", encoding="utf-8")
    expected_content = source.read_bytes()
    run_migrations(db_path)
    store = FakeEvidenceObjectStore()

    connection = connect(db_path, require_exists=True)
    try:
        evidence = EvidenceRegistryService(connection).register(
            source,
            evidence_code="SUPPORT-1",
            storage_tenant_id="tenant-a",
            object_store=store,
            content_type="text/plain",
        )
        source.unlink()
        verification = EvidenceRegistryService(connection).verify(str(evidence["id"]), object_store=store)
        stored_row = EvidenceRegistryService(connection).get(str(evidence["id"]))
    finally:
        connection.close()

    assert stored_row["storage_backend"] == OBJECT_STORAGE_BACKEND
    assert stored_row["storage_tenant_id"] == "tenant-a"
    assert stored_row["storage_key"].startswith("evidence/EVDREG-")
    assert stored_row["storage_version_id"] == "v1"
    assert stored_row["content_type"] == "text/plain"
    assert stored_row["byte_size"] == len(expected_content)
    assert verification.ok is True
    assert store.put_calls == [("tenant-a", stored_row["storage_key"])]


def test_sqlite_evidence_retention_floor_is_versioned_and_fail_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-retention.db"
    source = tmp_path / "support.txt"
    source.write_text("retained evidence\n", encoding="utf-8")
    run_migrations(db_path)
    store = FakeEvidenceObjectStore()
    first_floor = datetime(2027, 1, 1, tzinfo=UTC)
    extended_floor = first_floor + timedelta(days=30)
    shortened_floor = first_floor + timedelta(days=1)

    connection = connect(db_path, require_exists=True)
    try:
        service = EvidenceRegistryService(connection)
        first = service.register(
            source,
            evidence_code="RETENTION-1",
            storage_tenant_id="tenant-a",
            storage_object_name="evidence/retention/one.txt",
            object_store=store,
            retention_until=first_floor,
        )
        first_row = connection.execute(
            "SELECT retention_until, retention_version FROM evidence_registry WHERE id = ?",
            (first["id"],),
        ).fetchone()

        service.register(
            source,
            evidence_code="RETENTION-1",
            storage_tenant_id="tenant-a",
            storage_object_name="evidence/retention/two.txt",
            object_store=store,
            retention_until=extended_floor,
        )
        extended_row = connection.execute(
            "SELECT retention_until, retention_version FROM evidence_registry WHERE id = ?",
            (first["id"],),
        ).fetchone()
        put_calls_before_rejected_request = len(store.put_calls)

        with pytest.raises(PlatformError, match="cannot be shortened"):
            service.register(
                source,
                evidence_code="RETENTION-1",
                storage_tenant_id="tenant-a",
                storage_object_name="evidence/retention/three.txt",
                object_store=store,
                retention_until=shortened_floor,
            )
        assert len(store.put_calls) == put_calls_before_rejected_request

        with pytest.raises(sqlite3.IntegrityError, match="cannot be shortened"):
            connection.execute(
                "UPDATE evidence_registry SET retention_until = ?, retention_version = ? WHERE id = ?",
                (shortened_floor.isoformat().replace("+00:00", "Z"), 3, first["id"]),
            )
        connection.rollback()
        final_row = connection.execute(
            "SELECT retention_until, retention_version FROM evidence_registry WHERE id = ?",
            (first["id"],),
        ).fetchone()
    finally:
        connection.close()

    assert first_row["retention_version"] == 1
    assert extended_row["retention_version"] == 2
    assert extended_row["retention_until"] == extended_floor.isoformat().replace("+00:00", "Z")
    assert dict(final_row) == dict(extended_row)


def test_local_object_store_satisfies_evidence_contract_end_to_end(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-local-object.db"
    source = tmp_path / "support.txt"
    source.write_text("offline evidence\n", encoding="utf-8")
    run_migrations(db_path)
    store = LocalObjectStore(LocalObjectStorageSettings(root=(tmp_path / "objects").resolve()))

    connection = connect(db_path, require_exists=True)
    try:
        registered = EvidenceRegistryService(connection).register(
            source,
            evidence_code="LOCAL-OBJECT-1",
            storage_tenant_id="tenant-a",
            object_store=store,
        )
        source.unlink()
        verification = EvidenceRegistryService(connection).verify(str(registered["id"]), object_store=store)
    finally:
        connection.close()

    assert registered["storage_backend"] == OBJECT_STORAGE_BACKEND
    assert verification.ok is True
    scope = EvidenceStorageScope(
        tenant_id="tenant-a",
        workspace_id=str(registered["workspace_id"]),
    )
    object_path = tmp_path / "objects" / Path(
        *store.key_for(scope, str(registered["storage_key"])).split("/")
    )
    assert object_path.is_file()
    assert "/workspace/" in store.key_for(scope, str(registered["storage_key"]))


def test_object_backed_evidence_is_tenant_keyed_and_tampering_is_visible(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-tenants.db"
    source_a = tmp_path / "support-a.txt"
    source_b = tmp_path / "support-b.txt"
    source_a.write_text("a\n", encoding="utf-8")
    source_b.write_text("b\n", encoding="utf-8")
    run_migrations(db_path)
    store = FakeEvidenceObjectStore()

    connection = connect(db_path, require_exists=True)
    try:
        first = EvidenceRegistryService(connection).register(
            source_a,
            evidence_code="SUPPORT-A",
            workspace="workspace-a",
            storage_tenant_id="tenant-a",
            object_store=store,
        )
        second = EvidenceRegistryService(connection).register(
            source_b,
            evidence_code="SUPPORT-A",
            workspace="workspace-b",
            storage_tenant_id="tenant-b",
            object_store=store,
        )
        first_key = str(first["storage_key"])
        second_key = str(second["storage_key"])
        store.objects[("tenant-a", first_key)] = b"tampered"
        result = EvidenceRegistryService(connection).verify(str(first["id"]), object_store=store)
    finally:
        connection.close()

    assert first_key != second_key
    assert ("tenant-a", first_key) in store.objects
    assert ("tenant-b", second_key) in store.objects
    assert result.ok is False
    with pytest.raises(KeyError):
        store.get_bytes("tenant-b", first_key)


def test_object_storage_failure_does_not_create_a_registry_row(tmp_path: Path) -> None:
    class FailingStore(FakeEvidenceObjectStore):
        def put_bytes(self, *args: object, **kwargs: object) -> StoredObject:
            raise RuntimeError("provider unavailable")

    db_path = tmp_path / "evidence-failure.db"
    source = tmp_path / "support.txt"
    source.write_text("support\n", encoding="utf-8")
    run_migrations(db_path)

    connection = connect(db_path, require_exists=True)
    try:
        with pytest.raises(PlatformError, match="object storage"):
            EvidenceRegistryService(connection).register(
                source,
                evidence_code="FAIL-1",
                storage_tenant_id="tenant-a",
                object_store=FailingStore(),
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM evidence_registry").fetchone()["count"] == 0
    finally:
        connection.close()


def test_hierarchical_scope_mismatch_does_not_create_a_registry_row(tmp_path: Path) -> None:
    class WrongWorkspaceStore:
        supports_hierarchical_scope = True

        def put_bytes(
            self,
            tenant_id: str | EvidenceStorageScope,
            object_name: str,
            content: bytes,
            **_: Any,
        ) -> StoredObject:
            assert isinstance(tenant_id, EvidenceStorageScope)
            digest = hashlib.sha256(content).hexdigest()
            return StoredObject(
                key=object_name,
                content=content,
                sha256=digest,
                content_type="application/octet-stream",
                metadata={
                    "reconforge-tenant": tenant_id.tenant_id,
                    "reconforge-workspace": "sibling-workspace",
                    "reconforge-entity": "",
                },
                version_id="v1",
            )

        def get_bytes(
            self,
            tenant_id: str | EvidenceStorageScope,
            object_name: str,
        ) -> StoredObject:
            raise AssertionError((tenant_id, object_name))

    db_path = tmp_path / "evidence-scope-mismatch.db"
    source = tmp_path / "support.txt"
    source.write_text("support\n", encoding="utf-8")
    run_migrations(db_path)

    connection = connect(db_path, require_exists=True)
    try:
        with pytest.raises(PlatformError, match="workspace scope"):
            EvidenceRegistryService(connection).register(
                source,
                evidence_code="WRONG-SCOPE-1",
                workspace="workspace-a",
                storage_tenant_id="tenant-a",
                object_store=WrongWorkspaceStore(),
            )
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM evidence_registry"
        ).fetchone()["count"] == 0
    finally:
        connection.close()


def test_local_evidence_remains_backward_compatible_and_backup_preserves_storage_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-local.db"
    source = tmp_path / "support.txt"
    source.write_text("local support\n", encoding="utf-8")
    run_migrations(db_path)

    connection = connect(db_path, require_exists=True)
    try:
        registered = EvidenceRegistryService(connection).register(source, evidence_code="LOCAL-1")
        assert registered["storage_backend"] == LOCAL_STORAGE_BACKEND
        assert EvidenceRegistryService(connection).verify(str(registered["id"])).ok is True
    finally:
        connection.close()

    backup = create_backup(db_path, tmp_path / "backups")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    connection = connect(restored, require_exists=True)
    try:
        row = connection.execute(
            "SELECT storage_backend, storage_key, byte_size, retention_version "
            "FROM evidence_registry WHERE evidence_code = ?",
            ("LOCAL-1",),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["storage_backend"] == LOCAL_STORAGE_BACKEND
    assert row["storage_key"] == ""
    assert row["byte_size"] == 0
    assert row["retention_version"] == 1


def test_schema_upgrade_adds_object_storage_columns_without_changing_existing_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-upgrade.db"
    source = tmp_path / "support.txt"
    source.write_text("legacy support\n", encoding="utf-8")
    run_migrations(db_path, target_version=18)
    connection = connect(db_path, require_exists=True)
    try:
        registered = EvidenceRegistryService(connection).register(source, evidence_code="LEGACY-1")
        assert registered["id"]
    finally:
        connection.close()

    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute(
            "SELECT storage_backend, storage_key FROM evidence_registry WHERE evidence_code = ?",
            ("LEGACY-1",),
        ).fetchone()
    finally:
        connection.close()
    assert row["storage_backend"] == LOCAL_STORAGE_BACKEND
    assert row["storage_key"] == ""
