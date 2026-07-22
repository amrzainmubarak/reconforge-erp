"""Shared strict value objects for local inventory services."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from reconforge.platform.common import PlatformError

DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 100_000
MAX_QUANTITY_SCALED = 9_000_000_000_000_000_000
MAX_AMOUNT_MINOR = 9_000_000_000_000_000_000
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
_QUANTITY_PATTERN = re.compile(r"^(0|[0-9]+)(\.[0-9]+)?$")
_AMOUNT_PATTERN = re.compile(r"^(0|[0-9]+)(\.[0-9]+)?$")


def clean_text(value: object, label: str, *, maximum: int = 160, required: bool = True) -> str:
    raw = str(value).strip() if value is not None else ""
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise PlatformError(f"{label} must contain printable characters only.")
    text = " ".join(raw.split())
    if required and not text:
        raise PlatformError(f"{label} is required.")
    if len(text) > maximum:
        raise PlatformError(f"{label} must not exceed {maximum} characters.")
    return text


def code(value: object, label: str) -> str:
    normalized = clean_text(value, label, maximum=64).upper()
    if not _CODE_PATTERN.fullmatch(normalized):
        raise PlatformError(f"{label} must use 1-64 uppercase letters, numbers, dots, underscores, or hyphens.")
    return normalized


def document_number(value: object, label: str) -> str:
    number = clean_text(value, label, maximum=64).upper()
    if not _NUMBER_PATTERN.fullmatch(number):
        raise PlatformError(f"{label} contains unsupported characters.")
    return number


def movement_number(value: object) -> str:
    return document_number(value, "Movement number")


def choice(value: object, label: str, choices: tuple[str, ...]) -> str:
    candidate = clean_text(value, label, maximum=40)
    selected = {item.lower(): item for item in choices}.get(candidate.lower())
    if selected is None:
        raise PlatformError(f"{label} must be one of: {', '.join(choices)}.")
    return selected


def iso_date(value: object, label: str, *, required: bool = True) -> date | None:
    raw = clean_text(value, label, maximum=10, required=required)
    if not raw and not required:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return parsed


def page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise PlatformError(f"List limit must be between 1 and {MAX_LIST_LIMIT}.")
    if not 0 <= offset <= 10_000_000:
        raise PlatformError("List offset must be between 0 and 10000000.")
    return limit, offset


def quantity_to_scaled(
    value: object,
    decimal_places: int,
    label: str = "Quantity",
    *,
    allow_zero: bool = False,
) -> int:
    if isinstance(value, bool | float):
        raise PlatformError(f"{label} must be supplied as an exact decimal string or integer.")
    raw = str(value).strip() if value is not None else ""
    if len(raw) > 64 or not _QUANTITY_PATTERN.fullmatch(raw):
        requirement = "non-negative" if allow_zero else "positive"
        raise PlatformError(f"{label} must be a valid {requirement} decimal quantity.")
    try:
        quantity = Decimal(raw)
    except InvalidOperation as exc:
        requirement = "non-negative" if allow_zero else "positive"
        raise PlatformError(f"{label} must be a valid {requirement} decimal quantity.") from exc
    scaled = quantity * (Decimal(10) ** decimal_places)
    if quantity < 0 or (quantity == 0 and not allow_zero):
        comparator = "zero or greater" if allow_zero else "greater than zero"
        raise PlatformError(f"{label} must be {comparator}.")
    if scaled != scaled.to_integral_value():
        raise PlatformError(f"{label} exceeds the unit's {decimal_places}-decimal precision.")
    result = int(scaled)
    if result > MAX_QUANTITY_SCALED:
        raise PlatformError(f"{label} exceeds the supported local quantity range.")
    return result


def scaled_to_text(value: int, decimal_places: int) -> str:
    quantity = Decimal(value).scaleb(-decimal_places)
    return f"{quantity:.{decimal_places}f}"


def amount_to_minor(value: object, minor_units: int, label: str = "Amount") -> int:
    """Parse a non-negative exact amount into currency minor units."""

    if isinstance(value, bool | float):
        raise PlatformError(f"{label} must be supplied as an exact decimal string or integer.")
    raw = str(value).strip() if value is not None else ""
    if len(raw) > 64 or not _AMOUNT_PATTERN.fullmatch(raw):
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.") from exc
    scaled = amount * (Decimal(10) ** minor_units)
    if scaled != scaled.to_integral_value():
        raise PlatformError(f"{label} exceeds the currency's {minor_units}-decimal precision.")
    result = int(scaled)
    if result > MAX_AMOUNT_MINOR:
        raise PlatformError(f"{label} exceeds the supported local amount range.")
    return result


def minor_to_text(value: int, minor_units: int) -> str:
    """Format stored minor units without binary floating-point conversion."""

    amount = Decimal(value).scaleb(-minor_units)
    return f"{amount:.{minor_units}f}"


def public_record(row: sqlite3.Row | Mapping[str, object]) -> dict[str, Any]:
    record = dict(row)
    for field in ("active", "allow_negative"):
        if field in record:
            record[field] = bool(record[field])
    return record
