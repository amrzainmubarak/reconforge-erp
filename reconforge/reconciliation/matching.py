"""Stock-to-GL matching logic."""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from re import findall
from typing import Any, Literal, cast
from unicodedata import normalize as unicode_normalize

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.utils.dates import days_between
from reconforge.utils.money import InvalidAmountError, money_difference, parse_amount, within_tolerance

MatchLevel = Literal[
    "Level 1 Exact",
    "Level 2 Normalized Reference",
    "Level 2 Fuzzy Reference",
    "Level 3 Amount/Date Proximity",
    "Value Difference",
]
MatchingStrategy = Literal["standard", "strict", "aggressive", "audit-safe"]


@dataclass(frozen=True)
class MatchCandidate:
    """A matched stock and GL pair."""

    stock_index: int
    gl_index: int
    match_level: MatchLevel
    confidence: float
    reason: str
    match_id: str = ""
    stock_move_id: str = ""
    gl_entry_id: str = ""
    amount_difference: float = 0.0
    date_difference: int = 0
    reference_similarity: float = 0.0
    review_required: bool = False
    stock_sort_key: str = ""
    gl_sort_key: str = ""


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


def _amount(value: object) -> float | None:
    try:
        return parse_amount(value)
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


def reference_similarity(left: object, right: object) -> float:
    """Return normalized text similarity from 0 to 1."""

    left_norm = normalize_reference(left)
    right_norm = normalize_reference(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.94
    return round(SequenceMatcher(None, left_norm, right_norm).ratio(), 4)


def is_exact_match(stock_row: pd.Series, gl_row: pd.Series) -> bool:
    """Return true when a pair meets Level 1 exact matching criteria."""

    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    return (
        stock_amount is not None
        and gl_amount is not None
        and _string(stock_row.get("source_document")) == _string(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and money_difference(stock_amount, gl_amount) <= 0.01
    )


def is_fuzzy_reference_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair meets Level 2 fuzzy reference criteria."""

    source_document = normalize_reference(stock_row.get("source_document"))
    reference = normalize_reference(gl_row.get("reference"))
    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    if not source_document or not reference:
        return False
    reference_match = source_document in reference or reference in source_document
    return (
        stock_amount is not None
        and gl_amount is not None
        and reference_match
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(stock_amount, gl_amount, config.amount_tolerance)
    )


def is_normalized_reference_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when normalized references and work order/amount agree."""

    source_document = normalize_reference(stock_row.get("source_document"))
    reference = normalize_reference(gl_row.get("reference"))
    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    return (
        bool(source_document)
        and source_document == reference
        and stock_amount is not None
        and gl_amount is not None
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(stock_amount, gl_amount, config.amount_tolerance)
    )


def is_proximity_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair meets Level 3 amount/date proximity criteria."""

    stock_date = _date(stock_row.get("date"))
    gl_date = _date(gl_row.get("date"))
    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    day_difference = days_between(stock_date, gl_date)
    return (
        stock_amount is not None
        and gl_amount is not None
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(stock_amount, gl_amount, config.amount_tolerance)
        and day_difference is not None
        and day_difference <= config.date_tolerance_days
    )


def is_value_difference(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair has the same source/work order but a material amount difference."""

    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    source_document = normalize_reference(stock_row.get("source_document"))
    return (
        stock_amount is not None
        and gl_amount is not None
        and bool(source_document)
        and source_document == normalize_reference(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and money_difference(stock_amount, gl_amount) > config.amount_tolerance
    )


def _pair_candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_index: int,
    gl_row: pd.Series,
    config: ReconForgeConfig,
    strategy: MatchingStrategy,
) -> MatchCandidate | None:
    """Return the highest-quality supported classification for one pair."""

    minimum_similarity = {"strict": 0.98, "standard": 0.88, "aggressive": 0.76, "audit-safe": 0.93}[strategy]
    allow_proximity = strategy != "strict"
    allow_value_difference = strategy in {"standard", "aggressive", "audit-safe"}

    if is_exact_match(stock_row, gl_row):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 1 Exact",
            1.0,
            "source_document, work_order, and amount match",
            False,
        )
    if is_normalized_reference_match(stock_row, gl_row, config):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 2 Normalized Reference",
            0.92,
            "normalized references match with same work_order and amount tolerance",
            strategy == "audit-safe",
        )
    similarity = reference_similarity(stock_row.get("source_document"), gl_row.get("reference"))
    if is_fuzzy_reference_match(stock_row, gl_row, config) and similarity >= minimum_similarity:
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 2 Fuzzy Reference",
            0.86 if strategy != "aggressive" else 0.78,
            "reference contains or resembles source_document with same work_order and amount tolerance",
            strategy in {"audit-safe", "aggressive"},
        )
    if allow_proximity and is_proximity_match(stock_row, gl_row, config):
        confidence = 0.72 if strategy != "audit-safe" else 0.67
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Level 3 Amount/Date Proximity",
            confidence,
            "same work_order with amount and date proximity",
            True,
        )
    if allow_value_difference and is_value_difference(stock_row, gl_row, config):
        return _candidate(
            stock_index,
            stock_row,
            gl_index,
            gl_row,
            "Value Difference",
            0.66,
            "same source_document and work_order with amount outside tolerance",
            True,
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
    return str(value).strip()


def _stable_row_key(row: pd.Series, *, identifier: str, kind: str) -> str:
    payload = {str(column): _stable_value(row.get(column)) for column in sorted(str(column) for column in row.index)}
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    ).hexdigest()
    return f"{kind}:{_string(row.get(identifier))}:{fingerprint}"


