from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    prepare_intercompany_eliminations,
    verify_intercompany_elimination_payload,
)
from reconforge.utils.money import Money

runner = CliRunner()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _line(
    transaction_id: str,
    entity: str,
    counterparty: str,
    amount: str,
    *,
    reference: str = "IC-2026-08-001",
    account: str = "IC-RECEIVABLE",
    period: str = "2026-08",
) -> IntercompanyEliminationInputLine:
    return IntercompanyEliminationInputLine(
        transaction_id=transaction_id,
        period_name=period,
        entity_code=entity,
        counterparty_code=counterparty,
        reference=reference,
        group_account_code=account,
        account_type="Asset",
        amount=Money.from_exact(amount, "USD", strict_precision=True),
        source_reference=f"ledger:{transaction_id}",
        source_digest=_digest(f"source:{transaction_id}"),
    )


def _reciprocal_lines() -> tuple[IntercompanyEliminationInputLine, ...]:
    return (
        _line("TX-A", "ENTITY-A", "ENTITY-B", "100.00", account="IC-RECEIVABLE"),
        _line("TX-B", "ENTITY-B", "ENTITY-A", "-100.00", account="IC-PAYABLE"),
    )


def test_exact_reciprocal_group_produces_balanced_nonposting_proposal() -> None:
    result = prepare_intercompany_eliminations(
        _reciprocal_lines(),
        reporting_currency="USD",
        prepared_by="close-preparer",
        prepared_at="2026-08-31T22:00:00Z",
    )

    assert len(result.resolutions) == 1
    resolution = result.resolutions[0]
    assert resolution.status == "proposed"
    assert resolution.reason == "exact_reciprocal_zero_sum_group"
    assert resolution.proposal is not None
    assert resolution.proposal.elimination_type == "intercompany_transaction"
    assert [line.amount.amount for line in resolution.proposal.lines] == [Decimal("-100.00"), Decimal("100.00")]
    assert resolution.proposal.lines[0].source_digest == _digest("source:TX-A")


def test_result_matches_closed_json_schema() -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "docs" / "schemas" / "intercompany-elimination-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result = prepare_intercompany_eliminations(
        _reciprocal_lines(),
        reporting_currency="USD",
        prepared_by="close-preparer",
        prepared_at="2026-08-31T22:00:00Z",
    )

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(result.to_dict())


def test_permutation_is_stable_and_original_lines_replay_result() -> None:
    lines = _reciprocal_lines()
    first = prepare_intercompany_eliminations(
        lines,
        reporting_currency="USD",
        prepared_by="close-preparer",
        prepared_at="2026-08-31T22:00:00Z",
    )
    second = prepare_intercompany_eliminations(
        tuple(reversed(lines)),
        reporting_currency="USD",
        prepared_by="close-preparer",
        prepared_at="2026-08-31T22:00:00Z",
    )

    assert first.to_dict() == second.to_dict()
    assert verify_intercompany_elimination_payload(first.to_dict(), lines).to_dict() == first.to_dict()

    tampered = first.to_dict()
    tampered["result_digest"] = _digest("tampered")
    with pytest.raises(ConsolidationError, match="does not reproduce"):
        verify_intercompany_elimination_payload(tampered, lines)


def test_imbalanced_and_nonreciprocal_groups_remain_unresolved() -> None:
    result = prepare_intercompany_eliminations(
        (
            *_reciprocal_lines(),
            _line("TX-IMBAL-A", "ENTITY-A", "ENTITY-B", "5.00", reference="IC-IMBAL"),
            _line("TX-IMBAL-B", "ENTITY-B", "ENTITY-A", "-4.99", reference="IC-IMBAL"),
            _line("TX-ONE-WAY", "ENTITY-A", "ENTITY-B", "9.00", reference="IC-ONE-WAY"),
        ),
        reporting_currency="USD",
        prepared_by="close-preparer",
        prepared_at="2026-08-31T22:00:00Z",
    )

    by_reason = {item.reason for item in result.resolutions}
    assert "source_group_is_not_zero_sum" in by_reason
    assert "insufficient_reciprocal_lines" in by_reason
    assert all(item.proposal is None for item in result.resolutions if item.status == "unresolved")


def test_currency_mismatch_is_rejected_instead_of_converted() -> None:
    with pytest.raises(ConsolidationError, match="reporting currency"):
        prepare_intercompany_eliminations(
            (
                _reciprocal_lines()[0],
                IntercompanyEliminationInputLine(
                    transaction_id="TX-B-GBP",
                    period_name="2026-08",
                    entity_code="ENTITY-B",
                    counterparty_code="ENTITY-A",
                    reference="IC-2026-08-001",
                    group_account_code="IC-PAYABLE",
                    account_type="Liability",
                    amount=Money.from_exact("-100.00", "GBP", strict_precision=True),
                    source_reference="ledger:TX-B-GBP",
                    source_digest=_digest("source:TX-B-GBP"),
                ),
            ),
            reporting_currency="USD",
            prepared_by="close-preparer",
            prepared_at="2026-08-31T22:00:00Z",
        )


def test_cli_emits_replayable_digest_bound_result(tmp_path: Path) -> None:
    lines = [_line("TX-A", "ENTITY-A", "ENTITY-B", "100.00"), _line("TX-B", "ENTITY-B", "ENTITY-A", "-100.00", account="IC-PAYABLE")]
    request = {
        "schema_version": 1,
        "reporting_currency": "USD",
        "version": "1.0.0",
        "prepared_by": "close-preparer",
        "prepared_at": "2026-08-31T22:00:00Z",
        "lines": [line.to_dict() for line in lines],
    }
    input_path = tmp_path / "intercompany-eliminations.json"
    input_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")

    result = runner.invoke(app, ["consolidation", "intercompany-eliminations", "--input", str(input_path)])

    assert result.exit_code == 0
    assert '"algorithm_version": "intercompany-elimination-v1"' in result.output
    assert '"status": "proposed"' in result.output
    assert '"result_digest":' in result.output
