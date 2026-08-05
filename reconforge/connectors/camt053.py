"""Bounded, offline ISO 20022 CAMT.053 statement ingestion.

This parser is intentionally a file/bytes boundary, not a bank connector.  It
accepts one ``BkToCstmrStmt/Stmt`` document, uses ``defusedxml`` to reject
entity expansion, preserves exact Decimal text as canonical strings, and
requires a stable bank-provided entry reference for every statement entry.
Provider credentials, network transport, and payment write-back are outside
this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

CAMT053_SCHEMA_VERSION = "camt.053.001-bounded-v1"
MAX_CAMT053_BYTES = 8 * 1024 * 1024
MAX_CAMT053_LINES = 100_000
MAX_TEXT_BYTES = 8_192


class Camt053Error(ValueError):
    """Safe, non-disclosing CAMT.053 validation error."""


@dataclass(frozen=True)
class Camt053Balance:
    balance_type: str
    amount: str
    currency: str
    direction: str
    signed_amount: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Camt053Line:
    line_id: str
    account_id: str
    amount: str
    currency: str
    direction: str
    signed_amount: str
    booking_date: str
    value_date: str
    bank_reference: str
    end_to_end_id: str | None
    transaction_id: str | None
    remittance_information: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Camt053Statement:
    schema_version: str
    message_id: str
    statement_id: str
    account_id: str
    opening_balance: Camt053Balance | None
    closing_balance: Camt053Balance | None
    lines: tuple[Camt053Line, ...]
    source_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "statement_id": self.statement_id,
            "account_id": self.account_id,
            "opening_balance": self.opening_balance.to_dict() if self.opening_balance else None,
            "closing_balance": self.closing_balance.to_dict() if self.closing_balance else None,
            "lines": [line.to_dict() for line in self.lines],
            "source_digest": self.source_digest,
        }


def _local_name(tag: object) -> str:
    value = str(tag)
    return value.rsplit("}", 1)[-1]


def _children(element: Any, name: str) -> list[Any]:
    return [child for child in list(element) if _local_name(child.tag) == name]


def _first(element: Any, *path: str) -> Any | None:
    current = element
    for name in path:
        matches = _children(current, name)
        if len(matches) != 1:
            return None
        current = matches[0]
    return current


def _text(element: Any | None, field: str, *, required: bool = True, maximum_bytes: int = MAX_TEXT_BYTES) -> str | None:
    value = "" if element is None or element.text is None else element.text.strip()
    if required and not value:
        raise Camt053Error(f"camt053_{field}_missing")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise Camt053Error(f"camt053_{field}_too_large")
    return value or None


def _canonical_decimal(value: str, field: str) -> str:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise Camt053Error(f"camt053_{field}_invalid") from exc
    if not parsed.is_finite():
        raise Camt053Error(f"camt053_{field}_non_finite")
    if parsed == 0:
        return "0"
    normalized = format(parsed.normalize(), "f")
    if normalized.endswith(".0"):
        normalized = normalized[:-2]
    return normalized


def _signed_amount(amount: str, direction: str, field: str) -> str:
    parsed = Decimal(amount)
    signed = parsed if direction == "CRDT" else -parsed
    return _canonical_decimal(str(signed), field)


def _currency(amount_element: Any, field: str) -> str:
    currency = str(amount_element.attrib.get("Ccy", "")).strip().upper()
    if not 3 <= len(currency) <= 12 or not currency.isalnum():
        raise Camt053Error(f"camt053_{field}_currency_invalid")
    return currency


def _date(element: Any | None, field: str) -> str:
    value = _text(element, field)
    if value is None:
        raise Camt053Error(f"camt053_{field}_missing")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise Camt053Error(f"camt053_{field}_invalid") from exc
    return parsed.isoformat()


def _account_id(stmt: Any) -> str:
    account = _first(stmt, "Acct")
    if account is None:
        raise Camt053Error("camt053_account_missing")
    iban = _text(_first(account, "Id", "IBAN"), "account_iban", required=False)
    other = _text(_first(account, "Id", "Othr", "Id"), "account_other_id", required=False)
    value = iban or other
    if value is None:
        raise Camt053Error("camt053_account_identifier_missing")
    return value


def _balance(stmt: Any, balance_type: str, code: str) -> Camt053Balance | None:
    matches: list[Any] = []
    for candidate in _children(stmt, "Bal"):
        code_element = _first(candidate, "Tp", "CdOrPrtry", "Cd")
        if _text(code_element, "balance_type", required=False) == code:
            matches.append(candidate)
    if not matches:
        return None
    if len(matches) != 1:
        raise Camt053Error(f"camt053_{balance_type}_balance_duplicate")
    candidate = matches[0]
    amount_element = _first(candidate, "Amt")
    if amount_element is None:
        raise Camt053Error(f"camt053_{balance_type}_balance_amount_missing")
    raw_amount = _text(amount_element, f"{balance_type}_balance_amount")
    if raw_amount is None:
        raise Camt053Error(f"camt053_{balance_type}_balance_amount_missing")
    amount = _canonical_decimal(raw_amount, f"{balance_type}_balance_amount")
    direction = _text(_first(candidate, "CdtDbtInd"), f"{balance_type}_balance_direction")
    if direction is None:
        raise Camt053Error(f"camt053_{balance_type}_balance_direction_missing")
    direction = direction.upper()
    if direction not in {"CRDT", "DBIT"}:
        raise Camt053Error(f"camt053_{balance_type}_balance_direction_invalid")
    return Camt053Balance(
        balance_type=balance_type,
        amount=amount,
        currency=_currency(amount_element, f"{balance_type}_balance"),
        direction=direction,
        signed_amount=_signed_amount(amount, direction, f"{balance_type}_balance_amount"),
    )


def _line(entry: Any, account_id: str, seen_ids: set[str]) -> Camt053Line:
    reference = _text(_first(entry, "NtryRef"), "entry_reference", required=False)
    service_reference = _text(_first(entry, "AcctSvcrRef"), "service_reference", required=False)
    line_id = reference or service_reference
    if line_id is None:
        raise Camt053Error("camt053_entry_identity_missing")
    if line_id in seen_ids:
        raise Camt053Error("camt053_entry_identity_duplicate")
    seen_ids.add(line_id)

    amount_element = _first(entry, "Amt")
    if amount_element is None:
        raise Camt053Error("camt053_entry_amount_missing")
    raw_amount = _text(amount_element, "entry_amount")
    if raw_amount is None:
        raise Camt053Error("camt053_entry_amount_missing")
    amount = _canonical_decimal(raw_amount, "entry_amount")
    direction = _text(_first(entry, "CdtDbtInd"), "entry_direction")
    if direction is None:
        raise Camt053Error("camt053_entry_direction_missing")
    direction = direction.upper()
    if direction not in {"CRDT", "DBIT"}:
        raise Camt053Error("camt053_entry_direction_invalid")
    booking_date = _date(_first(entry, "BookgDt", "Dt"), "booking_date")
    value_date = _date(_first(entry, "ValDt", "Dt"), "value_date")
    if value_date < booking_date:
        raise Camt053Error("camt053_value_date_before_booking_date")

    refs = _first(entry, "NtryDtls", "TxDtls", "Refs")
    end_to_end_id = _text(_first(refs, "EndToEndId"), "end_to_end_id", required=False) if refs is not None else None
    transaction_id = _text(_first(refs, "TxId"), "transaction_id", required=False) if refs is not None else None
    remittance = _first(entry, "NtryDtls", "TxDtls", "RmtInf")
    remittance_parts = [part for item in _children(remittance, "Ustrd") if (part := _text(item, "remittance", required=False))]
    remittance_information = " | ".join(remittance_parts)
    if len(remittance_information.encode("utf-8")) > MAX_TEXT_BYTES:
        raise Camt053Error("camt053_remittance_too_large")

    return Camt053Line(
        line_id=line_id,
        account_id=account_id,
        amount=amount,
        currency=_currency(amount_element, "entry"),
        direction=direction,
        signed_amount=_signed_amount(amount, direction, "entry_amount"),
        booking_date=booking_date,
        value_date=value_date,
        bank_reference=line_id,
        end_to_end_id=end_to_end_id,
        transaction_id=transaction_id,
        remittance_information=remittance_information,
    )


def parse_camt053_bytes(payload: bytes, *, maximum_bytes: int = MAX_CAMT053_BYTES) -> Camt053Statement:
    """Parse one bounded CAMT.053 statement from bytes."""

    if not isinstance(payload, bytes) or not payload:
        raise Camt053Error("camt053_payload_empty")
    if len(payload) > maximum_bytes or maximum_bytes < 1 or maximum_bytes > MAX_CAMT053_BYTES:
        raise Camt053Error("camt053_payload_too_large")
    try:
        root = ElementTree.fromstring(payload.lstrip())
    except (DefusedXmlException, ElementTree.ParseError, ValueError) as exc:
        raise Camt053Error("camt053_xml_invalid") from exc
    if _local_name(root.tag) != "Document":
        raise Camt053Error("camt053_document_root_invalid")
    message = _first(root, "BkToCstmrStmt")
    if message is None:
        raise Camt053Error("camt053_statement_message_missing")
    statements = _children(message, "Stmt")
    if len(statements) != 1:
        raise Camt053Error("camt053_requires_one_statement")
    stmt = statements[0]
    message_id = _text(_first(message, "GrpHdr", "MsgId"), "message_id")
    statement_id = _text(_first(stmt, "Id"), "statement_id")
    if message_id is None or statement_id is None:
        raise Camt053Error("camt053_statement_identity_missing")
    account_id = _account_id(stmt)
    entries = _children(stmt, "Ntry")
    if len(entries) > MAX_CAMT053_LINES:
        raise Camt053Error("camt053_entry_count_too_large")
    seen_ids: set[str] = set()
    lines = tuple(_line(entry, account_id, seen_ids) for entry in entries)
    statement = Camt053Statement(
        schema_version=CAMT053_SCHEMA_VERSION,
        message_id=message_id,
        statement_id=statement_id,
        account_id=account_id,
        opening_balance=_balance(stmt, "opening", "OPBD"),
        closing_balance=_balance(stmt, "closing", "CLBD"),
        lines=lines,
        source_digest="",
    )
    canonical = json.dumps(statement.to_dict() | {"source_digest": None}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return replace(statement, source_digest=hashlib.sha256(canonical.encode("ascii")).hexdigest())


def parse_camt053_file(path: str) -> Camt053Statement:
    """Read and parse one local CAMT.053 file without network access."""

    try:
        with open(path, "rb") as handle:
            payload = handle.read(MAX_CAMT053_BYTES + 1)
    except OSError as exc:
        raise Camt053Error("camt053_file_unreadable") from exc
    return parse_camt053_bytes(payload)


__all__ = [
    "CAMT053_SCHEMA_VERSION",
    "MAX_CAMT053_BYTES",
    "Camt053Balance",
    "Camt053Error",
    "Camt053Line",
    "Camt053Statement",
    "parse_camt053_bytes",
    "parse_camt053_file",
]
