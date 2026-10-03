"""Exact, versioned content and human provenance for operational postings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

VALIDATION_CONTRACT_VERSION = "finance-entry-review-v1"
MAX_SNAPSHOT_BYTES = 2_097_152
PROVENANCE_FIELDS = (
    "preparer_actor_id",
    "validator_actor_id",
    "validation_digest",
    "validation_contract_version",
    "reverses_posting_id",
)
HEADER_FIELDS = (
    "id",
    "workspace_id",
    "organization_id",
    "legal_entity_id",
    "journal_id",
    "period_id",
    "entry_number",
    "posting_date",
    "description",
    "external_reference",
    "source_type",
    "currency_code",
    "currency_precision",
    "currency_rounding_policy",
    "currency_registry_version",
    "currency_registry_digest",
    "preparer_actor_id",
    "reverses_posting_id",
)
LINE_FIELDS = ("line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions")


class FinancePostingError(ValueError):
    """Stable, safe business failure shared by all posting adapters."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def text(value: object, field: str, *, maximum: int = 160) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise FinancePostingError(
            "posting_request_invalid", f"{field} must be nonempty printable text of at most {maximum} characters."
        )
    return value.strip()


@dataclass(frozen=True)
class PostingActor:
    """An identity supplied by a verified API/CLI authentication boundary."""

    user_id: str
    username: str
    permissions: frozenset[str]
    principal_type: str = "user"
    step_up_active: bool = False

    def require(self, permission: str, *, mutation: bool = True) -> None:
        text(self.user_id, "actor identity")
        text(self.username, "actor username")
        if self.principal_type != "user":
            raise FinancePostingError("posting_human_required", "Operational posting requires an authenticated human.")
        if permission not in self.permissions:
            raise FinancePostingError("posting_permission_denied", f"Permission {permission} is required.")
        if mutation and not self.step_up_active:
            raise FinancePostingError("posting_step_up_required", "Recent human reauthentication is required.")


def canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("oversized payload")
        return encoded
    except (TypeError, ValueError) as exc:
        raise FinancePostingError(
            "posting_payload_invalid", "Posting evidence must be bounded canonical JSON."
        ) from exc


