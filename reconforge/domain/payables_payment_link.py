"""Exact admission rules for linking a supplier invoice to a posted cash effect.

The existing financial-posting aggregate owns creation and review of the
double-entry record.  This bounded domain contract deliberately does not create
another posting path: it admits a Payables settlement only when that immutable
financial effect has an unambiguous Accounts Payable debit and cash credit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import canonical_json, digest_payload
from reconforge.io.finance_posting import decode_posting_snapshot
from reconforge.io.persisted import PersistedJsonError

PAYMENT_REFERENCE_PREFIX = "AP-PAYMENT:"
PAYMENT_LINK_CONTRACT_VERSION = "payables-finance-payment-link-v1"
PAYMENT_LINK_REVERSAL_CONTRACT_VERSION = "payables-finance-payment-link-reversal-v1"
_MAX_MINOR_UNITS = 9_000_000_000_000_000_000


class PayablesPaymentLinkError(ValueError):
    """Stable, non-sensitive rejection for the finance-to-AP linkage."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _text(value: object, field: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise PayablesPaymentLinkError("payment_link_invalid", f"{field} must be text.")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise PayablesPaymentLinkError("payment_link_invalid", f"{field} is invalid.")
    return result


def _optional_text(value: object, field: str, *, maximum: int = 500) -> str:
    if value is None:
        return ""
    return _text(value, field, maximum=maximum)


def _minor(value: object, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _MAX_MINOR_UNITS:
        raise PayablesPaymentLinkError("payment_link_amount_invalid", f"{field} must be a supported minor-unit integer.")
    if positive and value == 0:
        raise PayablesPaymentLinkError("payment_link_amount_invalid", f"{field} must be positive.")
    return value


def payment_external_reference(invoice_id: object) -> str:
    """Return the sole cross-aggregate reference allowed for a settlement effect."""

    return f"{PAYMENT_REFERENCE_PREFIX}{_text(invoice_id, 'supplier invoice id', maximum=160)}"


@dataclass(frozen=True)
class FinancePaymentEvidence:
    """The immutable subset of a reviewed Finance effect consumed by Payables."""

    finance_effect_id: str
    finance_entry_id: str
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    currency_code: str
    amount_minor: int
    payment_date: str
    validation_digest: str
    posted_actor_id: str
    preparer_actor_id: str
    validator_actor_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "finance_effect_id": self.finance_effect_id,
            "finance_entry_id": self.finance_entry_id,
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "legal_entity_id": self.legal_entity_id,
            "currency_code": self.currency_code,
            "amount_minor": self.amount_minor,
            "payment_date": self.payment_date,
            "validation_digest": self.validation_digest,
            "posted_actor_id": self.posted_actor_id,
            "preparer_actor_id": self.preparer_actor_id,
            "validator_actor_id": self.validator_actor_id,
        }


@dataclass(frozen=True)
class FinancePaymentReversalEvidence:
    """Immutable Finance reversal evidence that unwinds one AP allocation.

    This record deliberately describes an already posted full Finance reversal.
    It never constructs a journal or changes the original payment link.
    """

    payment_link_id: str
    reversal_finance_effect_id: str
    reversal_finance_entry_id: str
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    currency_code: str
    amount_minor: int
    reversal_date: str
    validation_digest: str
    posted_actor_id: str
    preparer_actor_id: str
    validator_actor_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "payment_link_id": self.payment_link_id,
            "reversal_finance_effect_id": self.reversal_finance_effect_id,
            "reversal_finance_entry_id": self.reversal_finance_entry_id,
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "legal_entity_id": self.legal_entity_id,
            "currency_code": self.currency_code,
            "amount_minor": self.amount_minor,
            "reversal_date": self.reversal_date,
            "validation_digest": self.validation_digest,
            "posted_actor_id": self.posted_actor_id,
            "preparer_actor_id": self.preparer_actor_id,
            "validator_actor_id": self.validator_actor_id,
        }


