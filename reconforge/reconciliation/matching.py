"""Stock-to-GL matching logic."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from difflib import SequenceMatcher
from numbers import Integral
from re import findall
from typing import Any, Literal, cast
from unicodedata import normalize as unicode_normalize

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.utils.dates import days_between
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    Money,
    parse_exact_amount,
    validate_financial_input_policy,
)

MatchLevel = Literal[
    "Level 1 Exact",
    "Level 2 Normalized Reference",
    "Level 2 Fuzzy Reference",
    "Level 3 Amount/Date Proximity",
    "Value Difference",
]
MatchingStrategy = Literal["standard", "strict", "aggressive", "audit-safe"]
MatchingAmbiguityPolicy = Literal["stable-tie-break-v1", "unresolved-equal-cost-v1"]
DEFAULT_MATCHING_AMBIGUITY_POLICY: MatchingAmbiguityPolicy = "stable-tie-break-v1"
CURRENT_MATCHING_AMBIGUITY_POLICY: MatchingAmbiguityPolicy = "unresolved-equal-cost-v1"
AMBIGUITY_MAX_CANDIDATES = 64
AMBIGUITY_MAX_ASSIGNMENT_CHECKS = 32
RECORD_IDENTITY_POLICY = "canonical-multiset-occurrence-v1"
SOURCE_ROW_BASIS = "tabular-header-offset-v1"
RECORD_INSTANCE_ID_COLUMN = "_reconforge_record_instance_id"
RECORD_FINGERPRINT_COLUMN = "_reconforge_record_fingerprint"
DUPLICATE_ORDINAL_COLUMN = "_reconforge_duplicate_ordinal"
DUPLICATE_COUNT_COLUMN = "_reconforge_duplicate_count"
SOURCE_POSITION_COLUMN = "_reconforge_source_position"
SOURCE_ROW_COLUMN = "_reconforge_source_row"
SOURCE_ROW_BASIS_COLUMN = "_reconforge_source_row_basis"
RECORD_IDENTITY_POLICY_COLUMN = "_reconforge_record_identity_policy"
INTERNAL_LINEAGE_COLUMNS = frozenset(
    {
        RECORD_INSTANCE_ID_COLUMN,
        RECORD_FINGERPRINT_COLUMN,
        DUPLICATE_ORDINAL_COLUMN,
        DUPLICATE_COUNT_COLUMN,
        SOURCE_POSITION_COLUMN,
        SOURCE_ROW_COLUMN,
        SOURCE_ROW_BASIS_COLUMN,
        RECORD_IDENTITY_POLICY_COLUMN,
    }
)


@dataclass(frozen=True)
class MatchCandidate:
    """A matched stock and GL pair."""

    stock_index: int
    gl_index: int
    match_level: MatchLevel
    confidence: Decimal
    reason: str
    match_id: str = ""
    stock_move_id: str = ""
    gl_entry_id: str = ""
    amount_difference: Decimal = Decimal("0")
    date_difference: int | None = None
    reference_similarity: Decimal = Decimal("0")
    review_required: bool = False
    stock_sort_key: str = ""
    gl_sort_key: str = ""
    stock_record_instance_id: str = ""
    gl_record_instance_id: str = ""
    stock_duplicate_ordinal: int = 1
    gl_duplicate_ordinal: int = 1
    stock_duplicate_count: int = 1
    gl_duplicate_count: int = 1
    stock_source_position: int = 0
    gl_source_position: int = 0
    stock_source_row: int = 0
    gl_source_row: int = 0


@dataclass(frozen=True)
class MatchAmbiguity:
    """One connected candidate component that cannot be selected safely."""

    ambiguity_group_id: str
    reason: Literal["equal_cost_alternative", "search_budget_exceeded"]
    stock_indices: frozenset[int]
    gl_indices: frozenset[int]
    candidate_count: int
    optimal_cardinality: int
    optimal_cost: int


@dataclass(frozen=True)
class MatchAssignment:
    """Selected pairs plus components deliberately left unresolved."""

    matches: tuple[MatchCandidate, ...]
    ambiguities: tuple[MatchAmbiguity, ...]
    ambiguity_policy: MatchingAmbiguityPolicy


@dataclass
class _FlowEdge:
    """Mutable residual edge used by deterministic min-cost matching."""

    to: int
    reverse: int
    capacity: int
    cost: int


def _string(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _money(
    value: object,
    currency: object = "USD",
    *,
    strict_precision: bool = False,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> Money | None:
    try:
        cur_str = _string(currency)
        if not cur_str:
            cur_str = "USD"
        return Money(
            value,
            currency=cur_str,
            strict_precision=strict_precision,
            input_policy=input_policy,
        )
    except InvalidAmountError:
        return None


def _date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "nat", "none"}:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(text, errors="coerce")
    if not isinstance(parsed, pd.Timestamp):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def normalize_reference(value: object) -> str:
    """Normalize an ERP reference while preserving alphanumeric meaning.

    Unicode compatibility/case differences and punctuation are ignored. Each
    numeric token is canonicalized so references such as ``INV-001`` and
    ``inv/1`` compare consistently.
    """

    text = unicode_normalize("NFKC", _string(value)).casefold()
    tokens = findall(r"[a-z]+|\d+", text)
    return "".join(str(int(token)) if token.isdigit() else token for token in tokens).upper()


def reference_similarity(left: object, right: object) -> Decimal:
    """Return normalized text similarity from 0 to 1."""

    left_norm = normalize_reference(left)
    right_norm = normalize_reference(right)
    if not left_norm or not right_norm:
        return Decimal("0")
    if left_norm in right_norm or right_norm in left_norm:
        return Decimal("0.94")
    return Decimal(str(SequenceMatcher(None, left_norm, right_norm).ratio())).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_EVEN,
    )


def is_exact_match(
    stock_row: pd.Series,
    gl_row: pd.Series,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> bool:
    """Return true when a pair meets Level 1 exact matching criteria."""

    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    if stock_money is None or gl_money is None or stock_money.currency != gl_money.currency:
        return False

    return (
        _string(stock_row.get("source_document")) == _string(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and abs(stock_money - gl_money).amount <= Decimal("0.01")
    )


def is_fuzzy_reference_match(
    stock_row: pd.Series,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> bool:
    """Return true when a pair meets Level 2 fuzzy reference criteria."""

    source_document = normalize_reference(stock_row.get("source_document"))
    reference = normalize_reference(gl_row.get("reference"))
    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    if not source_document or not reference:
        return False
    reference_match = source_document in reference or reference in source_document
    return (
        stock_money is not None
        and gl_money is not None
        and stock_money.currency == gl_money.currency
        and reference_match
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and abs(stock_money - gl_money).amount <= parse_exact_amount(config.amount_tolerance)
    )


def is_normalized_reference_match(
    stock_row: pd.Series,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> bool:
    """Return true when normalized references and work order/amount agree."""

    source_document = normalize_reference(stock_row.get("source_document"))
    reference = normalize_reference(gl_row.get("reference"))
    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    return (
        bool(source_document)
        and source_document == reference
        and stock_money is not None
        and gl_money is not None
        and stock_money.currency == gl_money.currency
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and abs(stock_money - gl_money).amount <= parse_exact_amount(config.amount_tolerance)
    )


def is_proximity_match(
    stock_row: pd.Series,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> bool:
    """Return true when a pair meets Level 3 amount/date proximity criteria."""

    stock_date = _date(stock_row.get("date"))
    gl_date = _date(gl_row.get("date"))
    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    day_difference = days_between(stock_date, gl_date)
    return (
        stock_money is not None
        and gl_money is not None
        and stock_money.currency == gl_money.currency
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and abs(stock_money - gl_money).amount <= parse_exact_amount(config.amount_tolerance)
        and day_difference is not None
        and day_difference <= config.date_tolerance_days
    )


def is_value_difference(
    stock_row: pd.Series,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> bool:
    """Return true when a pair has the same source/work order but a material amount difference."""

    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    source_document = normalize_reference(stock_row.get("source_document"))
    return (
        stock_money is not None
        and gl_money is not None
        and stock_money.currency == gl_money.currency
        and bool(source_document)
        and source_document == normalize_reference(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and abs(stock_money - gl_money).amount > parse_exact_amount(config.amount_tolerance)
    )


def _pair_candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_index: int,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    strategy: MatchingStrategy,
    input_policy: FinancialInputPolicy,
) -> MatchCandidate | None:
    """Return the highest-quality supported classification for one pair."""

    minimum_similarity = {
        "strict": Decimal("0.98"),
        "standard": Decimal("0.88"),
        "aggressive": Decimal("0.76"),
        "audit-safe": Decimal("0.93"),
    }[strategy]
    allow_proximity = strategy != "strict"
    allow_value_difference = strategy in {"standard", "aggressive", "audit-safe"}

    if is_exact_match(stock_row, gl_row, input_policy=input_policy):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 1 Exact",
            Decimal("1"),
            "source_document, work_order, and amount match",
            False,
            input_policy=input_policy,
        )
    if is_normalized_reference_match(stock_row, gl_row, config, input_policy=input_policy):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 2 Normalized Reference",
            Decimal("0.92"),
            "normalized references match with same work_order and amount tolerance",
            strategy == "audit-safe",
            input_policy=input_policy,
        )
    similarity = reference_similarity(stock_row.get("source_document"), gl_row.get("reference"))
    if (
        is_fuzzy_reference_match(stock_row, gl_row, config, input_policy=input_policy)
        and similarity >= minimum_similarity
    ):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 2 Fuzzy Reference",
            Decimal("0.86") if strategy != "aggressive" else Decimal("0.78"),
            "reference contains or resembles source_document with same work_order and amount tolerance",
            strategy in {"audit-safe", "aggressive"},
            input_policy=input_policy,
        )
    if allow_proximity and is_proximity_match(
        stock_row,
        gl_row,
        config,
        input_policy=input_policy,
    ):
        confidence = Decimal("0.72") if strategy != "audit-safe" else Decimal("0.67")
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 3 Amount/Date Proximity",
            confidence,
            "same work_order with amount and date proximity",
            True,
            input_policy=input_policy,
        )
    if allow_value_difference and is_value_difference(
        stock_row,
        gl_row,
        config,
        input_policy=input_policy,
    ):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Value Difference",
            Decimal("0.66"),
            "same source_document and work_order with amount outside tolerance",
            True,
            input_policy=input_policy,
        )

    return None


def _stable_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        normalized = Decimal("0") if value == 0 else value.normalize()
        return format(normalized, "f")
    return str(value).strip()


def _stable_row_key(row: pd.Series, *, identifier: str, kind: str) -> str:
    payload = {
        str(column): _stable_value(row.get(column))
        for column in sorted(str(column) for column in row.index)
        if not str(column).startswith("_reconforge_")
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    ).hexdigest()
    return f"{kind}:{_string(row.get(identifier))}:{fingerprint}"


def prepare_record_lineage(
    frame: pd.DataFrame,
    *,
    identifier: str,
    kind: str,
    preserve_source_positions: bool = False,
) -> pd.DataFrame:
    """Attach multiset-stable identity and non-identity source location metadata."""

    prepared = frame.copy()
    preserved_positions = (
        prepared[SOURCE_POSITION_COLUMN].copy()
        if preserve_source_positions and SOURCE_POSITION_COLUMN in prepared.columns
        else None
    )
    prepared = prepared.drop(columns=list(INTERNAL_LINEAGE_COLUMNS), errors="ignore")
    if preserved_positions is not None:
        prepared[SOURCE_POSITION_COLUMN] = preserved_positions
    records: list[tuple[int, str, int]] = []
    for position, (raw_index, raw_row) in enumerate(prepared.iterrows(), start=1):
        index = int(cast(int, raw_index))
        row = cast("pd.Series[Any]", raw_row)
        existing_position = row.get(SOURCE_POSITION_COLUMN)
        source_position = (
            int(existing_position)
            if isinstance(existing_position, Integral)
            and not isinstance(existing_position, bool)
            and int(existing_position) > 0
            else position
        )
        records.append((index, _stable_row_key(row, identifier=identifier, kind=kind), source_position))

    totals = Counter(identity for _, identity, _ in records)
    occurrences: Counter[str] = Counter()
    lineage: dict[int, tuple[str, str, int, int, int]] = {}
    for index, identity, source_position in sorted(records, key=lambda item: (item[1], item[2], item[0])):
        occurrences[identity] += 1
        ordinal = occurrences[identity]
        duplicate_count = totals[identity]
        instance_id = identity if duplicate_count == 1 else f"{identity}#occurrence:{ordinal}"
        fingerprint = identity.rsplit(":", 1)[-1]
        lineage[index] = (instance_id, fingerprint, ordinal, duplicate_count, source_position)

    prepared[RECORD_INSTANCE_ID_COLUMN] = [lineage[int(index)][0] for index in prepared.index]
    prepared[RECORD_FINGERPRINT_COLUMN] = [lineage[int(index)][1] for index in prepared.index]
    prepared[DUPLICATE_ORDINAL_COLUMN] = [lineage[int(index)][2] for index in prepared.index]
    prepared[DUPLICATE_COUNT_COLUMN] = [lineage[int(index)][3] for index in prepared.index]
    prepared[SOURCE_POSITION_COLUMN] = [lineage[int(index)][4] for index in prepared.index]
    prepared[SOURCE_ROW_COLUMN] = [lineage[int(index)][4] + 1 for index in prepared.index]
    prepared[SOURCE_ROW_BASIS_COLUMN] = SOURCE_ROW_BASIS
    prepared[RECORD_IDENTITY_POLICY_COLUMN] = RECORD_IDENTITY_POLICY
    return prepared


def _stable_match_id(stock_key: str, gl_key: str) -> str:
    digest = hashlib.sha256(f"{stock_key}|{gl_key}".encode()).hexdigest()[:20].upper()
    return f"MATCH-{digest}"


def _candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_index: int,
    gl_row: pd.Series,
    level: MatchLevel,
    confidence: Decimal,
    reason: str,
    review_required: bool,
    *,
    input_policy: FinancialInputPolicy,
) -> MatchCandidate:
    stock_money = _money(
        stock_row.get("total_cost"),
        stock_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    gl_money = _money(
        gl_row.get("amount"),
        gl_row.get("currency"),
        strict_precision=True,
        input_policy=input_policy,
    )
    if stock_money is None or gl_money is None:
        raise InvalidAmountError("matched rows require valid financial amounts")
    date_difference = days_between(_date(stock_row.get("date")), _date(gl_row.get("date")))
    stock_move_id = _string(stock_row.get("move_id"))
    gl_entry_id = _string(gl_row.get("entry_id"))
    stock_sort_key = str(
        stock_row.get(RECORD_INSTANCE_ID_COLUMN)
        or _stable_row_key(stock_row, identifier="move_id", kind="stock")
    )
    gl_sort_key = str(
        gl_row.get(RECORD_INSTANCE_ID_COLUMN)
        or _stable_row_key(gl_row, identifier="entry_id", kind="gl")
    )
    amount_difference = (stock_money - gl_money).amount if stock_money.currency == gl_money.currency else Decimal("0")
    return MatchCandidate(
        match_id=_stable_match_id(stock_sort_key, gl_sort_key),
        stock_index=stock_index,
        gl_index=gl_index,
        stock_move_id=stock_move_id,
        gl_entry_id=gl_entry_id,
        match_level=level,
        confidence=confidence,
        amount_difference=amount_difference,
        date_difference=date_difference,
        reference_similarity=reference_similarity(stock_row.get("source_document"), gl_row.get("reference")),
        reason=reason,
        review_required=review_required,
        stock_sort_key=stock_sort_key,
        gl_sort_key=gl_sort_key,
        stock_record_instance_id=stock_sort_key,
        gl_record_instance_id=gl_sort_key,
        stock_duplicate_ordinal=int(stock_row.get(DUPLICATE_ORDINAL_COLUMN) or 1),
        gl_duplicate_ordinal=int(gl_row.get(DUPLICATE_ORDINAL_COLUMN) or 1),
        stock_duplicate_count=int(stock_row.get(DUPLICATE_COUNT_COLUMN) or 1),
        gl_duplicate_count=int(gl_row.get(DUPLICATE_COUNT_COLUMN) or 1),
        stock_source_position=int(stock_row.get(SOURCE_POSITION_COLUMN) or 0),
        gl_source_position=int(gl_row.get(SOURCE_POSITION_COLUMN) or 0),
        stock_source_row=int(stock_row.get(SOURCE_ROW_COLUMN) or 0),
        gl_source_row=int(gl_row.get(SOURCE_ROW_COLUMN) or 0),
    )


_LEVEL_UTILITY: dict[MatchLevel, int] = {
    "Level 1 Exact": 5_000_000,
    "Level 2 Normalized Reference": 4_000_000,
    "Level 2 Fuzzy Reference": 3_000_000,
    "Level 3 Amount/Date Proximity": 2_000_000,
    "Value Difference": 1_000_000,
}
_MAX_PAIR_UTILITY = 6_000_000


def _candidate_cost(candidate: MatchCandidate) -> int:
    """Return a deterministic non-negative cost; lower means better."""

    utility = _LEVEL_UTILITY[candidate.match_level]
    utility += int(
        (candidate.confidence * Decimal("100000")).to_integral_value(
            rounding=ROUND_HALF_EVEN,
        ),
    )
    utility += int(
        (candidate.reference_similarity * Decimal("10000")).to_integral_value(
            rounding=ROUND_HALF_EVEN,
        ),
    )
    amount_penalty = min(
        int(
            (abs(candidate.amount_difference) * Decimal("100")).to_integral_value(
                rounding=ROUND_HALF_EVEN,
            ),
        ),
        5_000,
    )
    utility += max(0, 5_000 - amount_penalty)
    if candidate.date_difference is not None:
        utility += max(0, 1_000 - min(abs(candidate.date_difference), 1_000))
    return _MAX_PAIR_UTILITY - utility


def _add_flow_edge(graph: list[list[_FlowEdge]], source: int, target: int, capacity: int, cost: int) -> _FlowEdge:
    forward = _FlowEdge(to=target, reverse=len(graph[target]), capacity=capacity, cost=cost)
    backward = _FlowEdge(to=source, reverse=len(graph[source]), capacity=0, cost=-cost)
    graph[source].append(forward)
    graph[target].append(backward)
    return forward


def _minimum_cost_assignment(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
    """Compute a maximum-cardinality, maximum-quality bipartite assignment."""

    if not candidates:
        return []
    stock_keys = {candidate.stock_index: candidate.stock_sort_key for candidate in candidates}
    gl_keys = {candidate.gl_index: candidate.gl_sort_key for candidate in candidates}
    stock_indices = sorted(stock_keys, key=lambda index: (stock_keys[index], index))
    gl_indices = sorted(gl_keys, key=lambda index: (gl_keys[index], index))
    stock_nodes = {index: position + 1 for position, index in enumerate(stock_indices)}
    gl_offset = 1 + len(stock_indices)
    gl_nodes = {index: gl_offset + position for position, index in enumerate(gl_indices)}
    sink = gl_offset + len(gl_indices)
    graph: list[list[_FlowEdge]] = [[] for _ in range(sink + 1)]
    for index in stock_indices:
        _add_flow_edge(graph, 0, stock_nodes[index], 1, 0)
    for index in gl_indices:
        _add_flow_edge(graph, gl_nodes[index], sink, 1, 0)

    tracked_edges: list[tuple[_FlowEdge, MatchCandidate]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.stock_sort_key, _candidate_cost(item), item.gl_sort_key, item.match_id),
    ):
        edge = _add_flow_edge(
            graph,
            stock_nodes[candidate.stock_index],
            gl_nodes[candidate.gl_index],
            1,
            _candidate_cost(candidate),
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

    selected = [candidate for edge, candidate in tracked_edges if edge.capacity == 0]
    return sorted(selected, key=lambda candidate: candidate.match_id)


def _candidate_components(candidates: list[MatchCandidate]) -> list[list[MatchCandidate]]:
    """Split a candidate graph into deterministic independent components."""

    if not candidates:
        return []
    def candidate_order(item: MatchCandidate) -> tuple[str, int, str, str]:
        return (
            item.stock_sort_key,
            _candidate_cost(item),
            item.gl_sort_key,
            item.match_id,
        )
    stock_candidates: dict[int, list[int]] = {}
    gl_candidates: dict[int, list[int]] = {}
    for index, candidate in enumerate(candidates):
        stock_candidates.setdefault(candidate.stock_index, []).append(index)
        gl_candidates.setdefault(candidate.gl_index, []).append(index)

    unseen = set(range(len(candidates)))
    components: list[list[MatchCandidate]] = []
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
            neighbors = stock_candidates[candidate.stock_index] + gl_candidates[candidate.gl_index]
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
    return components


def _ambiguity_group(
    component: list[MatchCandidate],
    selected: list[MatchCandidate],
    *,
    reason: Literal["equal_cost_alternative", "search_budget_exceeded"],
) -> MatchAmbiguity:
    stock_indices = frozenset(candidate.stock_index for candidate in component)
    gl_indices = frozenset(candidate.gl_index for candidate in component)
    optimal_cost = sum(_candidate_cost(candidate) for candidate in selected)
    payload = {
        "candidate_count": len(component),
        "gl_record_instance_ids": sorted({candidate.gl_record_instance_id for candidate in component}),
        "optimal_cardinality": len(selected),
        "optimal_cost": optimal_cost,
        "reason": reason,
        "stock_record_instance_ids": sorted(
            {candidate.stock_record_instance_id for candidate in component}
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:20].upper()
    return MatchAmbiguity(
        ambiguity_group_id=f"AMB-{digest}",
        reason=reason,
        stock_indices=stock_indices,
        gl_indices=gl_indices,
        candidate_count=len(component),
        optimal_cardinality=len(selected),
        optimal_cost=optimal_cost,
    )


def _has_equal_cost_alternative(
    component: list[MatchCandidate],
    selected: list[MatchCandidate],
) -> bool:
    """Prove non-uniqueness by forbidding each selected edge within a fixed budget."""

    if not selected:
        return False
    expected_cardinality = len(selected)
    expected_cost = sum(_candidate_cost(candidate) for candidate in selected)
    for selected_candidate in selected:
        alternatives = [candidate for candidate in component if candidate is not selected_candidate]
        alternate_selection = _minimum_cost_assignment(alternatives)
        if len(alternate_selection) != expected_cardinality:
            continue
        alternate_cost = sum(_candidate_cost(candidate) for candidate in alternate_selection)
        if alternate_cost == expected_cost:
            return True
    return False


def _resolve_candidate_component(
    component: list[MatchCandidate],
    *,
    ambiguity_policy: MatchingAmbiguityPolicy,
) -> tuple[list[MatchCandidate], MatchAmbiguity | None]:
    selected = _minimum_cost_assignment(component)
    if ambiguity_policy == "stable-tie-break-v1":
        return selected, None
    if (
        len(component) > AMBIGUITY_MAX_CANDIDATES
        or len(selected) > AMBIGUITY_MAX_ASSIGNMENT_CHECKS
    ):
        return [], _ambiguity_group(component, selected, reason="search_budget_exceeded")
    if _has_equal_cost_alternative(component, selected):
        return [], _ambiguity_group(component, selected, reason="equal_cost_alternative")
    return selected, None


def assign_stock_to_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    strategy: MatchingStrategy = "standard",
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    lineage_prepared: bool = False,
    ambiguity_policy: MatchingAmbiguityPolicy = DEFAULT_MATCHING_AMBIGUITY_POLICY,
) -> MatchAssignment:
    """Assign records and retain bounded, explainable unresolved components."""

    input_policy = validate_financial_input_policy(input_policy)
    if strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        raise ValueError("matching strategy must be one of: standard, strict, aggressive, audit-safe")
    if ambiguity_policy not in {"stable-tie-break-v1", "unresolved-equal-cost-v1"}:
        raise ValueError(
            "ambiguity policy must be one of: stable-tie-break-v1, unresolved-equal-cost-v1"
        )
    stock_moves = prepare_record_lineage(
        stock_moves,
        identifier="move_id",
        kind="stock",
        preserve_source_positions=lineage_prepared,
    )
    gl_entries = prepare_record_lineage(
        gl_entries,
        identifier="entry_id",
        kind="gl",
        preserve_source_positions=lineage_prepared,
    )
    gl_by_work_order: dict[str, list[tuple[int, pd.Series]]] = {}
    for raw_gl_index, raw_gl_row in gl_entries.iterrows():
        gl_index = int(cast(int, raw_gl_index))
        gl_row = cast("pd.Series[Any]", raw_gl_row)
        gl_by_work_order.setdefault(_string(gl_row.get("work_order")), []).append((gl_index, gl_row))

    candidates_by_work_order: dict[str, list[MatchCandidate]] = {}
    for raw_stock_index, stock_row in stock_moves.iterrows():
        stock_index = int(cast(int, raw_stock_index))
        typed_stock_row = cast("pd.Series[Any]", stock_row)
        work_order = _string(typed_stock_row.get("work_order"))
        for gl_index, gl_row in gl_by_work_order.get(work_order, []):
            candidate = _pair_candidate(
                stock_index,
                typed_stock_row,
                gl_index,
                gl_row,
                config,
                strategy,
                input_policy,
            )
            if candidate is not None:
                candidates_by_work_order.setdefault(work_order, []).append(candidate)

    matches: list[MatchCandidate] = []
    ambiguities: list[MatchAmbiguity] = []
    for work_order in sorted(candidates_by_work_order):
        work_order_candidates = candidates_by_work_order[work_order]
        if ambiguity_policy == "stable-tie-break-v1":
            matches.extend(_minimum_cost_assignment(work_order_candidates))
            continue
        for component in _candidate_components(work_order_candidates):
            selected, ambiguity = _resolve_candidate_component(
                component,
                ambiguity_policy=ambiguity_policy,
            )
            matches.extend(selected)
            if ambiguity is not None:
                ambiguities.append(ambiguity)
    return MatchAssignment(
        matches=tuple(sorted(matches, key=lambda candidate: candidate.match_id)),
        ambiguities=tuple(sorted(ambiguities, key=lambda ambiguity: ambiguity.ambiguity_group_id)),
        ambiguity_policy=ambiguity_policy,
    )


def match_stock_to_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    strategy: MatchingStrategy = "standard",
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    lineage_prepared: bool = False,
    ambiguity_policy: MatchingAmbiguityPolicy = DEFAULT_MATCHING_AMBIGUITY_POLICY,
) -> list[MatchCandidate]:
    """Run deterministic global matching against stock and GL exports.

    Assignment is solved independently per work order because every supported
    candidate rule requires equal work orders. Within each partition the
    result maximizes pair count first and aggregate match quality second.
    """

    assignment = assign_stock_to_gl(
        stock_moves,
        gl_entries,
        config,
        strategy,
        input_policy=input_policy,
        lineage_prepared=lineage_prepared,
        ambiguity_policy=ambiguity_policy,
    )
    return list(assignment.matches)
