"""Deterministic, non-posting invoice-to-payment control for professional work."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.domain.decision_artifact import canonical_decision_digest, verify_canonical_decision_payload
from reconforge.utils.money import Money

PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_VERSION = 1
PROFESSIONAL_INVOICE_PAYMENT_ALGORITHM_VERSION = "professional-invoice-payment-control-v1"
ProfessionalPaymentStatus = Literal["matched", "exception", "unmatched_invoice", "unmatched_payment", "ambiguous"]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class ProfessionalInvoicePaymentError(ValueError):
    """Raised when the closed invoice-to-payment control contract is violated."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ProfessionalInvoicePaymentError(f"{field} is invalid.")
    return value.strip()


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProfessionalInvoicePaymentError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ProfessionalInvoicePaymentError(f"{field} must be an ISO-8601 date.") from exc


def _reference(value: object) -> str:
    if not isinstance(value, str):
        raise ProfessionalInvoicePaymentError("document reference must be text.")
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    if not normalized:
        raise ProfessionalInvoicePaymentError("document reference cannot be empty.")
    return normalized[:160]


def _money_dict(value: Money | None) -> dict[str, object] | None:
    return value.to_canonical_dict() if value is not None else None


@dataclass(frozen=True)
class ProfessionalInvoiceRecord:
    invoice_id: str
    client_id: str
    issue_date: str
    due_date: str
    amount: Money
    reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "invoice_id", _identifier(self.invoice_id, "invoice ID"))
        object.__setattr__(self, "client_id", _identifier(self.client_id, "invoice client ID"))
        object.__setattr__(self, "issue_date", _iso_date(self.issue_date, "invoice issue date"))
        object.__setattr__(self, "due_date", _iso_date(self.due_date, "invoice due date"))
        if date.fromisoformat(self.due_date) < date.fromisoformat(self.issue_date):
            raise ProfessionalInvoicePaymentError("invoice due date cannot precede issue date.")
        if not isinstance(self.amount, Money) or not self.amount.amount.is_finite() or self.amount.amount <= 0:
            raise ProfessionalInvoicePaymentError("invoice amount must be finite and positive Money.")
        object.__setattr__(self, "reference", _reference(self.reference))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "invoice source reference"))


@dataclass(frozen=True)
class ProfessionalPaymentRecord:
    payment_id: str
    client_id: str
    payment_date: str
    amount: Money
    reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_id", _identifier(self.payment_id, "payment ID"))
        object.__setattr__(self, "client_id", _identifier(self.client_id, "payment client ID"))
        object.__setattr__(self, "payment_date", _iso_date(self.payment_date, "payment date"))
        if not isinstance(self.amount, Money) or not self.amount.amount.is_finite() or self.amount.amount <= 0:
            raise ProfessionalInvoicePaymentError("payment amount must be finite and positive Money.")
        object.__setattr__(self, "reference", _reference(self.reference))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "payment source reference"))


@dataclass(frozen=True)
class ProfessionalInvoicePaymentDecision:
    invoice_id: str
    client_id: str
    status: ProfessionalPaymentStatus
    payment_ids: tuple[str, ...]
    amount_variance: Money | None
    days_from_due_date: int | None
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "amount_variance": _money_dict(self.amount_variance),
            "client_id": self.client_id,
            "days_from_due_date": self.days_from_due_date,
            "invoice_id": self.invoice_id,
            "payment_ids": list(self.payment_ids),
            "reason_code": self.reason_code,
            "status": self.status,
        }


@dataclass(frozen=True)
class ProfessionalInvoicePaymentRun:
    schema_version: int
    algorithm_version: str
    amount_tolerance: Money
    payment_window_days: int
    input_digests: tuple[str, ...]
    decisions: tuple[ProfessionalInvoicePaymentDecision, ...]
    decision_digest: str

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.status] = counts.get(decision.status, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "amount_tolerance": self.amount_tolerance.to_canonical_dict(),
            "decision_digest": self.decision_digest,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "input_digests": list(self.input_digests),
            "payment_window_days": self.payment_window_days,
            "schema_version": self.schema_version,
            "status_counts": self.status_counts,
        }