def _snapshot(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        try:
            raw = canonical_json(dict(value))
        except ValueError as exc:
            raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect snapshot is invalid.") from exc
    elif isinstance(value, str):
        raw = value
    else:
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect snapshot is invalid.")
    try:
        return decode_posting_snapshot(raw).payload
    except PersistedJsonError as exc:
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect snapshot is invalid.") from exc


def _same_scope(invoice: Mapping[str, object], effect: Mapping[str, object]) -> None:
    for field in ("workspace_id", "organization_id", "legal_entity_id"):
        invoice_value = _text(invoice.get(field), f"invoice {field}", maximum=160)
        effect_value = _text(effect.get(field), f"effect {field}", maximum=160)
        if invoice_value != effect_value:
            raise PayablesPaymentLinkError("payment_link_scope_mismatch", "Financial effect is outside the supplier invoice scope.")


def validate_finance_payment_effect(
    *,
    invoice: Mapping[str, object],
    effect: Mapping[str, object],
    ap_account_id: object,
    cash_account_id: object,
    settlement_actor_id: object,
    invoice_creator_actor_id: object,
    invoice_approver_actor_id: object,
) -> FinancePaymentEvidence:
    """Verify the exact one-invoice AP/cash posting shape before allocation.

    The reference binds the financial entry to one invoice.  The strict two-line
    shape deliberately rejects tax, fee, FX, netting, reversal, and composite
    manual entries; those require their own reviewed settlement contracts.
    """

    invoice_id = _text(invoice.get("id"), "supplier invoice id", maximum=160)
    if _text(invoice.get("status"), "invoice status", maximum=40) != "Approved":
        raise PayablesPaymentLinkError("payment_link_invoice_not_approved", "Only an approved supplier invoice can be settled.")
    invoice_total = _minor(invoice.get("total_minor"), "invoice total", positive=True)
    currency_code = _text(invoice.get("currency_code"), "invoice currency", maximum=16)
    actor_id = _text(settlement_actor_id, "settlement actor id", maximum=160)
    creator_id = _text(invoice_creator_actor_id, "invoice creator actor id", maximum=160)
    approver_id = _text(invoice_approver_actor_id, "invoice approver actor id", maximum=160)
    if actor_id in {creator_id, approver_id}:
        raise PayablesPaymentLinkError(
            "payment_link_sod_denied", "The invoice creator and approver cannot settle the same invoice.")

    effect_id = _text(effect.get("id"), "finance effect id", maximum=160)
    entry_id = _text(effect.get("entry_id"), "finance entry id", maximum=160)
    if _text(effect.get("source_kind"), "finance effect source", maximum=64) != "Manual" or effect.get("reverses_effect_id") is not None:
        raise PayablesPaymentLinkError("payment_link_source_invalid", "Settlement requires a non-reversal reviewed Manual financial effect.")
    if _text(effect.get("source_id"), "finance effect source id", maximum=160) != entry_id:
        raise PayablesPaymentLinkError("payment_link_source_invalid", "Financial effect source does not identify its entry.")
    _same_scope(invoice, effect)
    if _text(effect.get("currency_code"), "finance effect currency", maximum=16) != currency_code:
        raise PayablesPaymentLinkError("payment_link_currency_mismatch", "Financial effect currency differs from the supplier invoice.")
    validation_digest = _text(effect.get("validation_digest"), "finance validation digest", maximum=64)
    if len(validation_digest) != 64 or any(character not in "0123456789abcdef" for character in validation_digest):
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect validation digest is invalid.")
    posted_actor_id = _text(effect.get("posted_actor_id"), "finance posted actor id", maximum=160)
    if posted_actor_id in {creator_id, approver_id}:
        raise PayablesPaymentLinkError(
            "payment_link_sod_denied", "The invoice creator and approver cannot post the linked settlement effect.")

    snapshot = _snapshot(effect.get("snapshot_json", effect.get("snapshot")))
    header = snapshot.get("entry")
    lines = snapshot.get("lines")
    if not isinstance(header, Mapping) or not isinstance(lines, list):
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect snapshot is incomplete.")
    if _text(header.get("id"), "snapshot entry id", maximum=160) != entry_id:
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect snapshot identifies a different entry.")
    if _text(header.get("external_reference"), "snapshot external reference", maximum=500) != payment_external_reference(invoice_id):
        raise PayablesPaymentLinkError("payment_link_reference_mismatch", "Financial effect does not carry the required supplier invoice reference.")
    if _text(header.get("currency_code"), "snapshot currency", maximum=16) != currency_code:
        raise PayablesPaymentLinkError("payment_link_currency_mismatch", "Financial effect snapshot currency differs from the supplier invoice.")
    preparer_actor_id = _text(header.get("preparer_actor_id"), "financial preparer actor id", maximum=160)
    # The immutable posting snapshot retains its preparer but deliberately does
    # not duplicate the validator identity.  The adapter supplies that retained
    # ledger-header provenance alongside the effect row.
    validator_actor_id = _text(effect.get("validator_actor_id"), "financial validator actor id", maximum=160)
    if len({preparer_actor_id, validator_actor_id, posted_actor_id}) != 3:
        raise PayablesPaymentLinkError("payment_link_finance_sod_invalid", "Financial effect lacks independent preparation, review, and posting.")

    ap_account = _text(ap_account_id, "accounts payable account id", maximum=160)
    cash_account = _text(cash_account_id, "cash account id", maximum=160)
    if ap_account == cash_account:
        raise PayablesPaymentLinkError("payment_link_accounts_invalid", "Accounts payable and cash accounts must differ.")
    if not isinstance(lines, Sequence) or len(lines) != 2 or any(not isinstance(line, Mapping) for line in lines):
        raise PayablesPaymentLinkError("payment_link_shape_invalid", "Settlement requires exactly one Accounts Payable debit and one cash credit.")

    debit_lines = [
        line
        for line in lines
        if _text(line.get("account_id"), "financial line account id", maximum=160) == ap_account
        and _minor(line.get("debit_minor"), "financial debit") > 0
        and _minor(line.get("credit_minor"), "financial credit") == 0
    ]
    credit_lines = [
        line
        for line in lines
        if _text(line.get("account_id"), "financial line account id", maximum=160) == cash_account
        and _minor(line.get("debit_minor"), "financial debit") == 0
        and _minor(line.get("credit_minor"), "financial credit") > 0
    ]
    if len(debit_lines) != 1 or len(credit_lines) != 1:
        raise PayablesPaymentLinkError("payment_link_shape_invalid", "Settlement requires exactly one Accounts Payable debit and one cash credit.")
    amount = _minor(debit_lines[0].get("debit_minor"), "settlement amount", positive=True)
    if amount != _minor(credit_lines[0].get("credit_minor"), "settlement amount", positive=True) or amount > invoice_total:
        raise PayablesPaymentLinkError("payment_link_amount_invalid", "Settlement amount must be positive, balanced, and no greater than the invoice total.")
    try:
        payment_date = date.fromisoformat(_text(header.get("posting_date"), "posting date", maximum=10)).isoformat()
    except ValueError as exc:
        raise PayablesPaymentLinkError("payment_link_snapshot_invalid", "Financial effect posting date is invalid.") from exc

    return FinancePaymentEvidence(
        finance_effect_id=effect_id,
        finance_entry_id=entry_id,
        workspace_id=_text(effect.get("workspace_id"), "effect workspace id", maximum=160),
        organization_id=_text(effect.get("organization_id"), "effect organization id", maximum=160),
        legal_entity_id=_text(effect.get("legal_entity_id"), "effect legal entity id", maximum=160),
        currency_code=currency_code,
        amount_minor=amount,
        payment_date=payment_date,
        validation_digest=validation_digest,
        posted_actor_id=posted_actor_id,
        preparer_actor_id=preparer_actor_id,
        validator_actor_id=validator_actor_id,
    )


def validate_finance_payment_reversal_effect(
    *,
    invoice: Mapping[str, object],
    payment_link: Mapping[str, object],
    effect: Mapping[str, object],
    reversal_actor_id: object,
    invoice_creator_actor_id: object,
    invoice_approver_actor_id: object,
) -> FinancePaymentReversalEvidence:
    """Require one independently posted exact inverse for one retained link.

    Finance Posting already verifies the kernel's full inverse.  AP repeats the
    small, business-critical projection it consumes so direct repository and
    database callers cannot turn an arbitrary Finance reversal into an invoice
    state change.
    """

    invoice_id = _text(invoice.get("id"), "supplier invoice id", maximum=160)
    invoice_status = _text(invoice.get("status"), "invoice status", maximum=40)
    if invoice_status not in {"Approved", "Paid"}:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_invoice_invalid",
            "Only an approved or paid supplier invoice can have retained payment evidence reversed.",
        )
    _minor(invoice.get("total_minor"), "invoice total", positive=True)
    creator_id = _text(invoice_creator_actor_id, "invoice creator actor id", maximum=160)
    approver_id = _text(invoice_approver_actor_id, "invoice approver actor id", maximum=160)
    actor_id = _text(reversal_actor_id, "payment-link reversal actor id", maximum=160)

    link_id = _text(payment_link.get("id"), "payment link id", maximum=160)
    if _text(payment_link.get("supplier_invoice_id"), "payment-link supplier invoice id", maximum=160) != invoice_id:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_scope_mismatch", "Payment evidence belongs to another supplier invoice."
        )
    original_effect_id = _text(payment_link.get("finance_effect_id"), "payment-link finance effect id", maximum=160)
    link_currency = _text(payment_link.get("currency_code"), "payment-link currency", maximum=16)
    link_amount = _minor(payment_link.get("amount_minor"), "payment-link amount", positive=True)
    settlement_actor_id = _text(payment_link.get("settlement_actor_id"), "payment-link settlement actor id", maximum=160)
    if actor_id in {creator_id, approver_id, settlement_actor_id}:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_sod_denied",
            "Invoice makers, approvers, and the original settler cannot reverse the same payment link.",
        )
    for field in ("workspace_id", "organization_id", "legal_entity_id"):
        invoice_value = _text(invoice.get(field), f"invoice {field}", maximum=160)
        link_value = _text(payment_link.get(field), f"payment-link {field}", maximum=160)
        effect_value = _text(effect.get(field), f"reversal effect {field}", maximum=160)
        if invoice_value != link_value or link_value != effect_value:
            raise PayablesPaymentLinkError(
                "payment_link_reversal_scope_mismatch", "Financial reversal is outside the retained payment-link scope."
            )

    effect_id = _text(effect.get("id"), "reversal finance effect id", maximum=160)
    entry_id = _text(effect.get("entry_id"), "reversal finance entry id", maximum=160)
    if (
        _text(effect.get("source_kind"), "reversal finance source", maximum=64) != "Reversal"
        or _optional_text(effect.get("source_id"), "reversal finance source id", maximum=160) != original_effect_id
        or _optional_text(effect.get("reverses_effect_id"), "reversal finance original effect id", maximum=160)
        != original_effect_id
    ):
        raise PayablesPaymentLinkError(
            "payment_link_reversal_source_invalid",
            "Payment-link reversal requires the posted Finance reversal of the retained original effect.",
        )
    if _text(effect.get("currency_code"), "reversal finance currency", maximum=16) != link_currency:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_currency_mismatch", "Financial reversal currency differs from payment evidence."
        )
    validation_digest = _text(effect.get("validation_digest"), "reversal finance validation digest", maximum=64)
    if len(validation_digest) != 64 or any(character not in "0123456789abcdef" for character in validation_digest):
        raise PayablesPaymentLinkError(
            "payment_link_reversal_snapshot_invalid", "Financial reversal validation digest is invalid."
        )
    posted_actor_id = _text(effect.get("posted_actor_id"), "reversal finance posted actor id", maximum=160)

    snapshot = _snapshot(effect.get("snapshot_json", effect.get("snapshot")))
    header = snapshot.get("entry")
    lines = snapshot.get("lines")
    if not isinstance(header, Mapping) or not isinstance(lines, list):
        raise PayablesPaymentLinkError(
            "payment_link_reversal_snapshot_invalid", "Financial reversal snapshot is incomplete."
        )
    if (
        _text(header.get("id"), "reversal snapshot entry id", maximum=160) != entry_id
        or _optional_text(header.get("reverses_posting_id"), "reversal snapshot original effect id", maximum=160)
        != original_effect_id
        or _optional_text(header.get("external_reference"), "reversal snapshot external reference", maximum=160)
        != original_effect_id
        or _text(header.get("currency_code"), "reversal snapshot currency", maximum=16) != link_currency
    ):
        raise PayablesPaymentLinkError(
            "payment_link_reversal_snapshot_invalid", "Financial reversal snapshot does not bind its original payment effect."
        )
    preparer_actor_id = _text(header.get("preparer_actor_id"), "reversal financial preparer actor id", maximum=160)
    validator_actor_id = _text(effect.get("validator_actor_id"), "reversal financial validator actor id", maximum=160)
    if len({preparer_actor_id, validator_actor_id, posted_actor_id, actor_id}) != 4:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_finance_sod_invalid",
            "Payment-link reversal requires independent Finance preparation, review, posting, and AP reversal action."
        )

    ap_account_id = _text(payment_link.get("ap_account_id"), "payment-link accounts payable account id", maximum=160)
    cash_account_id = _text(payment_link.get("cash_account_id"), "payment-link cash account id", maximum=160)
    if not isinstance(lines, Sequence) or len(lines) != 2 or any(not isinstance(line, Mapping) for line in lines):
        raise PayablesPaymentLinkError(
            "payment_link_reversal_shape_invalid", "Payment-link reversal requires exactly one AP credit and one cash debit."
        )
    debit_lines = [
        line
        for line in lines
        if _text(line.get("account_id"), "reversal financial line account id", maximum=160) == cash_account_id
        and _minor(line.get("debit_minor"), "reversal financial debit") == link_amount
        and _minor(line.get("credit_minor"), "reversal financial credit") == 0
    ]
    credit_lines = [
        line
        for line in lines
        if _text(line.get("account_id"), "reversal financial line account id", maximum=160) == ap_account_id
        and _minor(line.get("debit_minor"), "reversal financial debit") == 0
        and _minor(line.get("credit_minor"), "reversal financial credit") == link_amount
    ]
    if len(debit_lines) != 1 or len(credit_lines) != 1:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_shape_invalid", "Financial reversal must exactly invert the retained AP and cash allocation."
        )
    try:
        reversal_date = date.fromisoformat(_text(header.get("posting_date"), "reversal posting date", maximum=10)).isoformat()
    except ValueError as exc:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_snapshot_invalid", "Financial reversal posting date is invalid."
        ) from exc

    return FinancePaymentReversalEvidence(
        payment_link_id=link_id,
        reversal_finance_effect_id=effect_id,
        reversal_finance_entry_id=entry_id,
        workspace_id=_text(payment_link.get("workspace_id"), "payment-link workspace id", maximum=160),
        organization_id=_text(payment_link.get("organization_id"), "payment-link organization id", maximum=160),
        legal_entity_id=_text(payment_link.get("legal_entity_id"), "payment-link legal entity id", maximum=160),
        currency_code=link_currency,
        amount_minor=link_amount,
        reversal_date=reversal_date,
        validation_digest=validation_digest,
        posted_actor_id=posted_actor_id,
        preparer_actor_id=preparer_actor_id,
        validator_actor_id=validator_actor_id,
    )


