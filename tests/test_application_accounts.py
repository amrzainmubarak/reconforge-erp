from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from reconforge.application.accounts import (
    AccountReconciliationApplicationService,
    ImportTrialBalanceResult,
)


class _Repository:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, operation: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((operation, args, kwargs))
        return {"operation": operation, "id": args[0] if args else kwargs.get("account_code", "")}

    def import_trial_balance(self, input_path: Path | str, **kwargs: Any) -> ImportTrialBalanceResult:
        self.calls.append(("import", (input_path,), kwargs))
        return ImportTrialBalanceResult(self.source, 3, 3)

    def create_template(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("template", **kwargs)

    def create_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("create", **kwargs)

    def prepare(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("prepare", **kwargs)

    def submit(self, reconciliation_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("submit", reconciliation_id, **kwargs)

    def review(self, reconciliation_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("review", reconciliation_id, **kwargs)

    def complete(self, reconciliation_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("complete", reconciliation_id, **kwargs)

    def roll_forward(self, **kwargs: Any) -> int:
        self.calls.append(("roll_forward", (), kwargs))
        return 2

    def list_reconciliations(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("list", (), kwargs))
        return [{"id": "AR-1"}]

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]:
        return self._call("get", reconciliation_id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        return self._call("get_template", template_id)


def test_application_delegates_complete_account_reconciliation_contract(tmp_path: Path) -> None:
    source = tmp_path / "trial-balance.csv"
    repository = _Repository(source)
    service = AccountReconciliationApplicationService(repository)

    assert service.import_trial_balance(
        source, workspace="finance", default_period="2026-08",
        default_entity="EG01", actor_label="preparer",
    ) == ImportTrialBalanceResult(source, 3, 3)
    assert service.create_template(
        account_code="1000", name="Cash", workspace="finance", risk_rating="high",
        materiality_threshold="10.25", required_evidence="statement", owner="owner",
        reviewer="reviewer", actor_label="preparer",
    )["operation"] == "template"
    assert service.create_reconciliation(
        period_name="2026-08", entity_code="EG01", account_code="1000",
        account_name="Cash", workspace="finance", balance="100.125", owner="owner",
        preparer="preparer", reviewer="reviewer", risk_rating="high",
        materiality_threshold="10.25", actor_label="preparer",
    )["operation"] == "create"
    assert service.prepare(
        reconciliation_id="AR-1", workspace="finance", period_name="2026-08",
        entity_code="EG01", account_code="1000", preparer="preparer",
        actor_label="preparer",
    )["operation"] == "prepare"
    assert service.submit("AR-1", actor_label="preparer")["operation"] == "submit"
    assert service.review("AR-1", reviewer="reviewer", actor_label="reviewer")["operation"] == "review"
    assert service.complete("AR-1", actor_label="controller")["operation"] == "complete"
    assert service.roll_forward(
        from_period="2026-08", to_period="2026-09",
        workspace="finance", actor_label="preparer",
    ) == 2
    assert service.list_reconciliations(
        status="Draft", owner="owner", period_name="2026-09",
        entity_code="EG01", risk_rating="high",
    ) == [{"id": "AR-1"}]
    assert service.get_reconciliation("AR-1")["operation"] == "get"
    assert service.get_template("ART-1")["operation"] == "get_template"
    assert [name for name, _, _ in repository.calls] == [
        "import", "template", "create", "prepare", "submit", "review", "complete",
        "roll_forward", "list", "get", "get_template",
    ]
    assert repository.calls[2][2]["balance"] == "100.125"
    assert repository.calls[8][2]["risk_rating"] == "high"


def test_application_module_has_no_database_or_infrastructure_imports() -> None:
    path = Path(__file__).parents[1] / "reconforge" / "application" / "accounts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "sqlite3" not in imports
    assert all(not name.startswith("reconforge.infrastructure") for name in imports)