def run_professional_invoice_payment_control(
    invoices: tuple[ProfessionalInvoiceRecord, ...],
    payments: tuple[ProfessionalPaymentRecord, ...],
    *,
    amount_tolerance: Money,
    payment_window_days: int = 7,
    input_digests: tuple[str, ...] = (),
) -> ProfessionalInvoicePaymentRun:
    """Match each invoice to at most one payment by normalized reference and bounded policy."""

    if not isinstance(amount_tolerance, Money) or amount_tolerance.amount < 0:
        raise ProfessionalInvoicePaymentError("amount tolerance must be non-negative Money.")
    if isinstance(payment_window_days, bool) or not isinstance(payment_window_days, int) or not 0 <= payment_window_days <= 366:
        raise ProfessionalInvoicePaymentError("payment window must be an integer from 0 to 366 days.")
    if not invoices and not payments:
        raise ProfessionalInvoicePaymentError("invoice-payment control requires at least one record.")
    invoice_ids = [item.invoice_id for item in invoices]
    payment_ids = [item.payment_id for item in payments]
    if len(invoice_ids) != len(set(invoice_ids)):
        raise ProfessionalInvoicePaymentError("invoice IDs must be unique.")
    if len(payment_ids) != len(set(payment_ids)):
        raise ProfessionalInvoicePaymentError("payment IDs must be unique.")
    currencies = [item.amount.currency for item in invoices] + [item.amount.currency for item in payments]
    if any(currency != amount_tolerance.currency for currency in currencies):
        raise ProfessionalInvoicePaymentError("all invoices, payments, and tolerance must use one currency.")
    by_reference: dict[str, list[ProfessionalPaymentRecord]] = {}
    for payment in payments:
        by_reference.setdefault(payment.reference, []).append(payment)
    used_payment_ids: set[str] = set()
    decisions: list[ProfessionalInvoicePaymentDecision] = []
    for invoice in sorted(invoices, key=lambda item: (item.client_id, item.due_date, item.invoice_id)):
        candidates = sorted(by_reference.get(invoice.reference, ()), key=lambda item: item.payment_id)
        available = [candidate for candidate in candidates if candidate.payment_id not in used_payment_ids]
        if not candidates:
            decisions.append(ProfessionalInvoicePaymentDecision(invoice.invoice_id, invoice.client_id, "unmatched_invoice", (), None, None, "INVOICE_HAS_NO_PAYMENT_CANDIDATE"))
            continue
        if len(available) != 1:
            decisions.append(
                ProfessionalInvoicePaymentDecision(
                    invoice.invoice_id,
                    invoice.client_id,
                    "ambiguous",
                    tuple(candidate.payment_id for candidate in candidates),
                    None,
                    None,
                    "MULTIPLE_PAYMENT_CANDIDATES" if len(available) > 1 else "PAYMENT_CANDIDATES_ALREADY_USED",
                )
            )
            continue
        payment = available[0]
        amount_variance = payment.amount - invoice.amount
        days_from_due = (date.fromisoformat(payment.payment_date) - date.fromisoformat(invoice.due_date)).days
        if payment.client_id != invoice.client_id:
            decisions.append(ProfessionalInvoicePaymentDecision(invoice.invoice_id, invoice.client_id, "exception", (payment.payment_id,), amount_variance, days_from_due, "INVOICE_PAYMENT_CLIENT_MISMATCH"))
            continue
        if abs(amount_variance.amount) > amount_tolerance.amount:
            decisions.append(ProfessionalInvoicePaymentDecision(invoice.invoice_id, invoice.client_id, "exception", (payment.payment_id,), amount_variance, days_from_due, "INVOICE_PAYMENT_AMOUNT_VARIANCE"))
            continue
        if abs(days_from_due) > payment_window_days:
            decisions.append(ProfessionalInvoicePaymentDecision(invoice.invoice_id, invoice.client_id, "exception", (payment.payment_id,), amount_variance, days_from_due, "INVOICE_PAYMENT_DATE_OUTSIDE_WINDOW"))
            continue
        used_payment_ids.add(payment.payment_id)
        decisions.append(ProfessionalInvoicePaymentDecision(invoice.invoice_id, invoice.client_id, "matched", (payment.payment_id,), amount_variance, days_from_due, "INVOICE_PAYMENT_RECONCILED"))
    for payment in sorted(payments, key=lambda item: (item.client_id, item.payment_date, item.payment_id)):
        if payment.payment_id not in used_payment_ids and not any(payment.payment_id in item.payment_ids for item in decisions):
            decisions.append(ProfessionalInvoicePaymentDecision(payment.payment_id, payment.client_id, "unmatched_payment", (payment.payment_id,), None, None, "PAYMENT_HAS_NO_INVOICE_LINE"))
    ordered = tuple(sorted(decisions, key=lambda item: (item.client_id, item.invoice_id, item.status, item.payment_ids)))
    payload = {
        "algorithm_version": PROFESSIONAL_INVOICE_PAYMENT_ALGORITHM_VERSION,
        "amount_tolerance": amount_tolerance.to_canonical_dict(),
        "decisions": [item.to_dict() for item in ordered],
        "input_digests": sorted(set(input_digests)),
        "payment_window_days": payment_window_days,
        "schema_version": PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_VERSION,
    }
    return ProfessionalInvoicePaymentRun(
        PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_VERSION,
        PROFESSIONAL_INVOICE_PAYMENT_ALGORITHM_VERSION,
        amount_tolerance,
        payment_window_days,
        tuple(sorted(set(input_digests))),
        ordered,
        canonical_decision_digest(payload),
    )


def verify_professional_invoice_payment_payload(payload: dict[str, object]) -> None:
    """Verify the serialized invoice/payment decision projection."""

    try:
        verify_canonical_decision_payload(
            payload,
            expected_schema_version=PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_VERSION,
            expected_algorithm_version=PROFESSIONAL_INVOICE_PAYMENT_ALGORITHM_VERSION,
            digest_fields=(
                "algorithm_version",
                "amount_tolerance",
                "decisions",
                "input_digests",
                "payment_window_days",
                "schema_version",
            ),
            decision_sort_key=lambda item: (
                str(item.get("client_id")),
                str(item.get("invoice_id")),
                str(item.get("status")),
                str(item.get("payment_ids", [])),
            ),
            allowed_statuses=frozenset({"matched", "exception", "unmatched_invoice", "unmatched_payment", "ambiguous"}),
        )
    except ValueError as exc:
        raise ProfessionalInvoicePaymentError("professional invoice/payment report replay verification failed.") from exc


__all__ = [
    "PROFESSIONAL_INVOICE_PAYMENT_ALGORITHM_VERSION",
    "PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_VERSION",
    "ProfessionalInvoicePaymentDecision",
    "ProfessionalInvoicePaymentError",
    "ProfessionalInvoicePaymentRun",
    "ProfessionalInvoiceRecord",
    "ProfessionalPaymentRecord",
    "run_professional_invoice_payment_control",
    "verify_professional_invoice_payment_payload",
]