def _stable_match_id(stock_key: str, gl_key: str) -> str:
    digest = hashlib.sha256(f"{stock_key}|{gl_key}".encode()).hexdigest()[:20].upper()
    return f"MATCH-{digest}"


def _candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_index: int,
    gl_row: pd.Series,
    level: MatchLevel,
    confidence: float,
    reason: str,
    review_required: bool,
) -> MatchCandidate:
    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    if stock_amount is None or gl_amount is None:
        raise InvalidAmountError("matched rows require valid financial amounts")
    date_difference = days_between(_date(stock_row.get("date")), _date(gl_row.get("date"))) or 0
    stock_move_id = _string(stock_row.get("move_id"))
    gl_entry_id = _string(gl_row.get("entry_id"))
    stock_sort_key = _stable_row_key(stock_row, identifier="move_id", kind="stock")
    gl_sort_key = _stable_row_key(gl_row, identifier="entry_id", kind="gl")
    return MatchCandidate(
        match_id=_stable_match_id(stock_sort_key, gl_sort_key),
        stock_index=stock_index,
        gl_index=gl_index,
        stock_move_id=stock_move_id,
        gl_entry_id=gl_entry_id,
        match_level=level,
        confidence=confidence,
        amount_difference=round(stock_amount - gl_amount, 2),
        date_difference=date_difference,
        reference_similarity=reference_similarity(stock_row.get("source_document"), gl_row.get("reference")),
        reason=reason,
        review_required=review_required,
        stock_sort_key=stock_sort_key,
        gl_sort_key=gl_sort_key,
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
    utility += int(round(candidate.confidence * 100_000))
    utility += int(round(candidate.reference_similarity * 10_000))
    utility += max(0, 5_000 - min(int(round(abs(candidate.amount_difference) * 100)), 5_000))
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


def match_stock_to_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    strategy: MatchingStrategy = "standard",
) -> list[MatchCandidate]:
    """Run deterministic global matching against stock and GL exports.

    Assignment is solved independently per work order because every supported
    candidate rule requires equal work orders. Within each partition the
    result maximizes pair count first and aggregate match quality second.
    """

    if strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        raise ValueError("matching strategy must be one of: standard, strict, aggressive, audit-safe")
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
            candidate = _pair_candidate(stock_index, typed_stock_row, gl_index, gl_row, config, strategy)
            if candidate is not None:
                candidates_by_work_order.setdefault(work_order, []).append(candidate)

    matches: list[MatchCandidate] = []
    for work_order in sorted(candidates_by_work_order):
        matches.extend(_minimum_cost_assignment(candidates_by_work_order[work_order]))
    return sorted(matches, key=lambda candidate: candidate.match_id)