def digest_payload(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_entry_snapshot(entry: Mapping[str, Any], lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Adapt exact stored values; never parse a float or infer historical policy."""
    if (
        not isinstance(entry, Mapping)
        or not isinstance(lines, (list, tuple))
        or any(not isinstance(line, Mapping) for line in lines)
    ):
        raise FinancePostingError(
            "posting_content_invalid", "Posting content requires an entry and stored line mappings."
        )
    header: dict[str, Any] = {key: entry.get(key) for key in HEADER_FIELDS}
    for key in HEADER_FIELDS:
        if key in {"reverses_posting_id", "preparer_actor_id"} and header[key] is None:
            continue
        if key == "currency_precision":
            if type(header[key]) is not int or not 0 <= header[key] <= 8:
                raise FinancePostingError("posting_policy_unverified", "A verified currency precision is required.")
        elif key in {"description", "external_reference"}:
            if not isinstance(header[key], str) or len(header[key]) > 500:
                raise FinancePostingError("posting_content_invalid", "Entry text must be retained exactly.")
        else:
            header[key] = text(header[key], key, maximum=500 if key == "description" else 160)
    if header["currency_rounding_policy"] != "ROUND_HALF_UP":
        raise FinancePostingError("posting_policy_unverified", "Unsupported retained rounding policy.")
    if len(header["currency_registry_digest"]) != 64 or any(
        c not in "0123456789abcdef" for c in header["currency_registry_digest"]
    ):
        raise FinancePostingError("posting_policy_unverified", "A retained currency registry digest is required.")
    try:
        date.fromisoformat(header["posting_date"])
    except ValueError as exc:
        raise FinancePostingError("posting_content_invalid", "Posting date must be an ISO business date.") from exc
    normalized = []
    numbers: set[int] = set()
    debit = credit = 0
    if not 2 <= len(lines) <= 1000:
        raise FinancePostingError("posting_content_invalid", "Posting requires between 2 and 1000 lines.")
    for line in lines:
        item: dict[str, Any] = {key: line.get(key) for key in LINE_FIELDS}
        for key in ("line_number", "debit_minor", "credit_minor"):
            if type(item[key]) is not int or not 0 <= item[key] <= 9_223_372_036_854_775_807:
                raise FinancePostingError(
                    "posting_content_invalid", "Posting amounts require bounded integer minor units."
                )
        if (
            item["line_number"] < 1
            or item["line_number"] in numbers
            or (item["debit_minor"] == 0) == (item["credit_minor"] == 0)
        ):
            raise FinancePostingError(
                "posting_content_invalid", "Each unique line requires exactly one positive debit or credit."
            )
        numbers.add(item["line_number"])
        item["account_id"] = text(item["account_id"], "account_id")
        if (
            not isinstance(item["description"], str)
            or len(item["description"]) > 500
            or not isinstance(item["dimensions"], Mapping)
        ):
            raise FinancePostingError("posting_content_invalid", "Stored line content is invalid.")
        item["dimensions"] = {
            text(k, "dimension_id"): text(v, "dimension_value_id") for k, v in item["dimensions"].items()
        }
        debit += item["debit_minor"]
        credit += item["credit_minor"]
        normalized.append(item)
    if debit != credit or debit <= 0 or debit > 9_223_372_036_854_775_807:
        raise FinancePostingError(
            "posting_unbalanced", "Operational postings must balance exactly within supported minor-unit bounds."
        )
    return {
        "schema_version": VALIDATION_CONTRACT_VERSION,
        "entry": header,
        "lines": sorted(normalized, key=lambda line: line["line_number"]),
    }


def validation_digest(snapshot: Mapping[str, Any]) -> str:
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"schema_version", "entry", "lines"}
        or snapshot["schema_version"] != VALIDATION_CONTRACT_VERSION
    ):
        raise FinancePostingError("posting_content_invalid", "Unsupported posting review contract.")
    normalized = make_entry_snapshot(snapshot["entry"], snapshot["lines"])
    if normalized != snapshot:
        raise FinancePostingError("posting_content_invalid", "Posting snapshot is not canonical.")
    return digest_payload(normalized)


def require_reviewed(entry: Mapping[str, Any], snapshot: Mapping[str, Any], actor: PostingActor) -> str:
    actor.require("finance_core.post")
    preparer, reviewer = entry.get("preparer_actor_id"), entry.get("validator_actor_id")
    if not preparer or not reviewer or entry.get("validation_contract_version") != VALIDATION_CONTRACT_VERSION:
        raise FinancePostingError(
            "posting_review_unverified",
            "Prepare a new authenticated draft and obtain independent review; legacy provenance is not inferred.",
        )
    if preparer == reviewer or actor.user_id == preparer:
        raise FinancePostingError("posting_sod_denied", "The preparer cannot review or post their own entry.")
    digest = validation_digest(snapshot)
    if entry.get("validation_digest") != digest:
        raise FinancePostingError(
            "posting_review_changed", "Entry content differs from its independently reviewed digest."
        )
    if entry.get("status") != "Validated":
        raise FinancePostingError("posting_state_invalid", "Only independently Validated entries can be posted.")
    return digest


def require_full_reversal(original: Mapping[str, Any], reversal: Mapping[str, Any]) -> None:
    validation_digest(original)
    validation_digest(reversal)
    fields = (
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "journal_id",
        "currency_code",
        "currency_precision",
        "currency_rounding_policy",
        "currency_registry_version",
        "currency_registry_digest",
    )
    if any(original["entry"][key] != reversal["entry"][key] for key in fields):
        raise FinancePostingError(
            "posting_reversal_invalid", "A full reversal must retain original scope and currency policy."
        )

    def amounts(lines: Sequence[Mapping[str, Any]], inverse: bool) -> list[str]:
        return sorted(
            canonical_json(
                {
                    "account_id": line["account_id"],
                    "debit_minor": line["credit_minor"] if inverse else line["debit_minor"],
                    "credit_minor": line["debit_minor"] if inverse else line["credit_minor"],
                    "dimensions": line["dimensions"],
                }
            )
            for line in lines
        )

    if amounts(original["lines"], True) != amounts(reversal["lines"], False):
        raise FinancePostingError(
            "posting_reversal_invalid", "A full reversal must exactly invert every original line and dimension."
        )
