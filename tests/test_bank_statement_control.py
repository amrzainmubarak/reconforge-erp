from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from typer.testing import CliRunner

from reconforge.application.bank_statement_control import (
    run_bank_statement_control_files,
    verify_bank_statement_report,
    write_bank_statement_report,
)
from reconforge.cli import app
from reconforge.domain.bank_statement_control import (
    BankLedgerRecord,
    BankStatementControlError,
    BankStatementRecord,
    normalize_bank_reference,
    run_bank_statement_control,
)
from reconforge.utils.money import Money

runner = CliRunner()
STATEMENT = Path("examples/bank_statement_control/statement.xml")
LEDGER = Path("examples/bank_statement_control/ledger.json")


def _money(value: str) -> Money:
    return Money.from_exact(value, "EUR")


def _bank(line_id: str = "BANK-1", amount: str = "10.00", reference: str = "REF-1") -> BankStatementRecord:
    return BankStatementRecord(line_id, "ACCOUNT-1", "2026-08-04", _money(amount), reference, "statement-1")


def _ledger(record_id: str = "LEDGER-1", amount: str = "10.00", reference: str = "REF-1") -> BankLedgerRecord:
    return BankLedgerRecord(record_id, "ACCOUNT-1", "2026-08-04", _money(amount), reference, "ledger-1")


def test_bank_statement_fixture_matches_and_keeps_unmatched_ledger_visible() -> None:
    run = run_bank_statement_control_files(STATEMENT, LEDGER, currency="EUR", tolerance="0.01")
    assert run.status_counts == {"matched": 2, "unmatched_ledger": 1}
    assert all(item.reason_code == "BANK_LEDGER_RECONCILED" for item in run.decisions[:2])
    assert len(run.decision_digest) == 64


def test_bank_control_preserves_variance_date_and_account_exceptions() -> None:
    bank = _bank()
    variance = _ledger(amount="10.50")
    dated = BankLedgerRecord("LEDGER-2", "ACCOUNT-1", "2026-08-10", _money("10.00"), "REF-2", "ledger-2")
    wrong_account = BankLedgerRecord("LEDGER-3", "ACCOUNT-2", "2026-08-04", _money("10.00"), "REF-3", "ledger-3")
    decisions = run_bank_statement_control(
        (bank, _bank("BANK-2", reference="REF-2"), _bank("BANK-3", reference="REF-3")),
        (variance, dated, wrong_account),
        amount_tolerance=_money("0.01"),
        date_window_days=1,
    ).decisions
    assert {item.reason_code for item in decisions} == {
        "BANK_LEDGER_AMOUNT_VARIANCE",
        "BANK_LEDGER_DATE_OUTSIDE_WINDOW",
        "BANK_LEDGER_ACCOUNT_MISMATCH",
    }


def test_bank_control_marks_ambiguity_and_unmatched_bank_lines() -> None:
    run = run_bank_statement_control(
        (_bank(), _bank("BANK-2", reference="MISSING")),
        (_ledger("LEDGER-1"), _ledger("LEDGER-2")),
        amount_tolerance=_money("0.01"),
    )
    assert run.status_counts == {"ambiguous": 1, "unmatched_bank": 1}
    assert run.decisions[0].ledger_record_ids == ("LEDGER-1", "LEDGER-2")


def test_bank_control_is_permutation_stable_and_rejects_duplicate_ids() -> None:
    first = run_bank_statement_control(
        (_bank("BANK-2", reference="REF-2"), _bank("BANK-1")),
        (_ledger("LEDGER-1"), _ledger("LEDGER-2", reference="REF-2")),
        amount_tolerance=_money("0.01"),
    )
    second = run_bank_statement_control(
        (_bank("BANK-1"), _bank("BANK-2", reference="REF-2")),
        (_ledger("LEDGER-2", reference="REF-2"), _ledger("LEDGER-1")),
        amount_tolerance=_money("0.01"),
    )
    assert first.decision_digest == second.decision_digest
    with pytest.raises(BankStatementControlError, match="ledger record IDs must be unique"):
        run_bank_statement_control(
            (_bank(),),
            (_ledger(), _ledger("LEDGER-1")),
            amount_tolerance=_money("0.01"),
        )


def test_bank_control_rejects_invalid_reference_float_and_currency() -> None:
    with pytest.raises(BankStatementControlError, match="cannot be empty"):
        normalize_bank_reference("---")
    with pytest.raises(BankStatementControlError, match="Money"):
        BankStatementRecord("BANK-FLOAT", "ACCOUNT-1", "2026-08-04", 1.0, "REF", "source")  # type: ignore[arg-type]
    with pytest.raises(BankStatementControlError, match="one currency"):
        run_bank_statement_control((_bank(),), (), amount_tolerance=Money.from_exact("0.01", "USD"))


def test_bank_report_is_schema_and_digest_bound(tmp_path: Path) -> None:
    run = run_bank_statement_control_files(STATEMENT, LEDGER, currency="EUR", tolerance="0.01")
    output = tmp_path / "bank-report.json"
    write_bank_statement_report(run, output)
    payload = verify_bank_statement_report(output)
    schema = json.loads(Path("docs/schemas/bank_statement_control_report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    payload["tampered"] = True
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BankStatementControlError, match="digest verification failed"):
        verify_bank_statement_report(output)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_bank_control_cli_writes_replayable_artifact(tmp_path: Path) -> None:
    output = tmp_path / "cli-report.json"
    result = runner.invoke(
        app,
        [
            "bank",
            "statement",
            "control-run",
            "--statement-input",
            str(STATEMENT),
            "--ledger-input",
            str(LEDGER),
            "--currency",
            "EUR",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert verify_bank_statement_report(output)["status_counts"] == {"matched": 2, "unmatched_ledger": 1}
    assert output.read_text(encoding="utf-8").count("EUR") >= 3