def payment_link_request_digest(
    *,
    invoice_id: object,
    finance_effect_id: object,
    ap_account_id: object,
    cash_account_id: object,
    expected_invoice_version: object,
    settlement_actor_id: object,
) -> str:
    """Hash the complete command intent before an idempotent result is recorded."""

    if isinstance(expected_invoice_version, bool) or not isinstance(expected_invoice_version, int) or expected_invoice_version < 1:
        raise PayablesPaymentLinkError("payment_link_version_invalid", "Expected invoice version must be a positive integer.")
    return digest_payload(
        {
            "contract_version": PAYMENT_LINK_CONTRACT_VERSION,
            "invoice_id": _text(invoice_id, "supplier invoice id", maximum=160),
            "finance_effect_id": _text(finance_effect_id, "finance effect id", maximum=160),
            "ap_account_id": _text(ap_account_id, "accounts payable account id", maximum=160),
            "cash_account_id": _text(cash_account_id, "cash account id", maximum=160),
            "expected_invoice_version": expected_invoice_version,
            "settlement_actor_id": _text(settlement_actor_id, "settlement actor id", maximum=160),
        }
    )


def payment_link_reversal_request_digest(
    *,
    invoice_id: object,
    payment_link_id: object,
    reversal_finance_effect_id: object,
    expected_invoice_version: object,
    reversal_actor_id: object,
) -> str:
    """Hash the complete immutable AP reversal intent for safe retries."""

    if isinstance(expected_invoice_version, bool) or not isinstance(expected_invoice_version, int) or expected_invoice_version < 1:
        raise PayablesPaymentLinkError(
            "payment_link_reversal_version_invalid", "Expected invoice version must be a positive integer."
        )
    return digest_payload(
        {
            "contract_version": PAYMENT_LINK_REVERSAL_CONTRACT_VERSION,
            "invoice_id": _text(invoice_id, "supplier invoice id", maximum=160),
            "payment_link_id": _text(payment_link_id, "payment link id", maximum=160),
            "reversal_finance_effect_id": _text(
                reversal_finance_effect_id, "reversal finance effect id", maximum=160
            ),
            "expected_invoice_version": expected_invoice_version,
            "reversal_actor_id": _text(reversal_actor_id, "payment-link reversal actor id", maximum=160),
        }
    )


__all__ = [
    "FinancePaymentEvidence",
    "FinancePaymentReversalEvidence",
    "PAYMENT_LINK_CONTRACT_VERSION",
    "PAYMENT_LINK_REVERSAL_CONTRACT_VERSION",
    "PAYMENT_REFERENCE_PREFIX",
    "PayablesPaymentLinkError",
    "payment_external_reference",
    "payment_link_reversal_request_digest",
    "payment_link_request_digest",
    "validate_finance_payment_reversal_effect",
    "validate_finance_payment_effect",
]
