from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.application.audit_browsing import (
    AuditBrowsingApplicationService,
    AuditBrowsingError,
    AuditChainVerification,
    AuditVerificationSummary,
    RedactedAuditEvent,
)
from reconforge.infrastructure.postgres_audit_browsing import PostgresAuditBrowsingRepository


def _event(*, event_id: str = "AE-1", source: str = "domain") -> RedactedAuditEvent:
    return RedactedAuditEvent(  # type: ignore[arg-type]
        source,
        event_id,
        1,
        "2026-07-30T00:00:00Z",
        "object.updated",
        "object",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        None,
        None,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_redacted_events(self, **kwargs: object) -> tuple[RedactedAuditEvent, ...]:
        self.calls.append(kwargs)
        return (_event(event_id="AE-1"), _event(event_id="AE-2"))

    def verify_chains(self) -> AuditVerificationSummary:
        chains = (
            AuditChainVerification("domain", True, 1, "a" * 64, ()),
            AuditChainVerification("ledger_control", True, 1, "b" * 64, ()),
        )
        return AuditVerificationSummary(True, chains)


def test_audit_browsing_bounds_pages_and_requires_both_chain_results() -> None:
    repository = _Repository()
    service = AuditBrowsingApplicationService(repository)

    page = service.list_events(limit=1)
    verification = service.verify()

    assert page.events == (_event(event_id="AE-1"),)
    assert page.has_more is True
    assert repository.calls == [
        {
            "limit": 2,
            "after_occurred_at": None,
            "after_source": None,
            "after_event_id": None,
        }
    ]
    assert verification.ok is True
    with pytest.raises(AuditBrowsingError, match="incomplete"):
        service.list_events(limit=1, after_occurred_at="2026-07-30T00:00:00Z")


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...]) -> _Cursor:
        self.calls.append((sql, parameters))
        return _Cursor(
            [
                {
                    "source": "domain",
                    "event_id": "AE-1",
                    "sequence": 1,
                    "occurred_at": "2026-07-30T00:00:00Z",
                    "action": "identity.user.disabled",
                    "object_type": "identity_user",
                    "actor_user_id": "sensitive-user-id",
                    "actor_label": "Sensitive Operator",
                    "object_id": "sensitive-object-id",
                    "metadata_text": "{}",
                    "previous_event_hash": "a" * 64,
                    "event_hash": "b" * 64,
                    "before_state_hash": None,
                    "after_state_hash": "c" * 64,
                }
            ]
        )


def test_postgres_audit_browse_projection_redacts_sensitive_values_and_uses_bound_query() -> None:
    connection = _Connection()
    records = PostgresAuditBrowsingRepository(connection, "tenant-a").list_redacted_events(limit=2)

    assert len(records) == 1
    event = records[0]
    assert event.actor_digest != "sensitive-user-id"
    assert event.object_digest != "sensitive-object-id"
    assert event.metadata_digest == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    assert "Sensitive" not in str(event)
    sql, parameters = connection.calls[0]
    assert parameters == ("tenant-a", "tenant-a", None, None, None, None, 2)
    assert "reason" not in sql.casefold()
    assert "request_id" not in sql.casefold()
    assert "SELECT *" not in sql.upper()


def test_audit_administration_docs_and_package_manifest_bind_the_disclosure_contract() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    adr = Path("docs/adr/0198-consolidated-audit-browsing-is-redacted-and-chain-specific.md").read_text(
        encoding="utf-8"
    )
    runbook = Path("docs/operations/audit-administration.md").read_text(encoding="utf-8")

    assert "include docs/adr/0198-consolidated-audit-browsing-is-redacted-and-chain-specific.md" in manifest
    assert "include docs/operations/audit-administration.md" in manifest
    assert "no global hash-chain claim" in adr
    for required_text in ("raw actor IDs and labels", "object IDs", "request IDs", "reasons", "metadata"):
        assert required_text in runbook
