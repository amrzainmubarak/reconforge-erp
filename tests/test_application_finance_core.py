from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from reconforge.application.finance_core import (
    FinanceCoreApplicationService,
    FinanceCoreRepositoryProtocol,
    FinanceCoreSummary,
)


class _RecordingFinanceRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

    def create_entry(
        self,
        *,
        entry_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        journal_code: str,
        posting_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        external_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.operation = "create_entry"
        self.arguments = {
            "entry_number": entry_number,
            "organization_code": organization_code,
            "entity_code": entity_code,
            "period_id": period_id,
            "journal_code": journal_code,
            "posting_date": posting_date,
            "description": description,
            "lines": lines,
            "workspace": workspace,
            "external_reference": external_reference,
            "source_type": source_type,
            "actor_label": actor_label,
        }
        return {"id": "entry-1", "lines": list(lines)}

    def validate_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.operation = "validate_entry"
        self.arguments = {"entry_id": entry_id, "reason": reason, "actor_label": actor_label}
        return {"id": entry_id, "status": "Validated"}

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> FinanceCoreSummary:
        self.operation = "summary"
        self.arguments = {"workspace": workspace, "actor_label": actor_label}
        return FinanceCoreSummary(workspace, 1, 2, 3, 4, 5, 6, 7, 8)


def _service(repository: _RecordingFinanceRepository) -> FinanceCoreApplicationService:
    return FinanceCoreApplicationService(cast(FinanceCoreRepositoryProtocol, repository))


def test_finance_application_preserves_exact_line_values_and_governance_context() -> None:
    repository = _RecordingFinanceRepository()
    service = _service(repository)
    lines = (
        {"account_code": "1100", "debit": "999999999999.123456", "credit": "0"},
        {"account_code": "2100", "debit": "0", "credit": "999999999999.123456"},
    )

    result = service.create_entry(
        entry_number="JE/2026/PORT",
        organization_code="ORG",
        entity_code="ENTITY",
        period_id="period-1",
        journal_code="GJ",
        posting_date="2026-07-28",
        description="Exact application boundary",
        lines=lines,
        workspace="regulated",
        external_reference="source-9",
        source_type="Imported",
        actor_label="maker@example.test",
    )

    assert repository.operation == "create_entry"
    assert repository.arguments["lines"] is lines
    assert result["lines"][0]["debit"] == "999999999999.123456"
    assert repository.arguments["actor_label"] == "maker@example.test"
    assert repository.arguments["workspace"] == "regulated"


def test_finance_application_delegates_governed_transition_and_typed_summary() -> None:
    repository = _RecordingFinanceRepository()
    service = _service(repository)

    assert (
        service.validate_entry("entry-1", reason="Independent review", actor_label="checker@example.test")["status"]
        == "Validated"
    )
    assert repository.arguments == {
        "entry_id": "entry-1",
        "reason": "Independent review",
        "actor_label": "checker@example.test",
    }
    assert service.summary(workspace="regulated", actor_label="auditor").to_dict() == {
        "workspace": "regulated",
        "charts": 1,
        "accounts": 2,
        "dimensions": 3,
        "dimension_values": 4,
        "journals": 5,
        "draft_entries": 6,
        "validated_entries": 7,
        "voided_entries": 8,
    }


def test_finance_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/finance_core.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)
