from __future__ import annotations

import ast
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from reconforge.application.matching import (
    LEGACY_RECORD_IDENTITY_POLICY,
    DeterministicMatchOutput,
    MatchingApplicationService,
    MatchingRepositoryProtocol,
    MatchRunResult,
    ReferenceNormalizationRules,
)
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY, FinancialInputPolicy, InvalidAmountError


class _RecordingMatchingRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

    def run(
        self,
        *,
        left_path: Path | str,
        right_path: Path | str,
        workspace: str = "default",
        name: str = "local-match-job",
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        actor_label: str = "local-cli",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
    ) -> MatchRunResult:
        self.operation = "run"
        self.arguments = locals() | {}
        self.arguments.pop("self")
        return MatchRunResult("job-1", 2, 1, financial_input_policy, record_identity_policy)

    def match_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | ReferenceNormalizationRules | None = None,
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
        _source_locations_trusted: bool = False,
    ) -> DeterministicMatchOutput:
        self.operation = "match_records"
        self.arguments = locals() | {}
        self.arguments.pop("self")
        return DeterministicMatchOutput(
            ({"left_id": "L-1", "right_id": "R-1", "status": "Matched"},),
            (),
            financial_input_policy,
            record_identity_policy,
        )


def _service(repository: _RecordingMatchingRepository) -> MatchingApplicationService:
    return MatchingApplicationService(cast(MatchingRepositoryProtocol, repository))


def test_matching_application_preserves_exact_tolerance_rules_and_identity_policy() -> None:
    repository = _RecordingMatchingRepository()
    service = _service(repository)
    rules = {"case": "upper", "strip_prefixes": ["INV-"]}

    result = service.run(
        left_path="left.csv",
        right_path="right.csv",
        workspace="regulated",
        name="exact-port",
        exact_fields="entity,currency",
        amount_tolerance=Decimal("0.000001"),
        date_window_days=3,
        allow_many_to_one=True,
        allow_one_to_many=True,
        allow_many_to_many=True,
        reference_normalization_rules=rules,
        idempotency_key="match-port-1",
        actor_label="operator@example.test",
        record_identity_policy="content-occurrence-v1",
    )

    assert result == MatchRunResult("job-1", 2, 1, STRICT_FINANCIAL_INPUT_POLICY, "content-occurrence-v1")
    assert repository.arguments["amount_tolerance"] == Decimal("0.000001")
    assert repository.arguments["reference_normalization_rules"] is rules
    assert repository.arguments["workspace"] == "regulated"
    assert repository.arguments["actor_label"] == "operator@example.test"


def test_matching_result_types_reject_unsupported_financial_input_policy() -> None:
    with pytest.raises(InvalidAmountError, match="unsupported financial input policy"):
        MatchRunResult("job-1", 0, 0, "unsupported-v9", LEGACY_RECORD_IDENTITY_POLICY)  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError, match="unsupported financial input policy"):
        DeterministicMatchOutput(
            results=(),
            exceptions=(),
            financial_input_policy="unsupported-v9",  # type: ignore[arg-type]
        )


def test_matching_application_preserves_record_objects_and_normalization_type() -> None:
    repository = _RecordingMatchingRepository()
    service = _service(repository)
    left = [{"id": "L-1", "amount": "999999999999.123456"}]
    right = [{"id": "R-1", "amount": "999999999999.123456"}]
    rules = ReferenceNormalizationRules(strip_prefixes=("INV-",))

    output = service.match_records(
        left_records=left,
        right_records=right,
        amount_tolerance=Decimal("0"),
        reference_normalization_rules=rules,
    )

    assert output.results[0]["status"] == "Matched"
    assert repository.arguments["left_records"] is left
    assert repository.arguments["right_records"] is right
    assert repository.arguments["reference_normalization_rules"] is rules


def test_matching_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/matching.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)
