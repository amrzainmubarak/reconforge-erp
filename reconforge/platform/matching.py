"""Scalable deterministic matching foundations."""

from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from re import findall
from typing import Any
from unicodedata import normalize as normalize_unicode

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    date_diff_days,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    read_local_records,
    require_permission,
    rows_to_dicts,
)
from reconforge.utils.money import InvalidAmountError, parse_amount, round_money


def _parse_amount(value: object) -> Decimal | None:
    """Parse a strict amount and return ``None`` when invalid."""

    try:
        return parse_amount(value)
    except InvalidAmountError:
        return None


def _normalize_reference(value: object) -> str:
    """Normalize references for matching while preserving numeric meaning."""

    text = normalize_unicode("NFKC", normalize_text(value, default="")).strip()
    if not text:
        return ""
    compact = "".join(part for part in text.split())
    tokens = findall(r"[A-Z]+|\d+", compact.upper())
    normalized_tokens: list[str] = []
    for token in tokens:
        if token.isdigit():
            normalized_tokens.append(str(int(token)))
        elif token:
            normalized_tokens.append(token)
    return "".join(normalized_tokens)


@dataclass(frozen=True)
class MatchRunResult:
    """Result from one deterministic match job."""

    job_id: str
    result_count: int
    matched_count: int


@dataclass(frozen=True)
class _MatchCandidate:
    left_index: int
    right_index: int
    left_id: str
    right_id: str
    left_sort_key: str
    right_sort_key: str
    confidence: float
    explanation: str
    amount_difference: float
    date_difference_days: int


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
        amount_tolerance: float = 0.0,
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        actor_label: str = "local-cli",
    ) -> MatchRunResult:
        """Run deterministic local matching without a full cross product where possible."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        left_source, left_records = read_local_records(left_path)
        right_source, right_records = read_local_records(right_path)
        return self._run_records(
            left_records=left_records,
            right_records=right_records,
            workspace=workspace,
            name=name,
            left_source=left_source.name,
            right_source=right_source.name,
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
            actor_label=actor_label,
        )

    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult:
        """Run a synthetic local benchmark job and persist summary results."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        if rows < 1 or rows > 250000:
            raise PlatformError("Benchmark rows must be between 1 and 250000.")
        left_records = [
            {"id": f"L-{index}", "reference": f"REF-{index}", "amount": index * 10.0, "date": "2026-01-15"}
            for index in range(rows)
        ]
        right_records = [
            {"id": f"R-{index}", "reference": f"REF-{index}", "amount": index * 10.0, "date": "2026-01-15"}
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
            amount_tolerance=0.0,
            date_window_days=0,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
            actor_label=actor_label,
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Return one match job status."""

        row = self.connection.execute("SELECT * FROM match_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise PlatformError("Match job not found.")
        payload = dict(row)
        counts = self.connection.execute(
            """
            SELECT
                COUNT(*) AS result_count,
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
                "SELECT * FROM match_results WHERE job_id = ? AND status = ? ORDER BY confidence DESC, left_id",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? ORDER BY confidence DESC, left_id",
                (job_id,),
            ).fetchall()
        return rows_to_dicts(rows)

    def list_jobs(self) -> list[dict[str, Any]]:
        """List match jobs."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM match_jobs ORDER BY created_at DESC").fetchall())

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
        amount_tolerance: float,
        date_window_days: int,
        allow_many_to_one: bool,
        allow_one_to_many: bool,
        allow_many_to_many: bool,
        actor_label: str,
    ) -> MatchRunResult:
        workspace_id = ensure_workspace(self.connection, workspace)
        created_at = utc_now_text()
        job_id = platform_id("MJ", workspace_id, name, left_source, right_source, created_at)
        exact_field_list = [field.strip() for field in exact_fields.split(",") if field.strip()]
        rule: dict[str, object] = {
            "amount_field": amount_field,
            "date_field": date_field,
            "reference_field": reference_field,
            "exact_fields": exact_field_list,
            "amount_tolerance": amount_tolerance,
            "date_window_days": date_window_days,
            "allow_many_to_one": allow_many_to_one,
            "allow_one_to_many": allow_one_to_many,
            "allow_many_to_many": allow_many_to_many,
        }
        self.connection.execute(
            """
            INSERT INTO match_jobs (
                id, workspace_id, name, left_source, right_source, status,
                rule_json, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'Running', ?, ?, ?)
            """,
            (job_id, workspace_id, name, left_source, right_source, json.dumps(rule, sort_keys=True), actor_label, created_at),
        )
        self.connection.execute(
            "INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (platform_id("MR", job_id, "primary"), job_id, "primary", json.dumps(rule, sort_keys=True), created_at),
        )
        ordered_right = self._ordered_records(
            right_records,
            id_field=right_id_field,
            prefix="R",
            amount_field=amount_field,
        )
        right_index = self._build_right_index(
            ordered_right,
            reference_field=reference_field,
            exact_fields=exact_field_list,
        )

        ordered_left = self._ordered_records(
            left_records,
            id_field=left_id_field,
            prefix="L",
            amount_field=amount_field,
        )
        ordered_candidates = self._build_candidates(
            ordered_left,
            right_index,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_field_list,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
        )
        selected_matches = self._minimum_cost_assignment(
            ordered_candidates,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
        )
        selected_by_left: dict[int, list[_MatchCandidate]] = {}
        for match in selected_matches:
            selected_by_left.setdefault(match.left_index, []).append(match)
        result_count = 0
        matched_count = 0
        for left_index, left_id, _, _, _, left_amount in ordered_left:
            matches = selected_by_left.get(left_index, [])
            if not matches:
                explanation = "No indexed candidate met the configured rules."
                if left_amount is None:
                    explanation = "No indexed candidate; source amount is invalid and cannot be matched."
                self._insert_result(
                    job_id=job_id,
                    left_id=left_id,
                    right_id="",
                    match_type="unmatched",
                    confidence=0.0,
                    explanation=explanation,
                    amount_difference=0.0,
                    date_difference_days=0,
                    status="Unmatched",
                )
                result_count += 1
                continue

            for match in matches:
                self._insert_result(
                    job_id=job_id,
                    left_id=match.left_id,
                    right_id=match.right_id,
                    match_type="deterministic",
                    confidence=match.confidence,
                    explanation=match.explanation,
                    amount_difference=match.amount_difference,
                    date_difference_days=match.date_difference_days,
                    status="Matched",
                )
                matched_count += 1
                result_count += 1
        self.connection.execute(
            "UPDATE match_jobs SET status = 'Complete', completed_at = ? WHERE id = ?",
            (utc_now_text(), job_id),
        )
        self.connection.commit()
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="match_job",
            object_id=job_id,
            action="match_job_completed",
            metadata={"result_count": result_count, "matched_count": matched_count},
        )
        return MatchRunResult(job_id=job_id, result_count=result_count, matched_count=matched_count)

    def _build_right_index(
        self,
        ordered_right_records: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]],
        *,
        reference_field: str,
        exact_fields: list[str],
    ) -> dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal]]]]:
        indexes: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal]]]] = {
            "reference": {},
            "amount": {},
            "exact": {},
        }
        for index, record_id, record, _stable_key, _, amount_value in ordered_right_records:
            if amount_value is None:
                continue
            reference = _normalize_reference(record.get(reference_field))
            if reference:
                indexes["reference"].setdefault(reference, []).append((index, record_id, record, amount_value))
            amount_bucket = str(round_money(amount_value))
            indexes["amount"].setdefault(amount_bucket, []).append((index, record_id, record, amount_value))
            if exact_fields:
                key = self._exact_key(record, exact_fields)
                indexes["exact"].setdefault(key, []).append((index, record_id, record, amount_value))
        return indexes

    def _candidates(
        self,
        left: dict[str, Any],
        right_index: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal]]]],
        *,
        left_amount: Decimal,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: float,
    ) -> list[tuple[int, str, dict[str, Any], Decimal]]:
        reference = _normalize_reference(left.get(reference_field))
        if reference and reference in right_index["reference"]:
            return right_index["reference"][reference]
        if exact_fields:
            key = self._exact_key(left, exact_fields)
            if key in right_index["exact"]:
                return right_index["exact"][key]
        tolerance_decimal = Decimal(str(amount_tolerance))
        if tolerance_decimal == 0:
            bucket = str(round_money(left_amount))
            return right_index["amount"].get(bucket, [])
        exact_value = left_amount
        selected: list[tuple[int, str, dict[str, Any], Decimal]] = []
        for bucket, candidates in right_index["amount"].items():
            bucket_decimal = Decimal(bucket)
            if abs(exact_value - bucket_decimal) > tolerance_decimal:
                continue
            selected.extend(candidates)
        return selected

    def _ordered_records(
        self,
        records: list[dict[str, Any]],
        *,
        id_field: str,
        prefix: str,
        amount_field: str,
    ) -> list[tuple[int, str, dict[str, Any], str, int, Decimal | None]]:
        prepared: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]] = []
        for index, record in enumerate(records):
            parsed_amount = _parse_amount(record.get(amount_field))
            stable_key = self._record_key(record)
            explicit_id = normalize_key(record.get(id_field), default="")
            base_id = explicit_id or f"{prefix}-{stable_key}"
            prepared.append((index, base_id, record, stable_key, 0, parsed_amount))
        prepared.sort(key=lambda item: (item[1], item[3], item[0]))
        counts: dict[str, int] = {}
        ordered: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]] = []
        for index, base_id, record, stable_key, _, parsed_amount in prepared:
            counts[base_id] = counts.get(base_id, 0) + 1
            occurrence = counts[base_id]
            record_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            ordered.append((index, record_id, record, stable_key, occurrence, parsed_amount))
        ordered.sort(key=lambda item: (item[3], item[4], item[0]))
        return ordered

    def _build_candidates(
        self,
        ordered_left: list[tuple[int, str, dict[str, Any], str, int, Decimal | None]],
        right_index_data: dict[str, dict[str, list[tuple[int, str, dict[str, Any], Decimal]]]],
        *,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: float,
        date_window_days: int,
    ) -> list[_MatchCandidate]:
        candidates: list[_MatchCandidate] = []
        for left_index, left_id, left, left_key, _, left_amount in ordered_left:
            if left_amount is None:
                continue
            for candidate_right_index, right_id, right, right_amount in self._candidates(
                left,
                right_index_data,
                left_amount=left_amount,
                reference_field=reference_field,
                exact_fields=exact_fields,
                amount_tolerance=amount_tolerance,
            ):
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
                )
                if confidence < 0.65:
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
            str(key): ("" if value is None else str(value).strip())
            for key, value in sorted(record.items(), key=lambda item: str(item[0]))
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
            key=lambda item: (item.left_sort_key, self._candidate_cost(item), item.right_sort_key, item.left_id, item.right_id),
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
        score = int(round(candidate.confidence * 1_000_000))
        amount_penalty = min(int(round(abs(candidate.amount_difference) * 10_000)), 2_000_000)
        date_penalty = min(abs(candidate.date_difference_days) * 10, 5_000)
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
        amount_tolerance: float,
        date_window_days: int,
    ) -> tuple[float, list[str], float, int]:
        score = 0.0
        parts: list[str] = []
        left_data = left
        right_data = right
        left_reference = normalize_text(left_data.get(reference_field))
        right_reference = normalize_text(right_data.get(reference_field))
        left_reference_norm = _normalize_reference(left_reference)
        right_reference_norm = _normalize_reference(right_reference)
        if left_reference_norm and left_reference_norm == right_reference_norm:
            score += 0.45
            if left_reference == right_reference:
                parts.append("reference matched exactly")
            else:
                parts.append(f"reference matched after normalization ({left_reference_norm})")
        amount_diff = abs(left_amount - right_amount)
        if amount_diff <= Decimal(str(amount_tolerance)):
            score += 0.30
            parts.append(f"amount within tolerance ({float(amount_diff):.2f})")
        day_diff = date_diff_days(left_data.get(date_field), right_data.get(date_field))
        if day_diff <= date_window_days:
            score += 0.15
            parts.append(f"date within window ({day_diff} days)")
        if exact_fields and self._exact_key(left_data, exact_fields) == self._exact_key(right_data, exact_fields):
            score += 0.10
            parts.append("exact key fields matched")
        return round(min(score, 1.0), 2), parts, float(amount_diff), day_diff

    def _insert_result(
        self,
        *,
        job_id: str,
        left_id: str,
        right_id: str,
        match_type: str,
        confidence: float,
        explanation: str,
        amount_difference: float,
        date_difference_days: int,
        status: str,
    ) -> None:
        result_id = platform_id("MRSLT", job_id, left_id, right_id, match_type)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO match_results (
                id, job_id, left_id, right_id, match_type, confidence, explanation,
                amount_difference, date_difference_days, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                job_id,
                left_id,
                right_id,
                match_type,
                confidence,
                explanation,
                amount_difference,
                date_difference_days,
                status,
                utc_now_text(),
            ),
        )

    @staticmethod
    def _exact_key(record: dict[str, Any], fields: list[str]) -> str:
        return "|".join(normalize_text(record.get(field)).lower() for field in fields)
