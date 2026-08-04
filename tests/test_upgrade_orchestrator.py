from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

import reconforge.upgrade.postgres_adapter as postgres_upgrade_module
from reconforge.connectors.package import TrustedPublisherKey, TrustedPublisherRegistry
from reconforge.db.migrations import database_status, run_migrations
from reconforge.infrastructure.object_storage import LocalObjectStorageSettings, LocalObjectStore
from reconforge.infrastructure.postgres_backup import PostgresNativeBackupAdapter
from reconforge.packs.lifecycle import (
    PackLifecycleStore,
    SignedPackEnvelope,
    VerifiedPack,
    load_verified_pack,
    signature_payload,
)
from reconforge.upgrade.application_adapter import PythonWheelApplicationAdapter, write_deployment_marker
from reconforge.upgrade.configuration_adapter import ConfigurationUpgradeAdapter, write_configuration_marker
from reconforge.upgrade.object_store_adapter import (
    LocalObjectCatalogUpgradeAdapter,
    build_object_catalog,
    write_object_catalog,
)
from reconforge.upgrade.orchestrator import (
    ApplyReceipt,
    PreflightEvidence,
    StepKind,
    UpgradeError,
    UpgradeOrchestrator,
    UpgradePlan,
    UpgradeStep,
)
from reconforge.upgrade.pack_adapter import SignedPackUpgradeAdapter
from reconforge.upgrade.postgres_adapter import (
    PostgreSQLUpgradeAdapter,
    PsycopgAlembicMigrationRunner,
    postgres_revision_digest,
)
from reconforge.upgrade.sqlite_adapter import SQLiteUpgradeAdapter


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _build_minimal_wheel(path: Path, version: str) -> str:
    files = {
        "reconforge/__init__.py": f'__version__ = "{version}"\n'.encode(),
        f"reconforge_erp-{version}.dist-info/METADATA": f"Metadata-Version: 2.1\nName: reconforge-erp\nVersion: {version}\n".encode(),
        f"reconforge_erp-{version}.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    rows: list[list[str]] = []
    for name, content in files.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        rows.append([name, f"sha256={encoded}", str(len(content))])
    record_name = f"reconforge_erp-{version}.dist-info/RECORD"
    rows.append([record_name, "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    files[record_name] = output.getvalue().encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_pack(path: Path, private_key: Ed25519PrivateKey, version: str) -> tuple[VerifiedPack, TrustedPublisherRegistry]:
    rule = {
        "rule_id": "UP-001", "rule_name": "Synthetic missing reference", "severity": "high",
        "entity_type": "gl_entry", "source_file": "gl_entries.csv",
        "condition": {"operator": "missing", "field": "reference"},
        "message": "Reference required.", "recommended_action": "Review synthetic record.",
        "risk_impact": 70, "evidence_fields": ["entry_id"],
    }
    payload = {
        "package_schema": "signed-data-pack-v1", "publisher_id": "test.publisher", "key_id": "key-1", "algorithm": "Ed25519",
        "manifest": {
            "schema": "signed-data-pack-manifest-v1", "pack_id": "upgrade-pack", "name": "Upgrade test pack",
            "version": version, "kind": "control", "reconforge_version": ">=0.7.0,<0.8.0", "dependencies": [],
            "metadata": {"pack_id": "upgrade-pack", "name": "Upgrade test pack", "version": version, "description": "Synthetic."},
            "rules": {"rules": [rule]}, "golden": {"rule_count": 1, "rule_ids": ["UP-001"]},
        },
        "signature": base64.b64encode(b"0" * 64).decode("ascii"),
    }
    envelope = SignedPackEnvelope.model_validate(payload)
    payload["signature"] = base64.b64encode(private_key.sign(signature_payload(envelope))).decode("ascii")
    path.write_text(json.dumps(payload), encoding="utf-8")
    public_key = private_key.public_key().public_bytes_raw()
    registry = TrustedPublisherRegistry(version=1, keys=(TrustedPublisherKey("test.publisher", "key-1", public_key),))
    return load_verified_pack(path, trusted_registry=registry), registry


@dataclass
class _Adapter:
    kind: StepKind
    resource_id: str
    events: list[str]
    state: str = "0.7.1"
    fail: bool = False
    fail_after_effect: bool = False
    recoverable: bool = True
    receipt: ApplyReceipt | None = field(default=None, init=False)

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        self.events.append(f"preflight:{self.kind}")
        if self.state != step.from_version:
            raise UpgradeError("source mismatch")
        return PreflightEvidence(_digest(self.state), _digest(f"rollback:{self.kind}"), _digest(step.compatibility_reader))

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        self.events.append(f"apply:{self.kind}")
        if evidence.source_digest != _digest(self.state):
            raise UpgradeError("stale preflight")
        if self.fail and not self.fail_after_effect:
            raise UpgradeError("synthetic before-effect failure")
        self.state = step.to_version
        self.receipt = ApplyReceipt(_digest(self.state), f"restore:{step.from_version}")
        if self.fail_after_effect:
            raise UpgradeError("synthetic uncertain outcome")
        return self.receipt

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        self.events.append(f"recover:{self.kind}")
        if not self.recoverable:
            return None
        return self.receipt if self.receipt is not None else "not_applied"

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self.events.append(f"verify:{self.kind}")
        return _digest(self.state)

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self.events.append(f"rollback:{self.kind}")
        self.state = step.from_version
        return _digest(self.state)


class _PostgresBackup:
    def __init__(self) -> None:
        self.cleanup_count = 0
        self.restore_count = 0

    def create_backup(self, output_path: Path, *, key: bytes) -> None:
        assert len(key) == 32
        output_path.write_bytes(b"synthetic-encrypted-postgres-backup")

    def restore_backup(self, input_path: Path, *, key: bytes) -> None:
        assert input_path.is_file() and len(key) == 32
        self.restore_count += 1

    def drop_restored_database(self) -> None:
        self.cleanup_count += 1


class _PostgresMigrations:
    def __init__(self) -> None:
        self.revisions = {"source": "0052_security_governance", "compatibility": "0052_security_governance"}
        self.events: list[str] = []

    def current_revision(self, database: Literal["source", "compatibility"]) -> str:
        return self.revisions[database]

    def upgrade(self, database: Literal["source", "compatibility"], revision: str) -> None:
        self.events.append(f"upgrade:{database}:{revision}")
        self.revisions[database] = revision

    def downgrade(self, database: Literal["source", "compatibility"], revision: str) -> None:
        self.events.append(f"downgrade:{database}:{revision}")
        self.revisions[database] = revision

def _plan(release: bytes, kinds: tuple[StepKind, ...] = ("application", "database", "object_store", "configuration", "pack")) -> UpgradePlan:
    steps = tuple(
        UpgradeStep(
            kind=kind,
            resource_id=f"{kind.replace('_', '-')}-main",
            from_version="0.7.1",
            to_version="0.7.2",
            target_sha256=_digest(f"target:{kind}"),
            rollback_required=True,
            compatibility_reader=f"{kind}-reader-v1",
        )
        for kind in kinds
    )
    return UpgradePlan(
        schema="reconforge-upgrade-plan-v1",
        plan_id="UPG-SYNTHETIC-001",
        current_application_version="0.7.1",
        target_application_version="0.7.2",
        release_manifest_sha256=hashlib.sha256(release).hexdigest(),
        steps=steps,
    )


def _adapters(events: list[str], plan: UpgradePlan) -> tuple[_Adapter, ...]:
    return tuple(_Adapter(step.kind, step.resource_id, events) for step in plan.steps)


def test_preflight_all_resources_precedes_every_mutation_and_execution_is_deterministic(tmp_path: Path) -> None:
    release = b"closed synthetic release manifest"
    plan = _plan(release)
    events: list[str] = []
    adapters = _adapters(events, plan)
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", adapters)
    try:
        assert orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker") == plan.digest
        orchestrator.approve(plan, actor="checker")
        output = orchestrator.execute(plan, actor="operator")
        assert len(output) == 64
        assert orchestrator.status(plan.plan_id) == "completed"
        assert events[:5] == [f"preflight:{kind}" for kind in ("application", "database", "object_store", "configuration", "pack")]
        assert events[5:] == [item for kind in ("application", "database", "object_store", "configuration", "pack") for item in (f"apply:{kind}", f"verify:{kind}")]
        assert orchestrator.execute(plan, actor="operator") == output
        assert [event["action"] for event in orchestrator.events(plan.plan_id)] == ["prepared", "approved", "started", "completed"]
    finally:
        orchestrator.close()


def test_any_preflight_failure_produces_no_journal_and_no_mutation(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application", "database"))
    events: list[str] = []
    adapters = list(_adapters(events, plan))
    adapters[1].state = "0.6.0"
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", tuple(adapters))
    try:
        with pytest.raises(UpgradeError, match="upgrade_preflight_failed"):
            orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        assert all(adapter.state != "0.7.2" for adapter in adapters)
        with pytest.raises(UpgradeError, match="upgrade_plan_not_prepared"):
            orchestrator.status(plan.plan_id)
    finally:
        orchestrator.close()


def test_failure_rolls_back_verified_resources_in_reverse_order(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application", "database", "configuration"))
    events: list[str] = []
    adapters = list(_adapters(events, plan))
    adapters[-1].fail = True
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", tuple(adapters))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert orchestrator.status(plan.plan_id) == "rolled_back"
        assert [adapter.state for adapter in adapters] == ["0.7.1"] * 3
        assert events[-2:] == ["rollback:database", "rollback:application"]
    finally:
        orchestrator.close()


def test_uncertain_effect_is_recovered_then_rolled_back_without_double_apply(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application", "database"))
    events: list[str] = []
    adapters = list(_adapters(events, plan))
    adapters[1].fail_after_effect = True
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", tuple(adapters))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert [adapter.state for adapter in adapters] == ["0.7.1", "0.7.1"]
        assert events.count("apply:database") == 1
        assert "recover:database" in events
        assert events[-2:] == ["rollback:database", "rollback:application"]
    finally:
        orchestrator.close()


def test_unrecoverable_uncertain_effect_fails_isolation_instead_of_claiming_rollback(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application", "database"))
    events: list[str] = []
    adapters = list(_adapters(events, plan))
    adapters[1].fail_after_effect = True
    adapters[1].recoverable = False
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", tuple(adapters))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_rollback_failed_isolate_resources"):
            orchestrator.execute(plan, actor="operator")
        assert orchestrator.status(plan.plan_id) == "failed"
        assert adapters[1].state == "0.7.2"
    finally:
        orchestrator.close()


def test_release_digest_order_schema_and_plan_identity_fail_closed(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application", "database"))
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", _adapters([], plan))
    try:
        with pytest.raises(UpgradeError, match="upgrade_release_manifest_digest_mismatch"):
            orchestrator.prepare(plan, release_manifest_bytes=b"tampered", actor="maker")
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        changed = plan.model_copy(update={"release_manifest_sha256": _digest("different")})
        with pytest.raises(UpgradeError, match="upgrade_plan_identity_conflict"):
            orchestrator.prepare(changed, release_manifest_bytes=b"different", actor="maker")
    finally:
        orchestrator.close()

    with pytest.raises(ValueError):
        _plan(release, ("database", "application"))


def test_upgrade_plan_json_schema_matches_the_runtime_contract() -> None:
    schema = json.loads(Path("docs/schemas/upgrade_plan.schema.json").read_text(encoding="utf-8"))
    plan = _plan(b"manifest")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(plan.model_dump(mode="json", by_alias=True))

    expanded = plan.model_dump(mode="json", by_alias=True)
    expanded["command"] = "arbitrary executable hook"
    assert list(Draft202012Validator(schema).iter_errors(expanded))

    with pytest.raises(ValueError, match="operator application version"):
        plan.model_copy(update={"operator_application_version": "0.7.0"}).model_validate(
            plan.model_copy(update={"operator_application_version": "0.7.0"}).model_dump(by_alias=True)
        )


def test_supported_upgrade_matrix_is_closed_unique_and_cannot_claim_support_while_blocked() -> None:
    schema = json.loads(Path("docs/schemas/upgrade_supported_versions.schema.json").read_text(encoding="utf-8"))
    matrix = json.loads(Path("docs/operations/upgrade-supported-versions.v1.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(matrix)
    identities = [
        (item["resource_kind"], item["resource_id"], item["from_version"], item["to_version"])
        for item in matrix["transitions"]
    ]
    assert len(identities) == len(set(identities))
    assert {item["resource_kind"] for item in matrix["transitions"]} == {
        "application", "database", "object_store", "configuration", "pack"
    }
    if matrix["release_state"] == "supported":
        assert all(item["status"] == "verified" for item in matrix["transitions"])


def test_execution_requires_distinct_approval_and_same_actor_for_resume(tmp_path: Path) -> None:
    release = b"manifest"
    plan = _plan(release, ("application",))
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", _adapters([], plan))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        with pytest.raises(UpgradeError, match="upgrade_approval_requires_distinct_actor"):
            orchestrator.approve(plan, actor="maker")
        with pytest.raises(UpgradeError, match="upgrade_execution_requires_approval"):
            orchestrator.execute(plan, actor="operator")
        orchestrator.approve(plan, actor="checker")
        assert len(orchestrator.execute(plan, actor="operator")) == 64
    finally:
        orchestrator.close()


def test_real_sqlite_schema_upgrade_and_later_resource_failure_restore_exact_source_state(tmp_path: Path) -> None:
    database = tmp_path / "community.sqlite3"
    run_migrations(database, target_version=23)
    release = b"manifest"
    application_step = UpgradeStep(
        kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2",
        target_sha256=_digest("target:application"), rollback_required=True, compatibility_reader="wheel-reader-v1",
    )
    database_step = UpgradeStep(
        kind="database", resource_id="community-db", from_version="0.0.23", to_version="0.0.24",
        target_sha256=_digest("reconforge-sqlite-schema:24"), rollback_required=True, compatibility_reader="sqlite-schema-reader-v1",
    )
    configuration_step = UpgradeStep(
        kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2",
        target_sha256=_digest("target:configuration"), rollback_required=True, compatibility_reader="config-reader-v1",
    )
    plan = UpgradePlan(
        schema="reconforge-upgrade-plan-v1", plan_id="UPG-SQLITE-ROLLBACK-01",
        current_application_version="0.7.1", target_application_version="0.7.2",
        release_manifest_sha256=hashlib.sha256(release).hexdigest(),
        steps=(application_step, database_step, configuration_step),
    )
    events: list[str] = []
    application = _Adapter("application", "application-main", events)
    sqlite_adapter = SQLiteUpgradeAdapter(resource_id="community-db", database_path=database, recovery_dir=tmp_path / "recovery")
    configuration = _Adapter("configuration", "configuration-main", events, fail=True)
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", (application, sqlite_adapter, configuration))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert database_status(database).current_version == 23
        assert orchestrator.status(plan.plan_id) == "rolled_back"
        assert list((tmp_path / "recovery").glob("*.rollback.sqlite3"))
    finally:
        orchestrator.close()


def test_real_object_catalog_cutover_and_later_failure_restore_catalog_without_mutating_objects(tmp_path: Path) -> None:
    object_root = (tmp_path / "objects").resolve()
    store = LocalObjectStore(LocalObjectStorageSettings(root=object_root))
    first = store.put_bytes("tenant-a", "evidence/a.json", b'{"amount":"12.30"}', content_type="application/json")
    second = store.put_bytes("tenant-a", "evidence/b.bin", b"immutable-evidence")
    original_files = {path.relative_to(object_root).as_posix(): path.read_bytes() for path in object_root.rglob("*") if path.is_file()}

    catalog_root = tmp_path / "object-catalog"
    catalog_root.mkdir()
    source_digest = write_object_catalog(catalog_root / "current", object_root, version="1.0.0")
    target_digest = hashlib.sha256(build_object_catalog(object_root, version="2.0.0")).hexdigest()
    release = b"manifest"
    steps = (
        UpgradeStep(kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:application"), rollback_required=True, compatibility_reader="wheel-reader-v1"),
        UpgradeStep(kind="database", resource_id="database-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:database"), rollback_required=True, compatibility_reader="database-reader-v1"),
        UpgradeStep(kind="object_store", resource_id="objects-main", from_version="1.0.0", to_version="2.0.0", target_sha256=target_digest, rollback_required=True, compatibility_reader="local-object-catalog-v1"),
        UpgradeStep(kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:configuration"), rollback_required=True, compatibility_reader="config-reader-v1"),
    )
    plan = UpgradePlan(schema="reconforge-upgrade-plan-v1", plan_id="UPG-OBJECT-ROLLBACK-01", current_application_version="0.7.1", target_application_version="0.7.2", release_manifest_sha256=hashlib.sha256(release).hexdigest(), steps=steps)
    events: list[str] = []
    adapters = (
        _Adapter("application", "application-main", events),
        _Adapter("database", "database-main", events),
        LocalObjectCatalogUpgradeAdapter(resource_id="objects-main", object_root=object_root, deployment_root=catalog_root),
        _Adapter("configuration", "configuration-main", events, fail=True),
    )
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", adapters)
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert orchestrator.status(plan.plan_id) == "rolled_back"
        assert source_digest == hashlib.sha256(
            (catalog_root / "current" / "reconforge-object-catalog.v1.json").read_bytes()
        ).hexdigest()
        assert {path.relative_to(object_root).as_posix(): path.read_bytes() for path in object_root.rglob("*") if path.is_file()} == original_files
        assert store.get_bytes("tenant-a", "evidence/a.json").sha256 == first.sha256
        assert store.get_bytes("tenant-a", "evidence/b.bin").sha256 == second.sha256
        assert (catalog_root / "quarantine-object-catalog-2.0.0").is_dir()
    finally:
        orchestrator.close()


def test_object_catalog_preflight_rejects_tampered_content_before_any_effect(tmp_path: Path) -> None:
    object_root = (tmp_path / "objects").resolve()
    store = LocalObjectStore(LocalObjectStorageSettings(root=object_root))
    store.put_bytes("tenant-a", "evidence.bin", b"original")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    write_object_catalog(catalog_root / "current", object_root, version="1.0.0")
    target_digest = hashlib.sha256(build_object_catalog(object_root, version="2.0.0")).hexdigest()
    content = next(path for path in object_root.rglob("*") if path.is_file() and not path.name.endswith(".reconforge-object.json"))
    content.write_bytes(b"tampered")
    adapter = LocalObjectCatalogUpgradeAdapter(resource_id="objects-main", object_root=object_root, deployment_root=catalog_root)
    step = UpgradeStep(kind="object_store", resource_id="objects-main", from_version="1.0.0", to_version="2.0.0", target_sha256=target_digest, rollback_required=True, compatibility_reader="local-object-catalog-v1")
    with pytest.raises(UpgradeError, match="object_catalog_content_integrity_failed"):
        adapter.preflight(step)
    assert not list(catalog_root.glob("stage-*"))


def test_postgres_encrypted_restore_drill_upgrade_and_later_failure_downgrade_source(tmp_path: Path) -> None:
    backup = _PostgresBackup()
    migrations = _PostgresMigrations()
    database = PostgreSQLUpgradeAdapter(
        resource_id="postgres-main",
        backup=cast(PostgresNativeBackupAdapter, backup),
        migration_runner=migrations,
        supported_versions={"0.0.52": "0052_security_governance", "0.0.53": "0053_audit_administration_acl"},
        recovery_dir=tmp_path / "recovery",
        backup_key=bytes(range(32)),
    )
    release = b"manifest"
    steps = (
        UpgradeStep(kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:application"), rollback_required=True, compatibility_reader="wheel-reader-v1"),
        UpgradeStep(kind="database", resource_id="postgres-main", from_version="0.0.52", to_version="0.0.53", target_sha256=postgres_revision_digest("0053_audit_administration_acl"), rollback_required=True, compatibility_reader="postgres-alembic-restore-v1"),
        UpgradeStep(kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:configuration"), rollback_required=True, compatibility_reader="config-reader-v1"),
    )
    plan = UpgradePlan(schema="reconforge-upgrade-plan-v1", plan_id="UPG-POSTGRES-ROLLBACK", current_application_version="0.7.1", target_application_version="0.7.2", release_manifest_sha256=hashlib.sha256(release).hexdigest(), steps=steps)
    events: list[str] = []
    orchestrator = UpgradeOrchestrator(
        tmp_path / "journal.sqlite3",
        (_Adapter("application", "application-main", events), database, _Adapter("configuration", "configuration-main", events, fail=True)),
    )
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        assert backup.restore_count == 1
        assert backup.cleanup_count == 1
        assert migrations.revisions["compatibility"] == "0053_audit_administration_acl"
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert migrations.revisions["source"] == "0052_security_governance"
        assert migrations.events[-1] == "downgrade:source:0052_security_governance"
        assert list((tmp_path / "recovery").glob("*.rfpgbackup"))
        assert orchestrator.status(plan.plan_id) == "rolled_back"
    finally:
        orchestrator.close()


def test_postgres_receipt_detects_backup_tamper_and_native_runner_keeps_dsn_out_of_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _PostgresBackup()
    migrations = _PostgresMigrations()
    adapter = PostgreSQLUpgradeAdapter(
        resource_id="postgres-main",
        backup=cast(PostgresNativeBackupAdapter, backup),
        migration_runner=migrations,
        supported_versions={"0.0.52": "0052_security_governance", "0.0.53": "0053_audit_administration_acl"},
        recovery_dir=tmp_path / "recovery",
        backup_key=bytes(range(32)),
    )
    step = UpgradeStep(kind="database", resource_id="postgres-main", from_version="0.0.52", to_version="0.0.53", target_sha256=postgres_revision_digest("0053_audit_administration_acl"), rollback_required=True, compatibility_reader="postgres-alembic-restore-v1")
    evidence = adapter.preflight(step)
    receipt = adapter.apply(step, evidence)
    artifact = next((tmp_path / "recovery").glob("*.rfpgbackup"))
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(UpgradeError, match="verification_failed"):
        adapter.verify(step, receipt)

    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> object:
        calls.append((argv, kwargs))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(postgres_upgrade_module.subprocess, "run", fake_run)
    runner = PsycopgAlembicMigrationRunner(
        source_dsn="postgresql://operator:secret@127.0.0.1/source",
        compatibility_dsn="postgresql://operator:secret@127.0.0.1/compatibility",
        python_executable=Path(sys.executable).resolve(strict=True),
        alembic_ini=Path("alembic.ini").resolve(strict=True),
    )
    runner.upgrade("source", "0053_audit_administration_acl")
    argv, kwargs = calls[0]
    assert all("secret" not in item for item in argv)
    assert argv[0].lower().endswith(("/alembic", "\\alembic", "/alembic.exe", "\\alembic.exe"))
    assert argv[1:] == ("-c", str(Path("alembic.ini").resolve()), "upgrade", "0053_audit_administration_acl")
    assert kwargs["shell"] is False
    assert cast(dict[str, str], kwargs["env"])["RECONFORGE_POSTGRES_DSN"].endswith("/source")


def test_real_offline_wheel_cutover_and_later_failure_restore_source_with_target_quarantine(tmp_path: Path) -> None:
    deployment = tmp_path / "application"
    current = deployment / "current"
    (current / "reconforge").mkdir(parents=True)
    (current / "reconforge" / "__init__.py").write_text('__version__ = "0.7.1"\n', encoding="utf-8")
    write_deployment_marker(current, version="0.7.1", artifact_sha256=_digest("source-wheel"))
    wheel = tmp_path / "reconforge_erp-0.7.2-py3-none-any.whl"
    wheel_digest = _build_minimal_wheel(wheel, "0.7.2")
    release = b"manifest"
    application_step = UpgradeStep(
        kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2",
        target_sha256=wheel_digest, rollback_required=True, compatibility_reader="wheel-import-v1",
    )
    configuration_step = UpgradeStep(
        kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2",
        target_sha256=_digest("target:configuration"), rollback_required=True, compatibility_reader="config-reader-v1",
    )
    plan = UpgradePlan(
        schema="reconforge-upgrade-plan-v1", plan_id="UPG-WHEEL-ROLLBACK-01",
        current_application_version="0.7.1", target_application_version="0.7.2",
        release_manifest_sha256=hashlib.sha256(release).hexdigest(), steps=(application_step, configuration_step),
    )
    events: list[str] = []
    application = PythonWheelApplicationAdapter(resource_id="application-main", deployment_root=deployment, wheel_path=wheel)
    configuration = _Adapter("configuration", "configuration-main", events, fail=True)
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", (application, configuration))
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert '__version__ = "0.7.1"' in (current / "reconforge" / "__init__.py").read_text(encoding="utf-8")
        quarantines = list(deployment.glob("quarantine-rolled-back-target-0.7.2-*"))
        assert len(quarantines) == 1
        assert '__version__ = "0.7.2"' in (quarantines[0] / "reconforge" / "__init__.py").read_text(encoding="utf-8")
    finally:
        orchestrator.close()


def test_real_application_and_configuration_cutover_roll_back_when_pack_fails(tmp_path: Path) -> None:
    app_root = tmp_path / "application"
    app_current = app_root / "current"
    (app_current / "reconforge").mkdir(parents=True)
    (app_current / "reconforge" / "__init__.py").write_text('__version__ = "0.7.1"\n', encoding="utf-8")
    write_deployment_marker(app_current, version="0.7.1", artifact_sha256=_digest("source-wheel"))
    wheel = tmp_path / "reconforge_erp-0.7.2-py3-none-any.whl"
    wheel_digest = _build_minimal_wheel(wheel, "0.7.2")

    config_root = tmp_path / "configuration"
    config_current = config_root / "current"
    config_current.mkdir(parents=True)
    (config_current / "reconforge.yml").write_text("amount_tolerance: '2.00'\noutput_currency: USD\n", encoding="utf-8")
    source_config_digest = write_configuration_marker(config_current, version="0.7.1")
    target_config = tmp_path / "target-reconforge.yml"
    target_config.write_text("amount_tolerance: '1.25'\noutput_currency: EUR\n", encoding="utf-8")
    target_config_digest = hashlib.sha256(target_config.read_bytes()).hexdigest()

    release = b"manifest"
    steps = (
        UpgradeStep(kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2", target_sha256=wheel_digest, rollback_required=True, compatibility_reader="wheel-import-v1"),
        UpgradeStep(kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2", target_sha256=target_config_digest, rollback_required=True, compatibility_reader="config-v1-reader"),
        UpgradeStep(kind="pack", resource_id="pack-main", from_version="0.7.1", to_version="0.7.2", target_sha256=_digest("target:pack"), rollback_required=True, compatibility_reader="pack-reader-v1"),
    )
    plan = UpgradePlan(schema="reconforge-upgrade-plan-v1", plan_id="UPG-APP-CONFIG-ROLLBACK", current_application_version="0.7.1", target_application_version="0.7.2", release_manifest_sha256=hashlib.sha256(release).hexdigest(), steps=steps)
    events: list[str] = []
    adapters = (
        PythonWheelApplicationAdapter(resource_id="application-main", deployment_root=app_root, wheel_path=wheel),
        ConfigurationUpgradeAdapter(resource_id="configuration-main", deployment_root=config_root, target_config=target_config),
        _Adapter("pack", "pack-main", events, fail=True),
    )
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", adapters)
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        with pytest.raises(UpgradeError, match="upgrade_execution_failed_and_rolled_back"):
            orchestrator.execute(plan, actor="operator")
        assert _digest("source-wheel") in (app_current / "reconforge-deployment.v1.json").read_text(encoding="ascii")
        assert source_config_digest in (config_current / "reconforge-config-deployment.v1.json").read_text(encoding="ascii")
        assert "2.00" in (config_current / "reconforge.yml").read_text(encoding="utf-8")
        assert (config_root / "quarantine-config-0.7.2" / "reconforge.yml").is_file()
    finally:
        orchestrator.close()


def test_signed_pack_adapter_installs_preapproved_target_and_restores_prior_version(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    first, registry = _verified_pack(tmp_path / "pack-1.json", private_key, "1.0.0")
    second, _ = _verified_pack(tmp_path / "pack-2.json", private_key, "1.1.0")
    store = PackLifecycleStore(tmp_path / "packs.sqlite3", trusted_registry=registry)
    try:
        store.submit(first, actor="maker")
        store.approve("upgrade-pack", "1.0.0", actor="checker")
        store.install("upgrade-pack", "1.0.0", actor="operator")
        store.submit(second, actor="maker")
        store.approve("upgrade-pack", "1.1.0", actor="checker")
        target = store.get("upgrade-pack", "1.1.0")
        step = UpgradeStep(
            kind="pack", resource_id="upgrade-pack", from_version="1.0.0", to_version="1.1.0",
            target_sha256=target.content_digest, rollback_required=True, compatibility_reader="signed-pack-v1-reader",
        )
        adapter = SignedPackUpgradeAdapter(resource_id="upgrade-pack", store=store, actor="upgrade-operator")
        evidence = adapter.preflight(step)
        receipt = adapter.apply(step, evidence)
        assert adapter.verify(step, receipt) == target.content_digest
        assert store.get("upgrade-pack", "1.1.0").status == "enabled"
        assert adapter.rollback(step, receipt) == evidence.source_digest
        assert store.get("upgrade-pack", "1.0.0").status == "enabled"
        assert store.get("upgrade-pack", "1.1.0").status == "disabled"
    finally:
        store.close()


def test_all_five_real_local_adapters_complete_one_ordered_upgrade_plan(tmp_path: Path) -> None:
    app_root = tmp_path / "application"
    app_current = app_root / "current"
    (app_current / "reconforge").mkdir(parents=True)
    (app_current / "reconforge" / "__init__.py").write_text('__version__ = "0.7.1"\n', encoding="utf-8")
    write_deployment_marker(app_current, version="0.7.1", artifact_sha256=_digest("source-wheel"))
    wheel = tmp_path / "reconforge_erp-0.7.2-py3-none-any.whl"
    wheel_digest = _build_minimal_wheel(wheel, "0.7.2")

    database_path = tmp_path / "community.sqlite3"
    run_migrations(database_path, target_version=23)

    object_root = (tmp_path / "objects").resolve()
    object_store = LocalObjectStore(LocalObjectStorageSettings(root=object_root))
    stored = object_store.put_bytes("tenant-a", "upgrade-evidence.json", b'{"source":"synthetic"}')
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    write_object_catalog(catalog_root / "current", object_root, version="1.0.0")
    object_target_digest = hashlib.sha256(build_object_catalog(object_root, version="2.0.0")).hexdigest()

    config_root = tmp_path / "configuration"
    config_current = config_root / "current"
    config_current.mkdir(parents=True)
    (config_current / "reconforge.yml").write_text("amount_tolerance: '2.00'\noutput_currency: USD\n", encoding="utf-8")
    write_configuration_marker(config_current, version="0.7.1")
    target_config = tmp_path / "target-reconforge.yml"
    target_config.write_text("amount_tolerance: '1.25'\noutput_currency: EUR\n", encoding="utf-8")

    private_key = Ed25519PrivateKey.generate()
    first, registry = _verified_pack(tmp_path / "pack-1.json", private_key, "1.0.0")
    second, _ = _verified_pack(tmp_path / "pack-2.json", private_key, "1.1.0")
    pack_store = PackLifecycleStore(tmp_path / "packs.sqlite3", trusted_registry=registry)
    pack_store.submit(first, actor="pack-maker")
    pack_store.approve("upgrade-pack", "1.0.0", actor="pack-checker")
    pack_store.install("upgrade-pack", "1.0.0", actor="pack-operator")
    pack_store.submit(second, actor="pack-maker")
    pack_store.approve("upgrade-pack", "1.1.0", actor="pack-checker")
    pack_target_digest = pack_store.get("upgrade-pack", "1.1.0").content_digest

    release = b"five-real-local-adapter-manifest"
    steps = (
        UpgradeStep(kind="application", resource_id="application-main", from_version="0.7.1", to_version="0.7.2", target_sha256=wheel_digest, rollback_required=True, compatibility_reader="wheel-import-v1"),
        UpgradeStep(kind="database", resource_id="community-db", from_version="0.0.23", to_version="0.0.24", target_sha256=_digest("reconforge-sqlite-schema:24"), rollback_required=True, compatibility_reader="sqlite-schema-reader-v1"),
        UpgradeStep(kind="object_store", resource_id="objects-main", from_version="1.0.0", to_version="2.0.0", target_sha256=object_target_digest, rollback_required=True, compatibility_reader="local-object-catalog-v1"),
        UpgradeStep(kind="configuration", resource_id="configuration-main", from_version="0.7.1", to_version="0.7.2", target_sha256=hashlib.sha256(target_config.read_bytes()).hexdigest(), rollback_required=True, compatibility_reader="config-v1-reader"),
        UpgradeStep(kind="pack", resource_id="upgrade-pack", from_version="1.0.0", to_version="1.1.0", target_sha256=pack_target_digest, rollback_required=True, compatibility_reader="signed-pack-v1-reader"),
    )
    plan = UpgradePlan(schema="reconforge-upgrade-plan-v1", plan_id="UPG-FIVE-REAL-LOCAL", current_application_version="0.7.1", target_application_version="0.7.2", release_manifest_sha256=hashlib.sha256(release).hexdigest(), steps=steps)
    adapters = (
        PythonWheelApplicationAdapter(resource_id="application-main", deployment_root=app_root, wheel_path=wheel),
        SQLiteUpgradeAdapter(resource_id="community-db", database_path=database_path, recovery_dir=tmp_path / "db-recovery"),
        LocalObjectCatalogUpgradeAdapter(resource_id="objects-main", object_root=object_root, deployment_root=catalog_root),
        ConfigurationUpgradeAdapter(resource_id="configuration-main", deployment_root=config_root, target_config=target_config),
        SignedPackUpgradeAdapter(resource_id="upgrade-pack", store=pack_store, actor="upgrade-operator"),
    )
    orchestrator = UpgradeOrchestrator(tmp_path / "journal.sqlite3", adapters)
    try:
        orchestrator.prepare(plan, release_manifest_bytes=release, actor="maker")
        orchestrator.approve(plan, actor="checker")
        assert len(orchestrator.execute(plan, actor="operator")) == 64
        assert orchestrator.status(plan.plan_id) == "completed"
        assert database_status(database_path).current_version == 24
        assert object_store.get_bytes("tenant-a", "upgrade-evidence.json").sha256 == stored.sha256
        assert "1.25" in (config_root / "current" / "reconforge.yml").read_text(encoding="utf-8")
        assert pack_store.get("upgrade-pack", "1.1.0").status == "enabled"
    finally:
        orchestrator.close()
        pack_store.close()
