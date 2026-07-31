from __future__ import annotations

from pathlib import Path

from reconforge.db.connection import connect
from reconforge.db.migrations import run_migrations
from reconforge.infrastructure.sqlite_matching import SQLiteMatchingRepository


def _connection(path: Path):
    run_migrations(path)
    return connect(path, require_exists=True)


def test_pure_match_path_uses_injected_currency_precision_port_without_sql_lookup(tmp_path: Path) -> None:
    connection = _connection(tmp_path / "precision-port.db")
    calls: list[str] = []

    def resolve_currency(code: str) -> tuple[int | None, str | None]:
        calls.append(code)
        return (3, None) if code == "KWD" else (None, "UNKNOWN_CURRENCY")

    repository = SQLiteMatchingRepository(connection, currency_precision_resolver=resolve_currency)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        output = repository.match_records(
            left_records=[{"id": "L1", "reference": "REF", "amount": "1.001", "currency": "KWD", "date": "2026-07-28"}],
            right_records=[
                {"id": "R1", "reference": "REF", "amount": "1.001", "currency": "KWD", "date": "2026-07-28"}
            ],
        )
    finally:
        connection.close()

    assert [result["status"] for result in output.results] == ["Matched"]
    assert calls == ["KWD"]
    assert not any("FROM currencies" in statement for statement in statements)


def test_injected_currency_port_preserves_data_quality_exception_for_unknown_currency(tmp_path: Path) -> None:
    connection = _connection(tmp_path / "unknown-currency.db")
    repository = SQLiteMatchingRepository(
        connection,
        currency_precision_resolver=lambda _code: (None, "UNKNOWN_CURRENCY"),
    )
    try:
        output = repository.match_records(
            left_records=[{"id": "L1", "reference": "REF", "amount": "1.00", "currency": "ZZZ", "date": "2026-07-28"}],
            right_records=[{"id": "R1", "reference": "REF", "amount": "1.00", "currency": "ZZZ", "date": "2026-07-28"}],
        )
    finally:
        connection.close()

    assert not any(result["status"] == "Matched" for result in output.results)
    assert any(exception["reason_code"] == "UNKNOWN_CURRENCY" for exception in output.exceptions)
