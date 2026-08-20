"""Fail-closed ERPNext Payment Entry draft write-back boundary.

The adapter validates and serializes one balanced, non-posting Payment Entry
draft. Provider I/O remains behind the governed write-back executor, policy,
maker-checker approval, and idempotency fence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconforge.connectors.writeback_network import (
    WritebackNetworkError,
    WritebackNetworkRegistration,
)

ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_PATH = "/api/resource/Payment%20Entry"
ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT = (
    "https://erpnext.example.test" + ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_PATH
)
ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION = "payment-entry.create-draft"


def _exact_non_negative_decimal(value: str, field_name: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be exact Decimal text") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite non-negative Decimal text")
    return value


def _currency(value: str, field_name: str) -> str:
    normalized = value.strip().upper()
    if (
        value != normalized
        or not normalized.isascii()
        or not normalized.isalnum()
        or not 3 <= len(normalized) <= 12
    ):
        raise ValueError(f"{field_name} must be an uppercase currency code")
    return normalized


class ErpNextPaymentEntryDraft(BaseModel):
    """A closed ERPNext Payment Entry draft with one positive payment side."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company: str = Field(min_length=1, max_length=160)
    posting_date: date
    paid_from: str = Field(min_length=1, max_length=256)
    paid_to: str = Field(min_length=1, max_length=256)
    paid_amount: str = Field(min_length=1, max_length=128)
    received_amount: str = Field(min_length=1, max_length=128)
    paid_from_account_currency: str = Field(min_length=3, max_length=12)
    paid_to_account_currency: str = Field(min_length=3, max_length=12)
    party_type: str | None = Field(default=None, min_length=1, max_length=64)
    party: str | None = Field(default=None, min_length=1, max_length=256)
    reference_no: str | None = Field(default=None, min_length=1, max_length=256)
    remarks: str | None = Field(default=None, max_length=2_000)
    docstatus: Literal[0] = 0

    @field_validator("paid_amount", "received_amount")
    @classmethod
    def validate_amount(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "amount")
        return _exact_non_negative_decimal(value, str(field_name))

    @field_validator("paid_from_account_currency", "paid_to_account_currency")
    @classmethod
    def validate_currency(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "currency")
        return _currency(value, str(field_name))

    @model_validator(mode="after")
    def validate_single_positive_side(self) -> ErpNextPaymentEntryDraft:
        paid = Decimal(self.paid_amount)
        received = Decimal(self.received_amount)
        if (paid > 0) == (received > 0):
            raise ValueError("Payment Entry must have exactly one positive paid or received amount")
        if paid > 0 and self.paid_from == self.paid_to:
            raise ValueError("Payment Entry paid_from and paid_to accounts must differ")
        return self


@dataclass(frozen=True)
class ErpNextPaymentEntryPayload:
    draft: ErpNextPaymentEntryDraft
    operation: str
    payload: bytes
    payload_digest: str


def erpnext_payment_entry_writeback_registration(
    *,
    credential_reference: str,
    endpoint: str = ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT,
) -> WritebackNetworkRegistration:
    """Bind an operator-owned ERPNext Payment Entry draft endpoint."""

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_PATH
    ):
        raise WritebackNetworkError("erpnext_payment_writeback_endpoint_invalid")
    return WritebackNetworkRegistration(
        registration_schema="writeback-network-registration-v1",
        connector_id="erpnext-payment-entry-writeback",
        version="1.0.0",
        endpoint=endpoint,
        egress_destinations=(endpoint,),
        credential_reference=credential_reference,
        credential_auth_scheme="token",
        allowed_operations=frozenset({ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION}),
        allowed_compensation_operations=frozenset(),
        feature_enabled=False,
        synthetic_sandbox=True,
    )


def build_erpnext_payment_entry_payload(
    draft: ErpNextPaymentEntryDraft,
) -> ErpNextPaymentEntryPayload:
    """Serialize one validated draft into deterministic Frappe REST JSON."""

    document = draft.model_dump(mode="json", exclude_none=True)
    document["doctype"] = "Payment Entry"
    payload = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return ErpNextPaymentEntryPayload(
        draft=draft,
        operation=ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
        payload=payload,
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


__all__ = [
    "ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT",
    "ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION",
    "ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_PATH",
    "ErpNextPaymentEntryDraft",
    "ErpNextPaymentEntryPayload",
    "build_erpnext_payment_entry_payload",
    "erpnext_payment_entry_writeback_registration",
]
