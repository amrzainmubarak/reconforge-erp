from __future__ import annotations

import ast
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from reconforge.infrastructure import postgres_close as close_module
from reconforge.infrastructure import postgres_evidence as evidence_module
from reconforge.infrastructure import postgres_ledger as ledger_module
from reconforge.infrastructure import postgres_master_data as master_data_module
from reconforge.infrastructure import postgres_reconciliation as reconciliation_module
from reconforge.infrastructure.postgres_outbox import (
    PostgresOutboxIntegrityError,
    PostgresOutboxRepository,
)
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    POSTGRES_OUTBOX_JSON_POLICY,
    POSTGRES_OUTBOX_JSON_PROFILE,
    POSTGRES_OUTBOX_PAYLOAD_SCHEMA,
    PersistedJsonError,
    decode_postgres_outbox_payload,
    encode_postgres_outbox_payload,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker, PostgresOutboxWorkerError

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_outbox_payload_round_trip_is_canonical_and_schema_valid() -> None:
    payload = {"entry_id": "entry-a", "line_count": 2, "display_ratio": 1.25}

    encoded = encode_postgres_outbox_payload(payload)
    decoded = decode_postgres_outbox_payload('{"line_count": 2, "entry_id": "entry-a", "display_ratio": 1.25}')
    mapping = decode_postgres_outbox_payload(payload)
    schema = json.loads((ROOT / "docs/schemas/postgres_outbox_payload.schema.json").read_text(encoding="utf-8"))

    assert encoded.text == '{"display_ratio":1.25,"entry_id":"entry-a","line_count":2}'
    assert decoded.payload == payload
    assert mapping.text == encoded.text
    assert decoded.profile_id == POSTGRES_OUTBOX_JSON_PROFILE
    assert decoded.schema_id == POSTGRES_OUTBOX_PAYLOAD_SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decoded.payload)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"id":"one","id":"two"}', "persisted_json_duplicate_key"),
        ('{"value":NaN}', "persisted_document_non_finite_number"),
        ('{"value":Infinity}', "persisted_document_non_finite_number"),
        ('[]', "persisted_json_object_required"),
    ],
)
def test_postgres_outbox_payload_rejects_ambiguous_or_invalid_stored_values(text: str, code: str) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decode_postgres_outbox_payload(text)
    assert captured.value.code == code


def test_postgres_outbox_payload_enforces_runtime_resource_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_OUTBOX_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16, max_nodes=4, max_depth=2),
    )

    with pytest.raises(PersistedJsonError):
        encode_postgres_outbox_payload({"value": "exceeds-budget"})
    with pytest.raises(PersistedJsonError):
        decode_postgres_outbox_payload('{"nested":{"value":"x"}}')


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _CorruptOutboxConnection:
    def execute(self, _: str, __: tuple[object, ...]) -> _Rows:
        return _Rows(
            [
                (
                    "tenant_a",
                    "evt-1",
                    "ledger.entry_posted",
                    "ledger_entry",
                    "entry-a",
                    '[{"not":"an-object"}]',
                    "Pending",
                    0,
                    "2026-07-26T00:00:00Z",
                    None,
                    None,
                    None,
                    None,
                    "2026-07-26T00:00:00Z",
                )
            ]
        )


class _CorruptWorkerConnection(_CorruptOutboxConnection):
    def __init__(self) -> None:
        self.commits = 0

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def close(self) -> None:
        return None


class _CorruptWorkerFactory:
    def __init__(self, connection: _CorruptWorkerConnection) -> None:
        self.connection = connection

    def connect(self) -> _CorruptWorkerConnection:
        return self.connection


def test_postgres_outbox_list_refuses_corrupt_payload_without_sentinel() -> None:
    repository = PostgresOutboxRepository(_CorruptOutboxConnection())

    with pytest.raises(PostgresOutboxIntegrityError, match="Stored outbox payload is invalid"):
        repository.list_events(tenant_id="tenant_a", status="all")


def test_corrupt_claim_rolls_back_before_external_publisher_receives_event() -> None:
    connection = _CorruptWorkerConnection()
    published: list[str] = []
    worker = PostgresOutboxWorker(
        _CorruptWorkerFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda event: published.append(event.id),
        settings=OutboxWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
    )

    with pytest.raises(PostgresOutboxWorkerError, match="failed safely"):
        worker.process_once()

    assert published == []
    assert connection.commits == 0


