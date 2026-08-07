from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from typer.testing import CliRunner

from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
    verify_professional_invoice_payment_report,
    write_professional_invoice_payment_report,
)
from reconforge.cli import app
from reconforge.domain.professional_invoice_payment_control import (
    ProfessionalInvoicePaymentError,
    ProfessionalInvoiceRecord,
    ProfessionalPaymentRecord,
    run_professional_invoice_payment_control,
)
from reconforge.utils.money import Money

runner = CliRunner()
INVOICES = Path("examples/professional_invoice_payment/invoices.json")
PAYMENTS = Path("examples/professional_invoice_payment/payments.json")


def _money(value: str) -> Money:
    return Money.from_exact(value, "USD")


def _invoice(invoice_id: str = "INV-1", amount: str = "10.00", reference: str = "REF-1") -> ProfessionalInvoiceRecord:
    return ProfessionalInvoiceRecord(invoice_id, "CLIENT-1", "2026-08-01", "2026-08-07", _money(amount), reference, "invoice-export")


def _payment(payment_id: str = "PAY-1", amount: str = "10.00", reference: str = "REF-1") -> ProfessionalPaymentRecord:
    return ProfessionalPaymentRecord(payment_id, "CLIENT-1", "2026-08-07", _money(amount), reference, "payment-export")


def test_professional_fixture_exposes_matched_exception_ambiguity_and_unapplied_cash() -> None:
    run = run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")
    assert run.status_counts == {
        "ambiguous": 1,
        "exception": 1,
        "matched": 2,
        "unmatched_invoice": 1,
        "unmatched_payment": 1,
    }
    assert len(run.decision_digest) == 64


def test_professional_control_preserves_client_amount_and_date_exceptions() -> None:
    wrong_client = ProfessionalPaymentRecord("PAY-2", "CLIENT-2", "2026-08-07", _money("10.00"), "REF-2", "payment-export")
    wrong_amount = _payment("PAY-3", "10.50", "REF-3")
    late = ProfessionalPaymentRecord("PAY-4", "CLIENT-1", "2026-08-20", _money("10.00"), "REF-4", "payment-export")
    decisions = run_professional_invoice_payment_control(
        (_invoice(reference="REF-2"), _invoice("INV-2", reference="REF-3"), _invoice("INV-3", reference="REF-4")),
        (wrong_client, wrong_amount, late),
        amount_tolerance=_money("0.01"),
        payment_window_days=7,
    ).decisions
    assert {item.reason_code for item in decisions} == {
        "INVOICE_PAYMENT_CLIENT_MISMATCH",
        "INVOICE_PAYMENT_AMOUNT_VARIANCE",
        "INVOICE_PAYMENT_DATE_OUTSIDE_WINDOW",
    }


def test_professional_control_is_permutation_stable_and_rejects_duplicate_ids() -> None:
    first = run_professional_invoice_payment_control(
        (_invoice("INV-2", reference="REF-2"), _invoice()),
        (_payment("PAY-2", reference="REF-2"), _payment()),
        amount_tolerance=_money("0.01"),
    )
    second = run_professional_invoice_payment_control(
        (_invoice(), _invoice("INV-2", reference="REF-2")),
        (_payment(), _payment("PAY-2", reference="REF-2")),
        amount_tolerance=_money("0.01"),
    )
    assert first.decision_digest == second.decision_digest
    with pytest.raises(ProfessionalInvoicePaymentError, match="payment IDs must be unique"):
        run_professional_invoice_payment_control(
            (_invoice(),),
            (_payment(), _payment("PAY-1")),
            amount_tolerance=_money("0.01"),
        )


def test_professional_control_rejects_non_positive_and_invalid_window() -> None:
    with pytest.raises(ProfessionalInvoicePaymentError, match="positive Money"):
        ProfessionalInvoiceRecord("INV-0", "CLIENT-1", "2026-08-01", "2026-08-07", _money("0"), "REF", "source")
    with pytest.raises(ProfessionalInvoicePaymentError, match="integer from 0 to 366"):
        run_professional_invoice_payment_control((_invoice(),), (_payment(),), amount_tolerance=_money("0.01"), payment_window_days=367)


def test_professional_report_is_schema_and_digest_bound(tmp_path: Path) -> None:
    run = run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")
    output = tmp_path / "professional-report.json"
    write_professional_invoice_payment_report(run, output)
    payload = verify_professional_invoice_payment_report(output)
    schema = json.loads(Path("docs/schemas/professional_invoice_payment_report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    payload["tampered"] = True
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProfessionalInvoicePaymentError, match="digest verification failed"):
        verify_professional_invoice_payment_report(output)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_professional_report_rejects_nested_decision_tampering_after_outer_rehash(tmp_path: Path) -> None:
    run = run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")
    output = tmp_path / "professional-nested-tamper.json"
    write_professional_invoice_payment_report(run, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["decisions"][0]["reason_code"] = "TAMPERED"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps({key: value for key, value in payload.items() if key != "artifact_digest"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProfessionalInvoicePaymentError, match="replay verification failed"):
        verify_professional_invoice_payment_report(output)


def test_professional_control_cli_writes_replayable_artifact(tmp_path: Path) -> None:
    output = tmp_path / "cli-report.json"
    result = runner.invoke(
        app,
        [
            "professional",
            "invoice-payment",
            "run",
            "--invoices-input",
            str(INVOICES),
            "--payments-input",
            str(PAYMENTS),
            "--currency",
            "USD",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert verify_professional_invoice_payment_report(output)["status_counts"]["ambiguous"] == 1
