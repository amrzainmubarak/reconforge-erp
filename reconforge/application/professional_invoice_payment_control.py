"""Application boundary for local professional invoice-to-payment controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reconforge.domain.professional_invoice_payment_control import (
    ProfessionalInvoicePaymentError,
    ProfessionalInvoicePaymentRun,
    ProfessionalInvoiceRecord,
    ProfessionalPaymentRecord,
    run_professional_invoice_payment_control,
)
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.utils.money import Money


def _required(record: dict[str, Any], key: str) -> Any:
    if key not in record:
        raise ProfessionalInvoicePaymentError(f"professional invoice/payment input is missing {key}.")
    return record[key]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        document = read_json_record_document(path, envelope_keys=("records", "data"))
    except RecordIngressError as exc:
        raise ProfessionalInvoicePaymentError(f"professional invoice/payment input rejected ({exc.code}).") from exc
    return list(document.records), document.checksum_sha256


def _read_invoices(path: Path) -> tuple[tuple[ProfessionalInvoiceRecord, ...], str]:
    records, digest = _read_records(path)
    try:
        invoices = tuple(
            ProfessionalInvoiceRecord(
                invoice_id=_required(record, "invoice_id"),
                client_id=_required(record, "client_id"),
                issue_date=_required(record, "issue_date"),
                due_date=_required(record, "due_date"),
                amount=Money.from_exact(_required(record, "amount"), _required(record, "currency")),
                reference=_required(record, "reference"),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfessionalInvoicePaymentError("invoice input does not match the closed record contract.") from exc
    return invoices, digest


def _read_payments(path: Path) -> tuple[tuple[ProfessionalPaymentRecord, ...], str]:
    records, digest = _read_records(path)
    try:
        payments = tuple(
            ProfessionalPaymentRecord(
                payment_id=_required(record, "payment_id"),
                client_id=_required(record, "client_id"),
                payment_date=_required(record, "payment_date"),
                amount=Money.from_exact(_required(record, "amount"), _required(record, "currency")),
                reference=_required(record, "reference"),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfessionalInvoicePaymentError("payment input does not match the closed record contract.") from exc
    return payments, digest


def run_professional_invoice_payment_control_files(
    invoices_path: Path,
    payments_path: Path,
    *,
    currency: str,
    tolerance: str,
    payment_window_days: int = 7,
) -> ProfessionalInvoicePaymentRun:
    """Run the local invoice-to-payment control over two bounded JSON exports."""

    invoices, invoices_digest = _read_invoices(invoices_path)
    payments, payments_digest = _read_payments(payments_path)
    try:
        amount_tolerance = Money.from_exact(tolerance, currency)
    except Exception as exc:
        raise ProfessionalInvoicePaymentError("professional invoice/payment control policy is invalid.") from exc
    return run_professional_invoice_payment_control(
        invoices,
        payments,
        amount_tolerance=amount_tolerance,
        payment_window_days=payment_window_days,
        input_digests=(invoices_digest, payments_digest, _sha256(invoices_path), _sha256(payments_path)),
    )


def write_professional_invoice_payment_report(run: ProfessionalInvoicePaymentRun, output_path: Path) -> None:
    """Write a self-digesting invoice-to-payment control artifact."""

    payload = run.to_dict()
    payload["artifact_type"] = "reconforge-professional-invoice-payment-control"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_professional_invoice_payment_report(path: Path) -> dict[str, Any]:
    """Verify one local invoice-to-payment report through the bounded reader."""

    from reconforge.io.structured import StructuredDocumentError, read_json_document

    try:
        payload = read_json_document(path)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise ProfessionalInvoicePaymentError("professional invoice/payment report cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("artifact_type") != "reconforge-professional-invoice-payment-control":
        raise ProfessionalInvoicePaymentError("professional invoice/payment report artifact type is invalid.")
    artifact_digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    expected = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    if not isinstance(artifact_digest, str) or artifact_digest != expected:
        raise ProfessionalInvoicePaymentError("professional invoice/payment report digest verification failed.")
    return payload


__all__ = [
    "run_professional_invoice_payment_control_files",
    "verify_professional_invoice_payment_report",
    "write_professional_invoice_payment_report",
]
