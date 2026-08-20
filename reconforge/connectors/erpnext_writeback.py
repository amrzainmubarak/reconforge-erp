"""Fail-closed ERPNext Journal Entry draft write-back boundary.

The adapter only validates and serializes a balanced ``docstatus=0`` Journal
Entry payload.  The governed write-back executor remains feature-disabled by
default and is the only path allowed to perform provider I/O after approval.
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

ERP_NEXT_JOURNAL_ENTRY_PATH = "/api/resource/Journal%20Entry"
ERP_NEXT_JOURNAL_ENTRY_ENDPOINT = "https://erpnext.example.test" + ERP_NEXT_JOURNAL_ENTRY_PATH
ERP_NEXT_JOURNAL_ENTRY_OPERATION = "journal-entry.create-draft"


def _exact_non_negative_decimal(value: str, field_name: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be exact Decimal text") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite non-negative Decimal text")
    return value


class ErpNextJournalEntryLine(BaseModel):
    """One balanced ERPNext account row using exact source amount text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account: str = Field(min_length=1, max_length=256)
    debit: str = Field(min_length=1, max_length=128)
    credit: str = Field(min_length=1, max_length=128)
    account_currency: str | None = Field(default=None, min_length=3, max_length=12)
    cost_center: str | None = Field(default=None, min_length=1, max_length=256)
    party_type: str | None = Field(default=None, min_length=1, max_length=64)
    party: str | None = Field(default=None, min_length=1, max_length=256)
    reference_type: str | None = Field(default=None, min_length=1, max_length=128)
    reference_name: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("debit", "credit")
    @classmethod
    def validate_amount(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "amount")
        return _exact_non_negative_decimal(value, str(field_name))

    @model_validator(mode="after")
    def validate_single_side(self) -> ErpNextJournalEntryLine:
        debit = Decimal(self.debit)
        credit = Decimal(self.credit)
        if (debit > 0) == (credit > 0):
            raise ValueError("each Journal Entry line must have exactly one positive side")
        return self


class ErpNextJournalEntryDraft(BaseModel):
    """A closed, balanced ERPNext draft Journal Entry document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company: str = Field(min_length=1, max_length=160)
    posting_date: date
    accounts: tuple[ErpNextJournalEntryLine, ...] = Field(min_length=2, max_length=2_000)
    user_remark: str | None = Field(default=None, max_length=2_000)
    docstatus: Literal[0] = 0

    @model_validator(mode="after")
    def validate_balanced(self) -> ErpNextJournalEntryDraft:
        debit_total = sum((Decimal(line.debit) for line in self.accounts), Decimal("0"))
        credit_total = sum((Decimal(line.credit) for line in self.accounts), Decimal("0"))
        if debit_total != credit_total:
            raise ValueError("Journal Entry debit and credit totals must balance exactly")
        return self


@dataclass(frozen=True)
class ErpNextJournalEntryPayload:
    draft: ErpNextJournalEntryDraft
    operation: str
    payload: bytes
    payload_digest: str


def erpnext_writeback_registration(
    *, credential_reference: str, endpoint: str = ERP_NEXT_JOURNAL_ENTRY_ENDPOINT
) -> WritebackNetworkRegistration:
    """Bind an operator-owned ERPNext Journal Entry endpoint.

    The returned registration is intentionally disabled. An operator must
    enable it through the existing policy, maker-checker, and server-profile
    controls before any provider mutation can be attempted.
    """

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != ERP_NEXT_JOURNAL_ENTRY_PATH
    ):
        raise WritebackNetworkError("erpnext_writeback_endpoint_invalid")
    return WritebackNetworkRegistration(
        registration_schema="writeback-network-registration-v1",
        connector_id="erpnext-journal-entry-writeback",
        version="1.0.0",
        endpoint=endpoint,
        egress_destinations=(endpoint,),
        credential_reference=credential_reference,
        credential_auth_scheme="token",
        allowed_operations=frozenset({ERP_NEXT_JOURNAL_ENTRY_OPERATION}),
        allowed_compensation_operations=frozenset(),
        feature_enabled=False,
        synthetic_sandbox=True,
    )


def build_erpnext_journal_entry_payload(
    draft: ErpNextJournalEntryDraft,
) -> ErpNextJournalEntryPayload:
    """Serialize one balanced draft into deterministic Frappe REST JSON."""

    document = draft.model_dump(mode="json", exclude_none=True)
    document["doctype"] = "Journal Entry"
    payload = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return ErpNextJournalEntryPayload(
        draft=draft,
        operation=ERP_NEXT_JOURNAL_ENTRY_OPERATION,
        payload=payload,
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


__all__ = [
    "ERP_NEXT_JOURNAL_ENTRY_ENDPOINT",
    "ERP_NEXT_JOURNAL_ENTRY_OPERATION",
    "ERP_NEXT_JOURNAL_ENTRY_PATH",
    "ErpNextJournalEntryDraft",
    "ErpNextJournalEntryLine",
    "ErpNextJournalEntryPayload",
    "build_erpnext_journal_entry_payload",
    "erpnext_writeback_registration",
]
