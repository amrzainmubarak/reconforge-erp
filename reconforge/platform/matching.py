"""Scalable deterministic matching foundations."""

from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from re import compile as regex_compile
from re import error as regex_error
from re import findall, sub
from typing import Any, Literal, cast
from unicodedata import normalize as normalize_unicode

from reconforge.audit import AuditLedgerError
from reconforge.domain.models import utc_now_text
from reconforge.io.persisted import (
    PersistedJsonError,
    PersistedJsonObjectDocument,
    decode_sqlite_matching_rule,
    encode_sqlite_matching_lineage,
    encode_sqlite_matching_rule,
)
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    audit,
    date_diff_days,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    parse_date,
    platform_id,
    read_local_record_document,
    require_permission,
    rows_to_dicts,
)
from reconforge.reconciliation.matching import (
    INTERNAL_LINEAGE_COLUMNS,
    RECORD_IDENTITY_POLICY,
    SOURCE_POSITION_COLUMN,
    SOURCE_ROW_BASIS_COLUMN,
    SOURCE_ROW_COLUMN,
)
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    parse_amount_for_currency_precision,
    round_exact_money,
    validate_financial_input_policy,
)

_KNOWN_CURRENCY_FIELDS = ("currency", "currency_code", "ccy")
_RECORD_SEQUENCE_BASIS = "record-sequence-v1"
_JSON_RECORD_BASIS = "json-record-position-v1"
_SOURCE_LOCATION_UNAVAILABLE_BASIS = "source-location-unavailable-v1"
LEGACY_RECORD_IDENTITY_POLICY = "row-order-occurrence-legacy-v0"


