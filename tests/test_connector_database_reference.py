from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from pydantic import ValidationError

from reconforge.connectors.database_reference import (
    DatabaseQueryProfile,
    DatabaseRecordRow,
    DatabaseTransport,
    ReferenceDatabaseConnector,
    database_reference_registration,
)
from reconforge.connectors.network import ConnectorNetworkError


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "secret/database"
        return b"synthetic-database-secret"


@dataclass
class _Transport(DatabaseTransport):
    rows: tuple[DatabaseRecordRow, ...]
    seen_profile: DatabaseQueryProfile | None = None

    def fetch_named(
        self,
        endpoint: str,
        *,
        tenant_id: str,
        query_profile: DatabaseQueryProfile,
        cursor: str | None,
        credential: bytes,
        maximum_rows: int,
        maximum_cell_characters: int,
    ) -> tuple[DatabaseRecordRow, ...]:
        assert endpoint == "https://db-gateway.example.test/reconforge"
        assert tenant_id == "tenant-a"
        assert cursor is None or cursor == "r-1"
        assert credential == b"synthetic-database-secret"
        assert maximum_rows == 1_000
        assert maximum_cell_characters == 16_384
        self.seen_profile = query_profile
        return self.rows


def _row(record_id: str, amount: str = "10.00", tenant_id: str = "tenant-a") -> DatabaseRecordRow:
    return DatabaseRecordRow(
        tenant_id=tenant_id,
        record_id=record_id,
        amount=amount,
        currency="USD",
        business_date=date(2026, 8, 2),
        reference=record_id,
    )


def _connector(rows: tuple[DatabaseRecordRow, ...]) -> tuple[ReferenceDatabaseConnector, _Transport]:
    transport = _Transport(rows)
    registration = database_reference_registration(credential_reference="secret/database", tenant_id="tenant-a")
    return ReferenceDatabaseConnector(transport, _Secrets(), registration), transport


def test_database_named_query_is_sorted_scoped_and_replayable() -> None:
    connector, transport = _connector((_row("r-2"), _row("r-1")))
    first = connector.read_rows(idempotency_key="db-1")
    replay = connector.read_rows(idempotency_key="db-1")
    assert [row.record_id for row in first.rows] == ["r-1", "r-2"]
    assert first.query_profile is DatabaseQueryProfile.STATEMENT_LINES_V1
    assert first.request_digest == replay.request_digest
    assert first.response_digest == replay.response_digest
    assert transport.seen_profile is DatabaseQueryProfile.STATEMENT_LINES_V1


def test_database_cursor_and_profile_are_explicit() -> None:
    transport = _Transport((_row("r-2"), _row("r-1")))
    registration = database_reference_registration(
        credential_reference="secret/database",
        tenant_id="tenant-a",
        query_profile=DatabaseQueryProfile.TRIAL_BALANCE_V1,
    )
    result = ReferenceDatabaseConnector(transport, _Secrets(), registration).read_rows(
        idempotency_key="db-2", cursor="r-1"
    )
    assert [row.record_id for row in result.rows] == ["r-2"]
    assert result.query_profile is DatabaseQueryProfile.TRIAL_BALANCE_V1


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((_row("r-1", tenant_id="tenant-b"),), "scope_mismatch"),
        ((_row("r-1"), _row("r-1")), "duplicate"),
    ],
)
def test_database_rejects_scope_duplicates_and_invalid_amounts(
    rows: tuple[DatabaseRecordRow, ...], message: str
) -> None:
    connector, _ = _connector(rows)
    with pytest.raises(ConnectorNetworkError, match=message):
        connector.read_rows(idempotency_key="db-3")


def test_database_row_rejects_nonfinite_amount() -> None:
    with pytest.raises(ValidationError, match="finite"):
        DatabaseRecordRow.model_validate(
            {
                "tenant_id": "tenant-a",
                "record_id": "r-1",
                "amount": "NaN",
                "currency": "USD",
                "business_date": "2026-08-02",
            }
        )


def test_database_rejects_free_form_profile_endpoint_and_invalid_cursor() -> None:
    registration = database_reference_registration(credential_reference="secret/database", tenant_id="tenant-a")
    with pytest.raises(ValidationError, match="exactly match"):
        registration.__class__.model_validate({**registration.model_dump(), "endpoint": "https://db.example.test/free"})
    with pytest.raises(ValidationError):
        registration.__class__.model_validate({**registration.model_dump(), "query_profile": "select * from users"})
    connector, _ = _connector(())
    with pytest.raises(ConnectorNetworkError, match="cursor"):
        connector.read_rows(idempotency_key="db-4", cursor="x" * 4097)
