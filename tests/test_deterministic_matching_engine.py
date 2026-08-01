from __future__ import annotations

import ast
from pathlib import Path

from reconforge.application.matching import DeterministicMatchingEngineProtocol
from reconforge.db.connection import connect
from reconforge.db.migrations import run_migrations
from reconforge.infrastructure.sqlite_matching import SQLiteMatchingRepository
from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine


def _currency_precision(code: str) -> tuple[int | None, str | None]:
    return (3, None) if code == "KWD" else (None, "UNKNOWN_CURRENCY")


def _require_engine_contract(engine: DeterministicMatchingEngineProtocol) -> None:
    assert callable(engine.match_records)


def _records() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    left = [
        {"id": "L2", "reference": "B", "amount": "2.002", "currency": "KWD", "date": "2026-07-29"},
        {"id": "L1", "reference": "A", "amount": "1.001", "currency": "KWD", "date": "2026-07-28"},
    ]
    right = [
        {"id": "R1", "reference": "A", "amount": "1.001", "currency": "KWD", "date": "2026-07-28"},
        {"id": "R2", "reference": "B", "amount": "2.002", "currency": "KWD", "date": "2026-07-29"},
    ]
    return left, right


def test_engine_module_has_no_database_or_infrastructure_import() -> None:
    source_path = Path("reconforge/reconciliation/deterministic_engine.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imported
    assert not any(name.startswith("reconforge.infrastructure") for name in imported)


def test_postgres_worker_matcher_has_no_sqlite_schema_dependency() -> None:
    source_path = Path("reconforge/workers/postgres_reconciliation.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imported
    assert "reconforge.db.migrations" not in imported


def test_direct_engine_matches_sqlite_delegation_and_record_permutations(tmp_path: Path) -> None:
    database = tmp_path / "matching-engine-parity.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    repository = SQLiteMatchingRepository(
        connection,
        currency_precision_resolver=_currency_precision,
    )
    engine = DeterministicMatchingEngine(_currency_precision)
    _require_engine_contract(engine)
    left, right = _records()
    try:
        delegated = repository.match_records(left_records=left, right_records=right)
    finally:
        connection.close()

    direct = engine.match_records(left_records=left, right_records=right)
    permuted = engine.match_records(
        left_records=list(reversed(left)),
        right_records=list(reversed(right)),
    )

    assert direct == delegated
    assert permuted == direct
    assert [result["status"] for result in direct.results] == ["Matched", "Matched"]