def _exception_identity_payload(value: object) -> str:
    """Serialize an exception payload into canonical JSON for hashing."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: _decimal_text(item) if isinstance(item, Decimal) else str(item),
    )


def _exception_id(
    *,
    exception_type: str,
    source_side: str,
    source_id: str,
    code: str,
    title: str,
    explanation: str,
    severity: str,
    risk_score: str,
    evidence: dict[str, object],
) -> str:
    """Build a stable exception identifier independent of row order."""

    payload = {
        "exception_type": exception_type,
        "source_side": source_side,
        "source_id": source_id,
        "reason_code": code,
        "title": title,
        "explanation": explanation,
        "severity": severity,
        "risk_score": risk_score,
        "evidence": {key: value for key, value in evidence.items() if key != "source_location"},
    }
    digest = hashlib.sha256(_exception_identity_payload(payload).encode("utf-8")).hexdigest()[:20].upper()
    return f"EXC-{digest}"


def _extract_currency_code(record: dict[str, Any]) -> str:
    """Read currency code from supported field variants."""

    for field in _KNOWN_CURRENCY_FIELDS:
        code = normalize_key(record.get(field), default="")
        if code:
            return code
    return ""


def _resolve_currency_precision(
    connection: sqlite3.Connection,
    cache: dict[str, tuple[int | None, str | None]],
    raw_code: str,
) -> tuple[str, int | None]:
    """Resolve minor-unit precision from the local currency table when possible."""

    if not raw_code:
        return "", None
    if raw_code in cache:
        precision, issue = cache[raw_code]
        if issue is not None:
            raise InvalidAmountError(issue)
        return raw_code, precision
    row = connection.execute("SELECT minor_units, active FROM currencies WHERE code = ?", (raw_code,)).fetchone()
    if row is None:
        cache[raw_code] = (None, "UNKNOWN_CURRENCY")
        raise InvalidAmountError("UNKNOWN_CURRENCY")
    if not bool(row["active"]):
        cache[raw_code] = (None, "INACTIVE_CURRENCY")
        raise InvalidAmountError("INACTIVE_CURRENCY")
    precision = int(row["minor_units"])
    cache[raw_code] = (precision, None)
    return raw_code, precision


def _matching_input_policy(value: object) -> FinancialInputPolicy:
    """Validate one public matching input policy without echoing its value."""

    try:
        return validate_financial_input_policy(value)
    except InvalidAmountError as exc:
        raise PlatformError("Unsupported financial input policy.") from exc


def _matching_record_identity_policy(value: object) -> str:
    if value in {LEGACY_RECORD_IDENTITY_POLICY, RECORD_IDENTITY_POLICY}:
        return str(value)
    raise PlatformError("Unsupported record identity policy.")


def _parse_amount(
    value: object,
    *,
    precision: int | None = None,
    input_policy: FinancialInputPolicy,
) -> Decimal | None:
    """Parse a strict amount with optional currency precision enforcement."""

    try:
        if precision is None:
            return parse_amount(value, input_policy=input_policy)
        return parse_amount_for_currency_precision(
            value,
            precision=precision,
            input_policy=input_policy,
        )
    except InvalidAmountError:
        return None


def _amount_bucket_key(value: Decimal, precision: int | None) -> str:
    """Build a deterministic bucket key for amount matching without assumptions.

    For known currency precisions we quantize the bucket explicitly.
    For unknown precision we use the canonical normalized decimal text.
    """

    if precision is None:
        normalized = value.normalize()
        return _decimal_text(normalized)
    return str(round_exact_money(value, places=precision))


def _non_negative_amount(
    value: object,
    *,
    field: str,
    input_policy: FinancialInputPolicy,
) -> Decimal:
    """Parse a non-negative monetary policy value without float arithmetic."""

    try:
        parsed = parse_amount(value, input_policy=input_policy)
    except InvalidAmountError as exc:
        raise PlatformError(f"Invalid financial amount for {field}.") from exc
    if parsed < 0:
        raise PlatformError(f"Invalid financial amount for {field}: value must be non-negative.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    """Serialize a Decimal without scientific notation or binary conversion."""

    return format(value, "f")


def _record_identity_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        normalized = Decimal("0") if value == 0 else value.normalize()
        return format(normalized, "f")
    return str(value).strip()


def _coerce_confidence(value: object, *, field: str = "confidence") -> Decimal:
    """Convert a matcher confidence value to a stable Decimal representation."""

    if isinstance(value, Decimal):
        return value
    if value in {None, ""}:
        return Decimal("0")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(str(value))
    except (TypeError, InvalidOperation) as exc:
        raise PlatformError(f"Invalid {field} value produced by matching engine: {value!r}.") from exc


@dataclass(frozen=True)
class ReferenceNormalizationRules:
    """Normalization settings for deterministic reference matching."""

    unicode_normalization: str = "NFKC"
    case: str = "upper"
    trim_whitespace: bool = True
    remove_whitespace: bool = True
    separator_normalizations: tuple[tuple[str, str], ...] = ()
    strip_prefixes: tuple[str, ...] = ()
    strip_suffixes: tuple[str, ...] = ()
    leading_zeros: bool = True
    regex_normalizations: tuple[tuple[str, str], ...] = ()


def _string_pairs(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    """Parse normalization replacements from a JSON-style sequence."""

    if value in (None, "", ()):  # no-op default path
        return ()
    if not isinstance(value, list | tuple):
        raise PlatformError(f"{field_name} must be a list of two-value string pairs.")
    parsed: list[tuple[str, str]] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            raise PlatformError(f"{field_name}[{index}] must contain exactly two values.")
        parsed.append((str(pair[0]), str(pair[1])))
    return tuple(parsed)


def _string_values(value: object, *, field_name: str) -> tuple[str, ...]:
    """Parse a list of strings from a JSON-style sequence."""

    if value in (None, "", ()):  # no-op default path
        return ()
    if not isinstance(value, list | tuple):
        raise PlatformError(f"{field_name} must be a list of strings.")
    return tuple(str(item) for item in value)


def _validate_regex_normalization_rules(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    """Parse regex normalization rules and fail fast for invalid patterns."""

    pairs = _string_pairs(value, field_name=field_name)
    for index, (pattern, _replacement) in enumerate(pairs):
        try:
            regex_compile(pattern)
        except regex_error as exc:
            raise PlatformError(f"{field_name}[{index}] must be a valid regular expression.") from exc
    return pairs


def _parse_reference_normalization_rules(
    rules: object | None,
) -> ReferenceNormalizationRules:
    """Build a stable, typed reference-normalization rule bundle."""

    if rules is None:
        return ReferenceNormalizationRules()
    if not isinstance(rules, Mapping):
        raise PlatformError("reference_normalization_rules must be a mapping.")
    case = str(rules.get("case", "upper")).lower()
    if case not in {"upper", "lower", "none"}:
        raise PlatformError("reference_normalization_rules.case must be one of: upper, lower, none.")
    return ReferenceNormalizationRules(
        unicode_normalization=str(rules.get("unicode_normalization", "NFKC")),
        case=case,
        trim_whitespace=bool(rules.get("trim_whitespace", True)),
        remove_whitespace=bool(rules.get("remove_whitespace", True)),
        separator_normalizations=_string_pairs(
            rules.get("separator_normalizations", ()),
            field_name="reference_normalization_rules.separator_normalizations",
        ),
        strip_prefixes=_string_values(
            rules.get("strip_prefixes", ()),
            field_name="reference_normalization_rules.strip_prefixes",
        ),
        strip_suffixes=_string_values(
            rules.get("strip_suffixes", ()),
            field_name="reference_normalization_rules.strip_suffixes",
        ),
        leading_zeros=bool(rules.get("leading_zeros", True)),
        regex_normalizations=_validate_regex_normalization_rules(
            rules.get("regex_normalizations", ()),
            field_name="reference_normalization_rules.regex_normalizations",
        ),
    )


def _normalize_reference(
    value: object,
    *,
    rules: ReferenceNormalizationRules | None = None,
) -> str:
    """Normalize references for matching while preserving numeric meaning."""

    options = rules or ReferenceNormalizationRules()
    text = normalize_unicode(
        cast(Literal["NFC", "NFD", "NFKC", "NFKD"], options.unicode_normalization),
        normalize_text(value, default=""),
    )
    if options.trim_whitespace:
        text = text.strip()
    if options.remove_whitespace:
        text = "".join(part for part in text.split())
    if options.case == "upper":
        text = text.upper()
    elif options.case == "lower":
        text = text.lower()
    for prefix in options.strip_prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in options.strip_suffixes:
        if suffix and text.endswith(suffix):
            text = text[: -len(suffix)]
    if not text:
        return ""
    for pattern, replacement in options.regex_normalizations:
        text = sub(pattern, replacement, text)
    for source, replacement in options.separator_normalizations:
        text = text.replace(source, replacement)
    if not text:
        return ""
    compact = "".join(part for part in text.split())
    tokens = findall(r"[A-Za-z]+|\d+", compact)
    normalized_tokens: list[str] = []
    for token in tokens:
        if token.isdigit():
            normalized_tokens.append(str(int(token)) if options.leading_zeros else token)
        elif token:
            normalized_tokens.append(token)
    return "".join(normalized_tokens)


@dataclass(frozen=True)
class MatchRunResult:
    """Result from one deterministic match job."""

    job_id: str
    result_count: int
    matched_count: int
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY


@dataclass(frozen=True)
class DeterministicMatchOutput:
    """Pure matcher output that can be persisted by a separate application boundary."""

    results: tuple[dict[str, Any], ...]
    exceptions: tuple[dict[str, Any], ...]
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY


@dataclass(frozen=True)
class _MatchCandidate:
    left_index: int
    right_index: int
    left_id: str
    right_id: str
    left_sort_key: str
    right_sort_key: str
    left_reference_original: str
    right_reference_original: str
    left_reference_normalized: str
    right_reference_normalized: str
    confidence: Decimal
    explanation: str
    amount_difference: Decimal
    date_difference_days: int | None


@dataclass
class _FlowEdge:
    """Residual edge used by deterministic min-cost matching."""

    to: int
    reverse: int
    capacity: int
    cost: int


def _add_flow_edge(
    graph: list[list[_FlowEdge]],
    from_node: int,
    to_node: int,
    capacity: int,
    cost: int,
) -> _FlowEdge:
    forward = _FlowEdge(to=to_node, reverse=len(graph[to_node]), capacity=capacity, cost=cost)
    reverse = _FlowEdge(to=from_node, reverse=len(graph[from_node]), capacity=0, cost=-cost)
    graph[from_node].append(forward)
    graph[to_node].append(reverse)
    return forward


class MatchingService:
    """Indexed candidate-generation matching engine."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._match_result_columns: set[str] | None = None

    @staticmethod
    def _json_text(value: object) -> str:
        """Serialize deterministic JSON for explainability metadata."""

        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise PlatformError("Matching lineage is invalid.")
        try:
            return encode_sqlite_matching_lineage(value).text
        except PersistedJsonError as exc:
            raise PlatformError("Matching lineage is invalid.") from exc

    @staticmethod
    def _matching_rule_document(
        value: object,
        *,
        producer: bool = False,
    ) -> PersistedJsonObjectDocument:
        try:
            if producer:
                if not isinstance(value, Mapping):
                    raise PersistedJsonError("persisted_json_object_required")
                return encode_sqlite_matching_rule(value)
            return decode_sqlite_matching_rule(value)
        except PersistedJsonError as exc:
            message = "Matching rule is invalid." if producer else "Stored matching rule is invalid."
            raise PlatformError(message) from exc

    @staticmethod
    def _records_with_source_locations(
        records: list[dict[str, Any]],
        *,
        source_name: str,
    ) -> list[dict[str, Any]]:
        """Attach trusted file positions after removing user-supplied internal lineage keys."""

        suffix = Path(source_name).suffix.casefold()
        basis = "tabular-header-offset-v1" if suffix == ".csv" else _JSON_RECORD_BASIS
        located: list[dict[str, Any]] = []
        for position, record in enumerate(records, start=1):
            clean = {str(key): value for key, value in record.items() if str(key) not in INTERNAL_LINEAGE_COLUMNS}
            clean[SOURCE_POSITION_COLUMN] = position
            clean[SOURCE_ROW_COLUMN] = position + 1 if suffix == ".csv" else None
            clean[SOURCE_ROW_BASIS_COLUMN] = basis
            located.append(clean)
        return located

    def _match_results_columns(self) -> set[str]:
        """Return cached table columns for the local match_results table."""

        if self._match_result_columns is None:
            rows = self.connection.execute("PRAGMA table_info(match_results)").fetchall()
            self._match_result_columns = {str(row["name"]) for row in rows}
        return self._match_result_columns

    def _ensure_match_result_columns(self) -> None:
        """Ensure optional explainability columns exist on legacy match_result tables."""

        columns = self._match_results_columns()
        migration_sql: list[str] = []
        if "lineage_json" not in columns:
            migration_sql.append("ALTER TABLE match_results ADD COLUMN lineage_json TEXT NOT NULL DEFAULT '{}'")
        if "reason_code" not in columns:
            migration_sql.append("ALTER TABLE match_results ADD COLUMN reason_code TEXT NOT NULL DEFAULT ''")
        for migration in migration_sql:
            self.connection.execute(migration)
        if migration_sql:
            self._match_result_columns = None
            self._match_result_columns = self._match_results_columns()

    def run(
        self,
        *,
        left_path: Path | str,
        right_path: Path | str,
        workspace: str = "default",
        name: str = "local-match-job",
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        actor_label: str = "local-cli",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
    ) -> MatchRunResult:
        """Run deterministic local matching without a full cross product where possible."""

        financial_input_policy = _matching_input_policy(financial_input_policy)
        record_identity_policy = _matching_record_identity_policy(record_identity_policy)
        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        left_document = read_local_record_document(left_path)
        right_document = read_local_record_document(right_path)
        return self._run_records(
            left_records=left_document.records,
            right_records=right_document.records,
            workspace=workspace,
            name=name,
            left_source=left_document.source_path.name,
            right_source=right_document.source_path.name,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
            reference_normalization_rules=reference_normalization_rules,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult:
        """Run a synthetic local benchmark job and persist summary results."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        if rows < 1 or rows > 250000:
            raise PlatformError("Benchmark rows must be between 1 and 250000.")
        left_records = [
            {"id": f"L-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        right_records = [
            {"id": f"R-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        return self._run_records(
            left_records=left_records,
            right_records=right_records,
            workspace=workspace,
            name=f"synthetic-benchmark-{rows}",
            left_source="synthetic-left",
            right_source="synthetic-right",
            left_id_field="id",
            right_id_field="id",
            amount_field="amount",
            date_field="date",
            reference_field="reference",
            exact_fields="",
            amount_tolerance=Decimal("0"),
            date_window_days=0,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
            idempotency_key=None,
            actor_label=actor_label,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Return one match job status."""

        row = self.connection.execute("SELECT * FROM match_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise PlatformError("Match job not found.")
        payload = dict(row)
        self._matching_rule_document(payload.get("rule_json", ""))
        counts = self.connection.execute(
            """
            SELECT
                COUNT(CASE WHEN left_id <> '' THEN 1 END) AS result_count,
                SUM(CASE WHEN status = 'Matched' THEN 1 ELSE 0 END) AS matched_count
            FROM match_results
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        payload["result_count"] = int(counts["result_count"] or 0)
        payload["matched_count"] = int(counts["matched_count"] or 0)
        return payload

    def results(self, job_id: str, *, status: str = "") -> list[dict[str, Any]]:
        """List match results for one job."""

        if status:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? AND status = ? ORDER BY confidence DESC, left_id, right_id, match_type",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? ORDER BY confidence DESC, left_id, right_id, match_type",
                (job_id,),
            ).fetchall()
        return rows_to_dicts(rows)

    def list_jobs(self) -> list[dict[str, Any]]:
        """List match jobs."""

        jobs = rows_to_dicts(self.connection.execute("SELECT * FROM match_jobs ORDER BY created_at DESC").fetchall())
        for job in jobs:
            self._matching_rule_document(job.get("rule_json", ""))
        return jobs

    def match_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | ReferenceNormalizationRules | None = None,
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
        _source_locations_trusted: bool = False,
    ) -> DeterministicMatchOutput:
        """Match canonical records without opening or mutating a persistence transaction."""

        financial_input_policy = _matching_input_policy(financial_input_policy)
        record_identity_policy = _matching_record_identity_policy(record_identity_policy)
        exact_field_list = [field.strip() for field in exact_fields.split(",") if field.strip()]
        tolerance = _non_negative_amount(
            amount_tolerance,
            field="match amount tolerance",
            input_policy=financial_input_policy,
        )
        normalization_rules = (
            reference_normalization_rules
            if isinstance(reference_normalization_rules, ReferenceNormalizationRules)
            else _parse_reference_normalization_rules(reference_normalization_rules)
        )
        currency_cache: dict[str, tuple[int | None, str | None]] = {}
        (
            ordered_right,
            right_currency_map,
            right_precision_map,
            right_currency_issues,
            right_record_lineage,
        ) = self._ordered_records(
            right_records,
            id_field=right_id_field,
            prefix="R",
            amount_field=amount_field,
            currency_lookup_cache=currency_cache,
            financial_input_policy=financial_input_policy,
            source_locations_trusted=_source_locations_trusted,
            record_identity_policy=record_identity_policy,
        )
        right_index = self._build_right_index(
            ordered_right,
            right_currency_map=right_currency_map,
            right_precision_map=right_precision_map,
            reference_field=reference_field,
            exact_fields=exact_field_list,
            reference_normalization_rules=normalization_rules,
        )
        (
            ordered_left,
            left_currency_map,
            left_precision_map,
            left_currency_issues,
            left_record_lineage,
        ) = self._ordered_records(
            left_records,
            id_field=left_id_field,
            prefix="L",
            amount_field=amount_field,
            currency_lookup_cache=currency_cache,
            financial_input_policy=financial_input_policy,
            source_locations_trusted=_source_locations_trusted,
            record_identity_policy=record_identity_policy,
        )
        candidates = self._build_candidates(
            ordered_left,
            left_precision_map,
            left_currency_map,
            left_currency_issues,
            right_currency_map,
            right_index,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_field_list,
            amount_tolerance=tolerance,
            date_window_days=date_window_days,
            reference_normalization_rules=normalization_rules,
        )
        candidate_counts: dict[str, int] = {}
        for candidate in candidates:
            candidate_counts[candidate.left_id] = candidate_counts.get(candidate.left_id, 0) + 1
        candidates_by_left_index: dict[int, list[_MatchCandidate]] = {}
        for candidate in candidates:
            candidates_by_left_index.setdefault(candidate.left_index, []).append(candidate)
        selected_matches = self._minimum_cost_assignment(
            candidates,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
        )

        results: list[dict[str, Any]] = []
        exceptions: list[dict[str, Any]] = []

        def add_data_quality_exception(
            *,
            side: str,
            source_id: str,
            code: str,
            title: str,
            explanation: str,
            severity: str,
            risk_score: str,
            evidence: dict[str, object],
        ) -> None:
            exception_payload = {
                "exception_type": "data_quality",
                "source_side": side,
                "source_id": source_id,
                "title": title,
                "explanation": explanation,
                "severity": severity,
                "risk_score": risk_score,
                "reason_code": code,
                "evidence": evidence,
            }
            exception_payload["exception_id"] = _exception_id(
                exception_type="data_quality",
                source_side=side,
                source_id=source_id,
                code=code,
                title=title,
                explanation=explanation,
                severity=severity,
                risk_score=risk_score,
                evidence=evidence,
            )
            exceptions.append(exception_payload)

        def check_record_quality(
            *,
            side: str,
            source_id: str,
            record: dict[str, Any],
            amount_value: Decimal | None,
            currency_issue: str | None = None,
            record_lineage: dict[str, object],
        ) -> str:
            identity_evidence = {key: value for key, value in record_lineage.items() if key != "source_location"}

            def with_lineage(evidence: dict[str, object]) -> dict[str, object]:
                return {
                    **evidence,
                    "record_identity": identity_evidence,
                    "source_location": record_lineage["source_location"],
                }

            if currency_issue:
                title = (
                    "Unknown currency reference"
                    if currency_issue == "UNKNOWN_CURRENCY"
                    else "Inactive currency reference"
                )
                add_data_quality_exception(
                    side=side,
                    source_id=source_id,
                    code=currency_issue,
                    title=title,
                    explanation="Reconciliation was blocked because the currency reference was not known or inactive.",
                    severity="High",
                    risk_score="0.8",
                    evidence=with_lineage(
                        {
                            "source_id": source_id,
                            "currency": normalize_text(record.get("currency", record.get("currency_code", ""))),
                        }
                    ),
                )
                return currency_issue
            if not bool(record.get("valid", True)):
                add_data_quality_exception(
                    side=side,
                    source_id=source_id,
                    code="INVALID_RECORD",
                    title="Invalid source record",
                    explanation="The canonical input was marked invalid during ingestion.",
                    severity="High",
                    risk_score="0.75",
                    evidence=with_lineage({"source_id": source_id}),
                )
                return "INVALID_RECORD"
            if amount_value is None:
                original = record.get("amount_original", record.get(amount_field, ""))
                add_data_quality_exception(
                    side=side,
                    source_id=source_id,
                    code="INVALID_AMOUNT",
                    title="Invalid monetary amount",
                    explanation="The source amount could not be parsed as an exact decimal.",
                    severity="Critical",
                    risk_score="0.9",
                    evidence=with_lineage({"source_id": source_id, "amount_original": original}),
                )
                return "INVALID_AMOUNT"
            date_value = record.get(date_field)
            if date_value is None or not str(date_value).strip():
                add_data_quality_exception(
                    side=side,
                    source_id=source_id,
                    code="MISSING_DATE",
                    title="Missing reconciliation date",
                    explanation="The date was unavailable; no date score was applied.",
                    severity="Medium",
                    risk_score="0.3",
                    evidence=with_lineage({"source_id": source_id, "date_original": date_value}),
                )
                return "MISSING_DATE"
            if parse_date(date_value) is None:
                add_data_quality_exception(
                    side=side,
                    source_id=source_id,
                    code="INVALID_DATE",
                    title="Invalid reconciliation date",
                    explanation="The date could not be parsed; invalid date values are not eligible for matching.",
                    severity="High",
                    risk_score="0.6",
                    evidence=with_lineage({"source_id": source_id, "date_original": date_value}),
                )
                return "INVALID_DATE"
            return ""

        def build_lineage_payload(*, left_index: int, selected_match: _MatchCandidate | None) -> dict[str, Any]:
            all_candidates = candidates_by_left_index.get(left_index, [])
            payload: dict[str, Any] = {
                "candidate_count": len(all_candidates),
                "left_record": left_record_lineage[left_index],
            }
            if selected_match is None:
                payload["rejection_reasons"] = ["No indexed candidate met the configured rules."]
                return payload
            alternatives: list[dict[str, str | int | None]] = []
            selected_rank = 1
            for rank, candidate in enumerate(all_candidates, start=1):
                if candidate is selected_match:
                    selected_rank = rank
                    continue
                alternatives.append(
                    {
                        "right_id": candidate.right_id,
                        "score": _decimal_text(candidate.confidence),
                        "amount_difference": _decimal_text(candidate.amount_difference),
                        "date_difference_days": candidate.date_difference_days,
                        "left_reference_original": candidate.left_reference_original,
                        "left_reference_normalized": candidate.left_reference_normalized,
                        "right_reference_original": candidate.right_reference_original,
                        "right_reference_normalized": candidate.right_reference_normalized,
                        "explanation": candidate.explanation,
                    },
                )
                if len(alternatives) >= 3:
                    break
            payload["selected_score"] = _decimal_text(selected_match.confidence)
            payload["selected_rank"] = selected_rank
            payload["selected_match"] = {
                "left_reference_original": selected_match.left_reference_original,
                "left_reference_normalized": selected_match.left_reference_normalized,
                "right_reference_original": selected_match.right_reference_original,
                "right_reference_normalized": selected_match.right_reference_normalized,
            }
            payload["right_record"] = right_record_lineage[selected_match.right_index]
            payload["alternatives"] = alternatives
            return payload

        left_quality_codes: dict[int, str] = {}
        for left_index, left_id, left_record, _, _, left_amount in ordered_left:
            left_quality_codes[left_index] = check_record_quality(
                side="Left",
                source_id=left_id,
                record=left_record,
                amount_value=left_amount,
                currency_issue=left_currency_issues.get(left_index),
                record_lineage=left_record_lineage[left_index],
            )

        right_quality_codes: dict[int, str] = {}
        for right_index_value, right_id, right_record, _, _, right_amount in ordered_right:
            right_quality_codes[right_index_value] = check_record_quality(
                side="Right",
                source_id=right_id,
                record=right_record,
                amount_value=right_amount,
                currency_issue=right_currency_issues.get(right_index_value),
                record_lineage=right_record_lineage[right_index_value],
            )

        selected_by_left: dict[int, list[_MatchCandidate]] = {}
        matched_right_indices: set[int] = set()
        for match in selected_matches:
            if left_quality_codes.get(match.left_index):
                continue
            if right_quality_codes.get(match.right_index):
                continue
            selected_by_left.setdefault(match.left_index, []).append(match)
            matched_right_indices.add(match.right_index)

        for left_index, left_id, left_record, _, _, left_amount in ordered_left:
            quality_code = left_quality_codes.get(left_index) or check_record_quality(
                side="Left",
                source_id=left_id,
                record=left_record,
                amount_value=left_amount,
                currency_issue=left_currency_issues.get(left_index),
                record_lineage=left_record_lineage[left_index],
            )
            matches = selected_by_left.get(left_index, [])
            if quality_code:
                results.append(
                    {
                        "left_id": left_id,
                        "match_type": "invalid",
                        "confidence": "0",
                        "explanation": "Source record failed canonical data-quality validation.",
                        "amount_difference": "0",
                        "status": "Invalid",
                        "reason_code": quality_code,
                        "lineage": build_lineage_payload(left_index=left_index, selected_match=None),
                    }
                )
                continue
            if not matches:
                results.append(
                    {
                        "left_id": left_id,
                        "match_type": "unmatched",
                        "confidence": "0",
                        "explanation": "No indexed candidate met the configured rules.",
                        "amount_difference": "0",
                        "status": "Unmatched",
                        "reason_code": "MISSING_RIGHT",
                        "lineage": build_lineage_payload(left_index=left_index, selected_match=None),
                    }
                )
                continue
            for match in matches:
                results.append(
                    {
                        "left_id": match.left_id,
                        "right_id": match.right_id,
                        "match_type": "deterministic",
                        "confidence": _decimal_text(match.confidence),
                        "explanation": match.explanation,
                        "amount_difference": format(match.amount_difference, "f"),
                        "date_difference_days": match.date_difference_days,
                        "status": "Matched",
                        "lineage": build_lineage_payload(left_index=left_index, selected_match=match),
                    }
                )

        for right_index_value, right_id, right_record, _, _, right_amount in ordered_right:
            if right_index_value in matched_right_indices:
                continue
            quality_code = right_quality_codes.get(right_index_value) or check_record_quality(
                side="Right",
                source_id=right_id,
                record=right_record,
                amount_value=right_amount,
                currency_issue=right_currency_issues.get(right_index_value),
                record_lineage=right_record_lineage[right_index_value],
            )
            if quality_code:
                results.append(
                    {
                        "right_id": right_id,
                        "match_type": "invalid_right",
                        "confidence": "0",
                        "explanation": "Target record failed canonical data-quality validation.",
                        "amount_difference": "0",
                        "status": "Invalid",
                        "reason_code": quality_code,
                        "lineage": {
                            "candidate_count": 0,
                            "right_record": right_record_lineage[right_index_value],
                        },
                    }
                )
            else:
                results.append(
                    {
                        "right_id": right_id,
                        "match_type": "unmatched_right",
                        "confidence": "0",
                        "explanation": "No left-side candidate met the configured rules.",
                        "amount_difference": "0",
                        "status": "Unmatched",
                        "reason_code": "MISSING_LEFT",
                        "lineage": {
                            "candidate_count": 0,
                            "rejection_reasons": ["No left-side candidate matched this right-side record."],
                            "right_record": right_record_lineage[right_index_value],
                        },
                    }
                )
        return DeterministicMatchOutput(
            results=tuple(results),
            exceptions=tuple(exceptions),
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def _run_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        workspace: str,
        name: str,
        left_source: str,
        right_source: str,
        left_id_field: str,
        right_id_field: str,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: str,
        amount_tolerance: object,
        date_window_days: int,
        allow_many_to_one: bool,
        allow_one_to_many: bool,
        allow_many_to_many: bool,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None,
        actor_label: str,
        financial_input_policy: FinancialInputPolicy,
        record_identity_policy: str,
    ) -> MatchRunResult:
        financial_input_policy = _matching_input_policy(financial_input_policy)
        record_identity_policy = _matching_record_identity_policy(record_identity_policy)
        workspace_id = ensure_workspace(self.connection, workspace)
        created_at = utc_now_text()
        self._ensure_match_result_columns()
        job_id = (
            platform_id("MJ", workspace_id, name, left_source, right_source, "idempotency", idempotency_key)
            if idempotency_key
            else platform_id("MJ", workspace_id, name, left_source, right_source, created_at)
        )
        if idempotency_key:
            existing = self.connection.execute(
                "SELECT id, rule_json FROM match_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None:
                try:
                    existing_rule = self._matching_rule_document(existing["rule_json"]).payload
                except PlatformError as exc:
                    raise PlatformError("Existing idempotent match rule is invalid.") from exc
                existing_policy = _matching_input_policy(
                    existing_rule.get(
                        "financial_input_policy",
                        LEGACY_FINANCIAL_INPUT_POLICY,
                    )
                )
                if existing_policy != financial_input_policy:
                    raise PlatformError("Idempotency key is bound to a different financial input policy.")
                existing_identity_policy = str(
                    existing_rule.get(
                        "record_identity_policy",
                        LEGACY_RECORD_IDENTITY_POLICY,
                    )
                )
                if existing_identity_policy != record_identity_policy:
                    raise PlatformError("Idempotency key is bound to a different record identity policy.")
                counts = self.connection.execute(
                    """
                    SELECT
                        COUNT(CASE WHEN left_id <> '' THEN 1 END) AS result_count,
                        COUNT(CASE WHEN status = 'Matched' THEN 1 END) AS matched_count
                    FROM match_results
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                return MatchRunResult(
                    job_id=job_id,
                    result_count=int(counts["result_count"] or 0),
                    matched_count=int(counts["matched_count"] or 0),
                    financial_input_policy=existing_policy,
                    record_identity_policy=existing_identity_policy,
                )
        exact_field_list = [field.strip() for field in exact_fields.split(",") if field.strip()]
        tolerance = _non_negative_amount(
            amount_tolerance,
            field="match amount tolerance",
            input_policy=financial_input_policy,
        )
        rule: dict[str, object] = {
            "amount_field": amount_field,
            "date_field": date_field,
            "reference_field": reference_field,
            "exact_fields": exact_field_list,
            "amount_tolerance": _decimal_text(tolerance),
            "date_window_days": date_window_days,
            "allow_many_to_one": allow_many_to_one,
            "allow_one_to_many": allow_one_to_many,
            "allow_many_to_many": allow_many_to_many,
            "financial_input_policy": financial_input_policy,
            "record_identity_policy": record_identity_policy,
        }
        try:
            normalization_rules = _parse_reference_normalization_rules(reference_normalization_rules)
            rule["reference_normalization_rules"] = asdict(normalization_rules)
            rule_json = self._matching_rule_document(rule, producer=True).text
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO match_jobs (
                    id, workspace_id, name, left_source, right_source, status,
                    rule_json, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'Running', ?, ?, ?)
                """,
                (
                    job_id,
                    workspace_id,
                    name,
                    left_source,
                    right_source,
                    rule_json,
                    actor_label,
                    created_at,
                ),
            )
            self.connection.execute(
                "INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (platform_id("MR", job_id, "primary"), job_id, "primary", rule_json, created_at),
            )
            located_left_records = self._records_with_source_locations(
                left_records,
                source_name=left_source,
            )
            located_right_records = self._records_with_source_locations(
                right_records,
                source_name=right_source,
            )
            output = self.match_records(
                left_records=located_left_records,
                right_records=located_right_records,
                left_id_field=left_id_field,
                right_id_field=right_id_field,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=",".join(exact_field_list),
                amount_tolerance=tolerance,
                date_window_days=date_window_days,
                allow_many_to_one=allow_many_to_one,
                allow_one_to_many=allow_one_to_many,
                allow_many_to_many=allow_many_to_many,
                reference_normalization_rules=normalization_rules,
                financial_input_policy=financial_input_policy,
                record_identity_policy=record_identity_policy,
                _source_locations_trusted=True,
            )
            result_count = 0
            matched_count = 0
            exception_count = len(output.exceptions)
            for result in output.results:
                left_id = str(result.get("left_id", ""))
                right_id = str(result.get("right_id", ""))
                date_difference_days = result.get("date_difference_days")
                if date_difference_days is not None and not isinstance(date_difference_days, int):
                    raise PlatformError("Invalid date_difference_days value produced by matching engine.")
                self._insert_result(
                    job_id=job_id,
                    left_id=left_id,
                    right_id=right_id,
                    match_type=str(result.get("match_type")),
                    confidence=_coerce_confidence(result.get("confidence", 0)),
                    explanation=str(result.get("explanation", "")),
                    amount_difference=(
                        _parse_amount(
                            result.get("amount_difference", "0"),
                            input_policy=financial_input_policy,
                        )
                        or Decimal("0")
                    ),
                    date_difference_days=date_difference_days,
                    status=str(result.get("status", "Unmatched")),
                    reason_code=str(result.get("reason_code", "")),
                    lineage=result.get("lineage", {}),
                )
                if left_id:
                    result_count += 1
                if result.get("status") == "Matched":
                    matched_count += 1
            self.connection.execute(
                "UPDATE match_jobs SET status = 'Complete', completed_at = ? WHERE id = ?",
                (utc_now_text(), job_id),
            )
            audit(
                self.connection,
                actor_label=actor_label,
                object_type="match_job",
                object_id=job_id,
                action="match_job_completed",
                metadata={
                    "result_count": result_count,
                    "matched_count": matched_count,
                    "exception_count": exception_count,
                    "financial_input_policy": financial_input_policy,
                    "record_identity_policy": record_identity_policy,
                },
            )
            append_outbox_event(
                self.connection,
                event_id=platform_id("OB", job_id, "match_job_completed"),
                event_type="match_job.completed",
                aggregate_type="match_job",
                aggregate_id=job_id,
                payload={
                    "job_id": job_id,
                    "result_count": result_count,
                    "matched_count": matched_count,
                    "exception_count": exception_count,
                    "financial_input_policy": financial_input_policy,
                    "record_identity_policy": record_identity_policy,
                },
            )
            self.connection.commit()
        except (sqlite3.DatabaseError, AuditLedgerError, PlatformError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to complete the match job; all results were rolled back.") from exc
        return MatchRunResult(
            job_id=job_id,
            result_count=result_count,
            matched_count=matched_count,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def _build_right_index(
        self,
        ordered_right_records: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]],
        *,
        right_currency_map: dict[int, str],
        right_precision_map: dict[int, int | None],
        reference_field: str,
        exact_fields: list[str],
        reference_normalization_rules: ReferenceNormalizationRules,
    ) -> dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal, str, int | None]]]]:
        indexes: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal, str, int | None]]]] = {
            "reference": {},
            "amount": {},
            "exact": {},
        }
        for index, record_id, record, _stable_key, _, amount_value in ordered_right_records:
            if amount_value is None:
                continue
            reference = _normalize_reference(
                record.get(reference_field),
                rules=reference_normalization_rules,
            )
            right_currency = right_currency_map.get(index, "")
            right_precision = right_precision_map.get(index)
            if reference:
                indexes["reference"].setdefault(reference, []).append(
                    (index, record_id, record, amount_value, right_currency, right_precision),
                )
            amount_bucket = _amount_bucket_key(amount_value, right_precision)
            indexes["amount"].setdefault(str(amount_bucket), []).append(
                (index, record_id, record, amount_value, right_currency, right_precision),
            )
            if exact_fields:
                key = self._exact_key(record, exact_fields)
                indexes["exact"].setdefault(key, []).append(
                    (index, record_id, record, amount_value, right_currency, right_precision),
                )
        return indexes

    def _candidates(
        self,
        left: dict[str, Any],
        right_index: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal, str, int | None]]]],
        *,
        left_amount: Decimal,
        left_currency: str,
        left_precision: int | None,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: Decimal,
        reference_normalization_rules: ReferenceNormalizationRules,
    ) -> list[tuple[int, str, dict[str, Any], Decimal, str, int | None]]:
        reference = _normalize_reference(
            left.get(reference_field),
            rules=reference_normalization_rules,
        )
        candidates_by_key: dict[tuple[int, str], tuple[int, str, dict[str, Any], Decimal, str, int | None]] = {}
        if reference and reference in right_index["reference"]:
            for candidate in right_index["reference"][reference]:
                if left_currency and candidate[4] and candidate[4] != left_currency:
                    continue
                candidates_by_key[(candidate[0], candidate[1])] = candidate
        if exact_fields:
            key = self._exact_key(left, exact_fields)
            if key in right_index["exact"]:
                for candidate in right_index["exact"][key]:
                    if left_currency and candidate[4] and candidate[4] != left_currency:
                        continue
                    candidates_by_key[(candidate[0], candidate[1])] = candidate
        if amount_tolerance == 0:
            bucket = _amount_bucket_key(left_amount, left_precision)
            amount_candidates = right_index["amount"].get(bucket, [])
        else:
            amount_candidates = []
            for bucket, candidates in right_index["amount"].items():
                bucket_decimal = Decimal(bucket)
                if abs(left_amount - bucket_decimal) <= amount_tolerance:
                    amount_candidates.extend(candidates)
        for candidate in amount_candidates:
            if left_currency and candidate[4] and candidate[4] != left_currency:
                continue
            candidates_by_key[(candidate[0], candidate[1])] = candidate
        return sorted(
            candidates_by_key.values(),
            key=lambda item: (self._record_key(item[2], fallback=item[1]), item[1], item[0]),
        )

    def _ordered_records(
        self,
        records: list[dict[str, Any]],
        *,
        id_field: str,
        prefix: str,
        amount_field: str,
        currency_lookup_cache: dict[str, tuple[int | None, str | None]],
        financial_input_policy: FinancialInputPolicy,
        source_locations_trusted: bool,
        record_identity_policy: str,
    ) -> tuple[
        list[tuple[int, str, dict[str, Any], str, int, Decimal | None]],
        dict[int, str],
        dict[int, int | None],
        dict[int, str | None],
        dict[int, dict[str, object]],
    ]:
        prepared: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]] = []
        currency_code_by_index: dict[int, str] = {}
        precision_by_index: dict[int, int | None] = {}
        currency_issue_by_index: dict[int, str | None] = {}
        for index, record in enumerate(records):
            currency_code = _extract_currency_code(record)
            try:
                resolved_currency, precision = _resolve_currency_precision(
                    self.connection,
                    currency_lookup_cache,
                    currency_code,
                )
                currency_issue: str | None = None
            except InvalidAmountError as exc:
                resolved_currency = currency_code
                precision = None
                currency_issue = str(exc)
            parsed_amount = _parse_amount(
                record.get(amount_field),
                precision=precision,
                input_policy=financial_input_policy,
            )
            stable_key = self._record_key(record)
            explicit_id = normalize_key(record.get(id_field), default="")
            base_id = explicit_id or f"{prefix}-{stable_key}"
            prepared.append((index, base_id, record, stable_key, 0, parsed_amount))
            currency_code_by_index[index] = resolved_currency
            precision_by_index[index] = precision
            currency_issue_by_index[index] = currency_issue
        prepared.sort(key=lambda item: (item[1], item[3], item[0]))
        counts: dict[str, int] = {}
        ordered: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]] = []
        for index, base_id, record, stable_key, _, parsed_amount in prepared:
            counts[base_id] = counts.get(base_id, 0) + 1
            occurrence = counts[base_id]
            record_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            ordered.append((index, record_id, record, stable_key, occurrence, parsed_amount))
        ordered.sort(key=lambda item: (item[3], item[4], item[0]))
        duplicate_totals = Counter(item[3] for item in ordered)
        duplicate_occurrences: Counter[str] = Counter()
        record_lineage: dict[int, dict[str, object]] = {}
        for index, _record_id, record, stable_key, _occurrence, _parsed_amount in sorted(
            ordered,
            key=lambda item: (item[3], item[0]),
        ):
            duplicate_occurrences[stable_key] += 1
            duplicate_ordinal = duplicate_occurrences[stable_key]
            duplicate_count = duplicate_totals[stable_key]
            base_instance_id = f"{prefix.casefold()}:{stable_key}"
            record_instance_id = (
                base_instance_id if duplicate_count == 1 else f"{base_instance_id}#occurrence:{duplicate_ordinal}"
            )
            source_position: int | None = None
            source_row: int | None = None
            source_row_basis = _SOURCE_LOCATION_UNAVAILABLE_BASIS
            if source_locations_trusted:
                raw_position = record.get(SOURCE_POSITION_COLUMN)
                raw_row = record.get(SOURCE_ROW_COLUMN)
                if isinstance(raw_position, int) and not isinstance(raw_position, bool) and raw_position > 0:
                    source_position = raw_position
                if isinstance(raw_row, int) and not isinstance(raw_row, bool) and raw_row > 0:
                    source_row = raw_row
                source_row_basis = str(record.get(SOURCE_ROW_BASIS_COLUMN) or _RECORD_SEQUENCE_BASIS)
            record_lineage[index] = {
                "record_instance_id": record_instance_id,
                "record_fingerprint": stable_key,
                "duplicate_ordinal": duplicate_ordinal,
                "duplicate_count": duplicate_count,
                "record_identity_policy": record_identity_policy,
                "source_location": {
                    "position": source_position,
                    "row": source_row,
                    "basis": source_row_basis,
                },
            }
        return (
            ordered,
            currency_code_by_index,
            precision_by_index,
            currency_issue_by_index,
            record_lineage,
        )

    def _build_candidates(
        self,
        ordered_left: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]],
        left_precision_map: dict[int, int | None],
        left_currency_map: dict[int, str],
        left_currency_issues: dict[int, str | None],
        right_currency_map: dict[int, str],
        right_index_data: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal, str, int | None]]]],
        *,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: Decimal,
        date_window_days: int,
        reference_normalization_rules: ReferenceNormalizationRules,
    ) -> list[_MatchCandidate]:
        candidates: list[_MatchCandidate] = []
        for left_index, left_id, left, left_key, _, left_amount in ordered_left:
            if left_amount is None:
                continue
            if left_currency_issues.get(left_index):
                continue
            left_reference_original = normalize_text(left.get(reference_field))
            left_reference_normalized = _normalize_reference(
                left_reference_original,
                rules=reference_normalization_rules,
            )
            left_precision = left_precision_map.get(left_index)
            left_currency = left_currency_map.get(left_index, "")
            for (
                candidate_right_index,
                right_id,
                right,
                right_amount,
                right_currency,
                right_precision,
            ) in self._candidates(
                left,
                right_index_data,
                left_amount=left_amount,
                left_currency=left_currency,
                left_precision=left_precision,
                reference_field=reference_field,
                exact_fields=exact_fields,
                amount_tolerance=amount_tolerance,
                reference_normalization_rules=reference_normalization_rules,
            ):
                if right_currency and left_currency and right_currency != left_currency:
                    continue
                _ = right_precision
                right_reference_original = normalize_text(right.get(reference_field))
                right_reference_normalized = _normalize_reference(
                    right_reference_original,
                    rules=reference_normalization_rules,
                )
                confidence, parts, amount_difference, day_difference = self._score_candidate(
                    left,
                    right,
                    left_amount=left_amount,
                    right_amount=right_amount,
                    amount_field=amount_field,
                    date_field=date_field,
                    reference_field=reference_field,
                    exact_fields=exact_fields,
                    amount_tolerance=amount_tolerance,
                    date_window_days=date_window_days,
                    reference_normalization_rules=reference_normalization_rules,
                )
                if confidence < Decimal("0.65"):
                    continue
                right_key = self._record_key(right, fallback=right_id)
                candidates.append(
                    _MatchCandidate(
                        left_index=left_index,
                        right_index=candidate_right_index,
                        left_id=left_id,
                        right_id=right_id,
                        left_sort_key=left_key,
                        right_sort_key=right_key,
                        left_reference_original=left_reference_original,
                        right_reference_original=right_reference_original,
                        left_reference_normalized=left_reference_normalized,
                        right_reference_normalized=right_reference_normalized,
                        confidence=confidence,
                        explanation="; ".join(parts),
                        amount_difference=amount_difference,
                        date_difference_days=day_difference,
                    ),
                )
        candidates.sort(
            key=lambda candidate: (
                candidate.left_sort_key,
                self._candidate_cost(candidate),
                candidate.right_sort_key,
                candidate.left_id,
                candidate.right_id,
            ),
        )
        return candidates

    def _record_key(self, record: dict[str, Any], *, fallback: str = "") -> str:
        payload = {
            str(key): _record_identity_value(value)
            for key, value in sorted(record.items(), key=lambda item: str(item[0]))
            if str(key) not in INTERNAL_LINEAGE_COLUMNS
        }
        payload["__fallback__"] = str(fallback)
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        ).hexdigest()

    def _minimum_cost_assignment(
        self,
        candidates: list[_MatchCandidate],
        *,
        allow_many_to_one: bool,
        allow_one_to_many: bool,
        allow_many_to_many: bool,
    ) -> list[_MatchCandidate]:
        if not candidates:
            return []

        def candidate_order(item: _MatchCandidate) -> tuple[object, ...]:
            return (item.left_sort_key, self._candidate_cost(item), item.right_sort_key, item.left_id, item.right_id)

        left_candidates: dict[int, list[int]] = {}
        right_candidates: dict[int, list[int]] = {}
        for index, candidate in enumerate(candidates):
            left_candidates.setdefault(candidate.left_index, []).append(index)
            right_candidates.setdefault(candidate.right_index, []).append(index)
        unseen = set(range(len(candidates)))
        components: list[list[_MatchCandidate]] = []
        for root in sorted(unseen, key=lambda index: candidate_order(candidates[index])):
            if root not in unseen:
                continue
            stack = [root]
            unseen.remove(root)
            component_indices: list[int] = []
            while stack:
                current = stack.pop()
                component_indices.append(current)
                candidate = candidates[current]
                neighbors = left_candidates[candidate.left_index] + right_candidates[candidate.right_index]
                for neighbor in sorted(neighbors, key=lambda index: candidate_order(candidates[index])):
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        stack.append(neighbor)
            components.append(
                [
                    candidates[index]
                    for index in sorted(component_indices, key=lambda index: candidate_order(candidates[index]))
                ]
            )
        if len(components) > 1:
            selected: list[_MatchCandidate] = []
            for component in components:
                selected.extend(
                    self._minimum_cost_assignment(
                        component,
                        allow_many_to_one=allow_many_to_one,
                        allow_one_to_many=allow_one_to_many,
                        allow_many_to_many=allow_many_to_many,
                    )
                )
            return sorted(selected, key=candidate_order)
        left_sort_keys = {candidate.left_index: candidate.left_sort_key for candidate in candidates}
        right_sort_keys = {candidate.right_index: candidate.right_sort_key for candidate in candidates}
        left_indices = sorted(left_sort_keys, key=lambda index: (left_sort_keys[index], index))
        right_indices = sorted(right_sort_keys, key=lambda index: (right_sort_keys[index], index))
        left_cap = len(right_indices) if (allow_one_to_many or allow_many_to_many) else 1
        right_cap = len(left_indices) if (allow_many_to_one or allow_many_to_many) else 1

        stock_to_graph = {index: position + 1 for position, index in enumerate(left_indices)}
        right_offset = 1 + len(stock_to_graph)
        right_to_graph = {index: right_offset + position for position, index in enumerate(right_indices)}
        sink = right_offset + len(right_indices)

        graph: list[list[_FlowEdge]] = [[] for _ in range(sink + 1)]
        for index in left_indices:
            _add_flow_edge(graph, 0, stock_to_graph[index], left_cap, 0)
        for index in right_indices:
            _add_flow_edge(graph, right_to_graph[index], sink, right_cap, 0)

        tracked_edges: list[tuple[_FlowEdge, _MatchCandidate]] = []
        for candidate in sorted(
            candidates,
            key=candidate_order,
        ):
            edge = _add_flow_edge(
                graph,
                stock_to_graph[candidate.left_index],
                right_to_graph[candidate.right_index],
                1,
                self._candidate_cost(candidate),
            )
            tracked_edges.append((edge, candidate))

        node_count = len(graph)
        potentials = [0] * node_count
        infinity = 10**30
        while True:
            distances = [infinity] * node_count
            predecessors: list[tuple[int, int] | None] = [None] * node_count
            distances[0] = 0
            queue: list[tuple[int, int]] = [(0, 0)]
            while queue:
                distance, node = heapq.heappop(queue)
                if distance != distances[node]:
                    continue
                for edge_index, edge in enumerate(graph[node]):
                    if edge.capacity <= 0:
                        continue
                    reduced_cost = edge.cost + potentials[node] - potentials[edge.to]
                    candidate_distance = distance + reduced_cost
                    if candidate_distance < distances[edge.to]:
                        distances[edge.to] = candidate_distance
                        predecessors[edge.to] = (node, edge_index)
                        heapq.heappush(queue, (candidate_distance, edge.to))
            if predecessors[sink] is None:
                break
            for node, distance in enumerate(distances):
                if distance < infinity:
                    potentials[node] += distance
            node = sink
            while node != 0:
                predecessor = predecessors[node]
                if predecessor is None:
                    raise RuntimeError("internal assignment path is incomplete")
                previous, edge_index = predecessor
                edge = graph[previous][edge_index]
                edge.capacity -= 1
                graph[node][edge.reverse].capacity += 1
                node = previous

        return [candidate for edge, candidate in tracked_edges if edge.capacity == 0]

    def _candidate_cost(self, candidate: _MatchCandidate) -> int:
        score = int(
            (candidate.confidence * Decimal("1000000")).to_integral_value(
                rounding=ROUND_HALF_EVEN,
            ),
        )
        amount_penalty = min(
            int(
                (abs(candidate.amount_difference) * Decimal("10000")).to_integral_value(
                    rounding=ROUND_HALF_EVEN,
                ),
            ),
            2_000_000,
        )
        date_penalty = (
            min(abs(candidate.date_difference_days) * 10, 5_000) if candidate.date_difference_days is not None else 0
        )
        return (1_000_000 - score) + amount_penalty + date_penalty

    def _score_candidate(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        left_amount: Decimal,
        right_amount: Decimal,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: Decimal,
        date_window_days: int,
        reference_normalization_rules: ReferenceNormalizationRules,
    ) -> tuple[Decimal, list[str], Decimal, int | None]:
        score = Decimal("0")
        parts: list[str] = []
        left_data = left
        right_data = right
        left_reference = normalize_text(left_data.get(reference_field))
        right_reference = normalize_text(right_data.get(reference_field))
        left_reference_norm = _normalize_reference(left_reference, rules=reference_normalization_rules)
        right_reference_norm = _normalize_reference(right_reference, rules=reference_normalization_rules)
        if left_reference_norm and left_reference_norm == right_reference_norm:
            score += Decimal("0.45")
            if left_reference == right_reference:
                parts.append("reference matched exactly")
            else:
                parts.append(f"reference matched after normalization ({left_reference_norm})")
        amount_diff = abs(left_amount - right_amount)
        if amount_diff <= amount_tolerance:
            score += Decimal("0.30")
            parts.append(f"amount within tolerance ({_decimal_text(amount_diff)})")
        day_diff = date_diff_days(left_data.get(date_field), right_data.get(date_field))
        if day_diff is not None and day_diff <= date_window_days:
            score += Decimal("0.15")
            parts.append(f"date within window ({day_diff} days)")
        else:
            parts.append("date unavailable; no date score applied")
        if exact_fields and self._exact_key(left_data, exact_fields) == self._exact_key(right_data, exact_fields):
            score += Decimal("0.10")
            parts.append("exact key fields matched")
        return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), parts, amount_diff, day_diff

    def _insert_result(
        self,
        *,
        job_id: str,
        left_id: str,
        right_id: str,
        match_type: str,
        confidence: Decimal,
        explanation: str,
        amount_difference: Decimal,
        date_difference_days: int | None,
        status: str,
        reason_code: str = "",
        lineage: dict[str, object] | None = None,
    ) -> None:
        result_id = platform_id("MRSLT", job_id, left_id, right_id, match_type)
        columns = [
            "id",
            "job_id",
            "left_id",
            "right_id",
            "match_type",
            "confidence",
            "explanation",
            "amount_difference",
            "amount_difference_decimal",
            "date_difference_days",
            "status",
            "created_at",
        ]
        values = [
            result_id,
            job_id,
            left_id,
            right_id,
            match_type,
            _decimal_text(confidence),
            explanation,
            str(amount_difference),
            _decimal_text(amount_difference),
            date_difference_days if date_difference_days is not None else -1,
            status,
            utc_now_text(),
        ]
        if "reason_code" in self._match_results_columns():
            columns.append("reason_code")
            values.append(reason_code)
        if "lineage_json" in self._match_results_columns():
            columns.append("lineage_json")
            values.append(self._json_text(lineage or {}))
        column_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(values))
        insert_sql = f"""
            INSERT OR IGNORE INTO match_results (
                {column_sql}
            ) VALUES ({placeholders})
        """
        self.connection.execute(insert_sql, values)

    @staticmethod
    def _exact_key(record: dict[str, Any], fields: list[str]) -> str:
        return "|".join(normalize_text(record.get(field)).lower() for field in fields)
