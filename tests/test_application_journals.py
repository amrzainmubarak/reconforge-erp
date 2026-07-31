"""Contract tests for the backend-neutral journal control boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reconforge.application.journals import JournalControlApplicationService, JournalImportResult


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def import_journals(self, input_path: Path | str, **values: Any) -> JournalImportResult:
        self.calls.append(("import", (input_path, values)))
        return JournalImportResult(source_path=Path(input_path), imported_rows=2)

    def policy_run(self, **values: Any) -> int:
        self.calls.append(("policy", values))
        return 7

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]:
        self.calls.append(("exceptions", period_name))
        return [{"id": "JEX-1", "period_name": period_name}]

    def report(self) -> dict[str, Any]:
        self.calls.append(("report", {}))
        return {"journal_entries": 2, "journal_exceptions": 7, "high_risk_exceptions": 5}


def test_journal_application_service_preserves_complete_contract(tmp_path: Path) -> None:
    repository = _Repository()
    service = JournalControlApplicationService(repository)
    source = tmp_path / "journals.csv"

    imported = service.import_journals(
        source, workspace="finance", default_period="2026-07", default_entity="EG01", actor_label="preparer"
    )
    count = service.policy_run(
        workspace="finance", period_name="2026-07", period_end="2026-07-31",
        high_value_threshold="1000.00", high_risk_accounts="9999", actor_label="reviewer",
    )
    exceptions = service.exceptions(period_name="2026-07")
    report = service.report()

    assert imported == JournalImportResult(source_path=source, imported_rows=2)
    assert count == 7
    assert exceptions == [{"id": "JEX-1", "period_name": "2026-07"}]
    assert report["high_risk_exceptions"] == 5
    assert [name for name, _ in repository.calls] == ["import", "policy", "exceptions", "report"]


def test_journal_application_module_has_no_database_or_adapter_import() -> None:
    source = Path("reconforge/application/journals.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "reconforge.infrastructure" not in source