def test_all_postgres_outbox_producer_helpers_share_runtime_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "POSTGRES_OUTBOX_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=8),
    )
    payload = {"value": "too-large"}

    with pytest.raises(ledger_module.PostgresLedgerValidationError, match="outbox payload"):
        ledger_module._outbox_json_text(payload)
    with pytest.raises(master_data_module.PostgresMasterDataValidationError, match="outbox payload"):
        master_data_module._outbox_json_text(payload)
    with pytest.raises(close_module.PostgresCloseValidationError, match="outbox payload"):
        close_module._outbox_json_text(payload)
    with pytest.raises(evidence_module.PostgresEvidenceValidationError, match="outbox payload"):
        evidence_module._outbox_json_text(payload)
    with pytest.raises(reconciliation_module.PostgresReconciliationValidationError, match="outbox payload"):
        reconciliation_module.PostgresReconciliationRepository._outbox_payload_text(payload)


def test_all_postgres_audit_producer_helpers_share_audit_metadata_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "AUDIT_METADATA_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=8),
    )
    metadata = {"value": "too-large"}

    with pytest.raises(ledger_module.PostgresLedgerValidationError, match="metadata"):
        ledger_module._json_text(metadata, "metadata")
    with pytest.raises(master_data_module.PostgresMasterDataValidationError, match="metadata"):
        master_data_module._json_text(metadata, "metadata")
    with pytest.raises(ledger_module.PostgresLedgerValidationError, match="metadata"):
        close_module._json_text(metadata, "metadata")
    with pytest.raises(evidence_module.PostgresEvidenceValidationError, match="metadata"):
        evidence_module._json_text(metadata, "metadata")
    with pytest.raises(reconciliation_module.PostgresReconciliationValidationError, match="metadata"):
        reconciliation_module.PostgresReconciliationRepository._audit_metadata_text(metadata)


def test_postgres_outbox_insert_functions_have_no_direct_json_encoder() -> None:
    forbidden: list[str] = []
    governed: dict[str, int] = {}
    expected = {
        "reconforge/infrastructure/postgres_ledger.py": 2,
        "reconforge/infrastructure/postgres_master_data.py": 1,
        "reconforge/infrastructure/postgres_close.py": 1,
        "reconforge/infrastructure/postgres_evidence.py": 1,
        "reconforge/infrastructure/postgres_reconciliation.py": 1,
    }
    for relative in expected:
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if "INSERT INTO reconforge.outbox_events" not in (ast.get_source_segment(source, function) or ""):
                continue
            governed[relative] = governed.get(relative, 0) + sum(
                ast.unparse(call.func).endswith(("_outbox_json_text", "_outbox_payload_text"))
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
            )
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                if ast.unparse(call.func) in {"json.dumps", "json.loads"}:
                    forbidden.append(f"{relative}:{function.name}:{call.lineno}")
    assert forbidden == []
    assert governed == expected


def test_all_postgres_audit_insert_functions_use_bounded_metadata_encoder() -> None:
    governed: dict[str, int] = {}
    expected = {
        "reconforge/infrastructure/postgres_ledger.py": 2,
        "reconforge/infrastructure/postgres_master_data.py": 1,
        "reconforge/infrastructure/postgres_close.py": 1,
        "reconforge/infrastructure/postgres_evidence.py": 2,
        "reconforge/infrastructure/postgres_reconciliation.py": 1,
    }
    for relative in expected:
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if "INSERT INTO reconforge.audit_events" not in (ast.get_source_segment(source, function) or ""):
                continue
            governed[relative] = governed.get(relative, 0) + sum(
                ast.unparse(call.func) in {"_json_text", "self._audit_metadata_text"}
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
            )
    assert governed == expected


def test_postgres_outbox_policy_has_explicit_resource_ceilings() -> None:
    assert POSTGRES_OUTBOX_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    assert POSTGRES_OUTBOX_JSON_POLICY.max_nodes == 100_000
    assert POSTGRES_OUTBOX_JSON_POLICY.max_depth == 32
    assert POSTGRES_OUTBOX_JSON_POLICY.max_collection_items == 25_000
    assert POSTGRES_OUTBOX_JSON_POLICY.max_scalar_characters == 256 * 1024
