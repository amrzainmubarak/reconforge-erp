"""Deterministic, non-posting intercompany elimination proposals.

The builder deliberately requires explicit group-account mappings and signed
source amounts.  It never infers an account, currency conversion, tax effect,
or statutory treatment.  A source group is proposed only when reciprocal
entity coverage and exact zero-sum balance are both proven; otherwise the
group is returned as unresolved with a machine-readable reason.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from reconforge.domain.consolidation import ConsolidationAccountType, ConsolidationError
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationElimination,
    ConsolidationEliminationLine,
)
from reconforge.utils.money import InvalidAmountError, Money

INTERCOMPANY_ELIMINATION_SCHEMA_VERSION = 1
INTERCOMPANY_ELIMINATION_ALGORITHM_VERSION = "intercompany-elimination-v1"
MAX_INTERCOMPANY_LINES = 100_000
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SEMVER_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_ACCOUNT_TYPES = frozenset({"Asset", "Liability", "Equity", "Income", "Expense"})

IntercompanyResolutionStatus = Literal["proposed", "unresolved"]


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value.strip()):
        raise ConsolidationError(f"{field} is invalid.")
    return value.strip()


def _bounded_text(value: object, field: str, *, optional: bool = False, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} is invalid.")
    clean = value.strip()
    if optional and clean == "":
        return ""
    if not clean or len(clean) > maximum or any(ord(character) < 32 for character in clean):
        raise ConsolidationError(f"{field} is invalid.")
    return clean


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ConsolidationError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _semver(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise ConsolidationError(f"{field} must be an exact semantic version.")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        raise ConsolidationError(f"{field} must use whole-second timezone-aware precision.")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class IntercompanyEliminationInputLine:
    """One explicitly mapped, signed source ledger line."""

    transaction_id: str
    period_name: str
    entity_code: str
    counterparty_code: str
    reference: str
    group_account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    source_reference: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "transaction_id", _identifier(self.transaction_id, "Transaction identifier"))
        object.__setattr__(self, "period_name", _identifier(self.period_name, "Intercompany period"))
        object.__setattr__(self, "entity_code", _identifier(self.entity_code, "Intercompany entity"))
        object.__setattr__(self, "counterparty_code", _identifier(self.counterparty_code, "Intercompany counterparty"))
        object.__setattr__(self, "reference", _identifier(self.reference, "Intercompany reference"))
        object.__setattr__(self, "group_account_code", _identifier(self.group_account_code, "Group account code"))
        if self.entity_code == self.counterparty_code:
            raise ConsolidationError("Intercompany entity and counterparty must be different.")
        if self.account_type not in _ACCOUNT_TYPES:
            raise ConsolidationError("Intercompany account type is not supported.")
        if not isinstance(self.amount, Money) or self.amount.amount == 0:
            raise ConsolidationError("Intercompany source amounts must be non-zero Money values.")
        object.__setattr__(self, "source_reference", _bounded_text(self.source_reference, "Intercompany source"))
        object.__setattr__(self, "source_digest", _sha256(self.source_digest, "Intercompany source digest"))

    def to_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "counterparty_code": self.counterparty_code,
            "entity_code": self.entity_code,
            "group_account_code": self.group_account_code,
            "period_name": self.period_name,
            "reference": self.reference,
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
            "transaction_id": self.transaction_id,
        }


def intercompany_elimination_input_line_from_dict(
    payload: Mapping[str, object],
) -> IntercompanyEliminationInputLine:
    """Decode one exact persisted source line without weakening domain checks."""

    if not isinstance(payload, Mapping):
        raise ConsolidationError("Intercompany source line must be an object.")
    expected_keys = {
        "account_type",
        "amount",
        "counterparty_code",
        "entity_code",
        "group_account_code",
        "period_name",
        "reference",
        "source_digest",
        "source_reference",
        "transaction_id",
    }
    if set(payload) != expected_keys:
        raise ConsolidationError("Intercompany source line fields are not exact.")
    amount = payload["amount"]
    if not isinstance(amount, Mapping):
        raise ConsolidationError("Intercompany source amount is invalid.")
    try:
        money = Money.from_canonical_dict(dict(amount))
        return IntercompanyEliminationInputLine(
            transaction_id=payload["transaction_id"],  # type: ignore[arg-type]
            period_name=payload["period_name"],  # type: ignore[arg-type]
            entity_code=payload["entity_code"],  # type: ignore[arg-type]
            counterparty_code=payload["counterparty_code"],  # type: ignore[arg-type]
            reference=payload["reference"],  # type: ignore[arg-type]
            group_account_code=payload["group_account_code"],  # type: ignore[arg-type]
            account_type=payload["account_type"],  # type: ignore[arg-type]
            amount=money,
            source_reference=payload["source_reference"],  # type: ignore[arg-type]
            source_digest=payload["source_digest"],  # type: ignore[arg-type]
        )
    except (ConsolidationError, InvalidAmountError, TypeError, ValueError, KeyError) as exc:
        raise ConsolidationError("Intercompany source line failed deterministic decoding.") from exc


@dataclass(frozen=True)
class IntercompanyEliminationResolution:
    """One deterministic source group, proposed or explicitly unresolved."""

    group_key: str
    status: IntercompanyResolutionStatus
    source_transaction_ids: tuple[str, ...]
    source_group_digest: str
    proposal: ConsolidationElimination | None
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_key", _identifier(self.group_key, "Intercompany group key"))
        if self.status not in {"proposed", "unresolved"}:
            raise ConsolidationError("Intercompany resolution status is invalid.")
        if not self.source_transaction_ids or tuple(sorted(self.source_transaction_ids)) != self.source_transaction_ids:
            raise ConsolidationError("Intercompany source transaction IDs must be sorted and non-empty.")
        if len(set(self.source_transaction_ids)) != len(self.source_transaction_ids):
            raise ConsolidationError("Intercompany source transaction IDs must be unique.")
        object.__setattr__(self, "source_group_digest", _sha256(self.source_group_digest, "Source group digest"))
        object.__setattr__(self, "reason", _bounded_text(self.reason, "Intercompany resolution reason"))
        if self.status == "proposed" and not isinstance(self.proposal, ConsolidationElimination):
            raise ConsolidationError("A proposed intercompany group requires an elimination proposal.")
        if self.status == "unresolved" and self.proposal is not None:
            raise ConsolidationError("An unresolved intercompany group cannot contain a proposal.")

    def to_dict(self) -> dict[str, object]:
        return {
            "group_key": self.group_key,
            "proposal": self.proposal.to_input_dict() if self.proposal is not None else None,
            "reason": self.reason,
            "source_group_digest": self.source_group_digest,
            "source_transaction_ids": list(self.source_transaction_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class IntercompanyEliminationResult:
    """Replayable portfolio of proposed and unresolved intercompany groups."""

    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    reporting_currency: str
    version: str
    prepared_by: str
    prepared_at: str
    resolutions: tuple[IntercompanyEliminationResolution, ...]

    def __post_init__(self) -> None:
        if self.schema_version != INTERCOMPANY_ELIMINATION_SCHEMA_VERSION:
            raise ConsolidationError("Intercompany elimination schema version is unsupported.")
        if self.algorithm_version != INTERCOMPANY_ELIMINATION_ALGORITHM_VERSION:
            raise ConsolidationError("Intercompany elimination algorithm version is unsupported.")
        object.__setattr__(self, "request_digest", _sha256(self.request_digest, "Intercompany request digest"))
        object.__setattr__(self, "result_digest", _sha256(self.result_digest, "Intercompany result digest"))
        object.__setattr__(self, "reporting_currency", _identifier(self.reporting_currency, "Reporting currency"))
        object.__setattr__(self, "version", _semver(self.version, "Intercompany elimination version"))
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Intercompany preparer"))
        object.__setattr__(self, "prepared_at", _timestamp(self.prepared_at, "Intercompany preparation timestamp"))
        if not isinstance(self.resolutions, tuple) or tuple(sorted(self.resolutions, key=lambda item: item.group_key)) != self.resolutions:
            raise ConsolidationError("Intercompany resolutions must be sorted by group key.")
        if len({item.group_key for item in self.resolutions}) != len(self.resolutions):
            raise ConsolidationError("Intercompany group keys must be unique.")

    def _payload(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "resolutions": [item.to_dict() for item in self.resolutions],
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["result_digest"] = self.result_digest
        return payload


def _source_group_digest(lines: tuple[IntercompanyEliminationInputLine, ...]) -> str:
    return _digest({"lines": [line.to_dict() for line in sorted(lines, key=lambda item: item.transaction_id)]})


def _request_digest(
    *,
    reporting_currency: str,
    version: str,
    prepared_by: str,
    prepared_at: str,
    lines: tuple[IntercompanyEliminationInputLine, ...],
) -> str:
    return _digest(
        {
            "algorithm_version": INTERCOMPANY_ELIMINATION_ALGORITHM_VERSION,
            "lines": [line.to_dict() for line in sorted(lines, key=lambda item: item.transaction_id)],
            "prepared_at": prepared_at,
            "prepared_by": prepared_by,
            "reporting_currency": reporting_currency,
            "schema_version": INTERCOMPANY_ELIMINATION_SCHEMA_VERSION,
            "version": version,
        }
    )


def _unresolved(
    *,
    group_key: str,
    lines: tuple[IntercompanyEliminationInputLine, ...],
    reason: str,
) -> IntercompanyEliminationResolution:
    return IntercompanyEliminationResolution(
        group_key=group_key,
        status="unresolved",
        source_transaction_ids=tuple(sorted(line.transaction_id for line in lines)),
        source_group_digest=_source_group_digest(lines),
        proposal=None,
        reason=reason,
    )


def prepare_intercompany_eliminations(
    lines: tuple[IntercompanyEliminationInputLine, ...],
    *,
    reporting_currency: str,
    prepared_by: str,
    prepared_at: str,
    version: str = "1.0.0",
) -> IntercompanyEliminationResult:
    """Build only exact, source-bound reciprocal elimination proposals.

    Groups are keyed by period, explicit reference, and currency.  A group is
    proposed only when every source currency equals the reporting currency,
    entity/counterparty coverage is reciprocal, and the signed source total is
    exactly zero.  Any failure is retained as an unresolved result instead of
    being silently dropped or rounded into balance.
    """

    if not isinstance(lines, tuple) or len(lines) > MAX_INTERCOMPANY_LINES:
        raise ConsolidationError("Intercompany elimination input exceeds the bounded line limit.")
    reporting_currency = _identifier(reporting_currency, "Reporting currency")
    try:
        Money.from_exact("0", reporting_currency, strict_precision=True)
    except InvalidAmountError as exc:
        raise ConsolidationError("Reporting currency is not registered.") from exc
    prepared_by = _identifier(prepared_by, "Intercompany preparer")
    prepared_at = _timestamp(prepared_at, "Intercompany preparation timestamp")
    version = _semver(version, "Intercompany elimination version")
    if any(not isinstance(line, IntercompanyEliminationInputLine) for line in lines):
        raise ConsolidationError("Intercompany elimination lines are invalid.")
    if len({line.transaction_id for line in lines}) != len(lines):
        raise ConsolidationError("Intercompany transaction IDs must be unique.")
    if any(line.amount.currency != reporting_currency for line in lines):
        raise ConsolidationError("Intercompany elimination lines must already use the reporting currency.")

    request_digest = _request_digest(
        reporting_currency=reporting_currency,
        version=version,
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        lines=lines,
    )
    grouped: dict[tuple[str, str, str], list[IntercompanyEliminationInputLine]] = {}
    for line in lines:
        grouped.setdefault((line.period_name, line.reference, line.amount.currency), []).append(line)

    resolutions: list[IntercompanyEliminationResolution] = []
    for period_name, reference, currency in sorted(grouped):
        group = tuple(sorted(grouped[(period_name, reference, currency)], key=lambda item: item.transaction_id))
        group_key = f"IC-GROUP-{_digest({'currency': currency, 'period_name': period_name, 'reference': reference})[:24]}"
        entities = {line.entity_code for line in group}
        counterparties = {line.counterparty_code for line in group}
        if len(group) < 2 or len(entities) < 2:
            resolutions.append(_unresolved(group_key=group_key, lines=group, reason="insufficient_reciprocal_lines"))
            continue
        if entities != counterparties:
            resolutions.append(_unresolved(group_key=group_key, lines=group, reason="non_reciprocal_entity_coverage"))
            continue
        total = sum((line.amount.amount for line in group), start=Decimal("0"))
        if total != 0:
            resolutions.append(_unresolved(group_key=group_key, lines=group, reason="source_group_is_not_zero_sum"))
            continue

        source_digest = _source_group_digest(group)
        elimination_id = f"IC-ELIM-{source_digest[:20]}"
        elimination_lines = tuple(
            ConsolidationEliminationLine(
                line_id=f"{elimination_id}:line:{index:06d}",
                entity_code=line.entity_code,
                group_account_code=line.group_account_code,
                account_type=line.account_type,
                amount=Money.from_exact(-line.amount.amount, currency, strict_precision=True),
                source_reference=f"intercompany:{line.transaction_id}:source:{line.source_digest}",
                source_digest=line.source_digest,
            )
            for index, line in enumerate(group, start=1)
        )
        proposal = ConsolidationElimination(
            elimination_id=elimination_id,
            elimination_type="intercompany_transaction",
            version=version,
            lines=elimination_lines,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            rationale=(
                f"Exact reciprocal intercompany elimination for period {period_name}, "
                f"reference {reference}, source group {source_digest}."
            ),
        )
        resolutions.append(
            IntercompanyEliminationResolution(
                group_key=group_key,
                status="proposed",
                source_transaction_ids=tuple(line.transaction_id for line in group),
                source_group_digest=source_digest,
                proposal=proposal,
                reason="exact_reciprocal_zero_sum_group",
            )
        )

    ordered = tuple(sorted(resolutions, key=lambda item: item.group_key))
    result = IntercompanyEliminationResult(
        schema_version=INTERCOMPANY_ELIMINATION_SCHEMA_VERSION,
        algorithm_version=INTERCOMPANY_ELIMINATION_ALGORITHM_VERSION,
        request_digest=request_digest,
        result_digest="0" * 64,
        reporting_currency=reporting_currency,
        version=version,
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        resolutions=ordered,
    )
    return replace(result, result_digest=_digest(result._payload()))


def verify_intercompany_elimination_payload(
    payload: Mapping[str, object],
    lines: tuple[IntercompanyEliminationInputLine, ...],
) -> IntercompanyEliminationResult:
    """Replay a result against the original typed source lines."""

    if not isinstance(payload, Mapping):
        raise ConsolidationError("Intercompany elimination result must be an object.")
    expected_keys = {
        "algorithm_version",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "request_digest",
        "resolutions",
        "result_digest",
        "schema_version",
        "version",
    }
    if set(payload) != expected_keys:
        raise ConsolidationError("Intercompany elimination result fields are not exact.")
    result = prepare_intercompany_eliminations(
        lines,
        reporting_currency=payload["reporting_currency"],  # type: ignore[arg-type]
        version=payload["version"],  # type: ignore[arg-type]
        prepared_by=payload["prepared_by"],  # type: ignore[arg-type]
        prepared_at=payload["prepared_at"],  # type: ignore[arg-type]
    )
    if not hmac.compare_digest(
        json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    ):
        raise ConsolidationError("Intercompany elimination result does not reproduce from its source lines.")
    return result
