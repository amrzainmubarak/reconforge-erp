"""Tenant-scoped PostgreSQL worker for reconciliation runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Any, Protocol, cast

from reconforge.application.matching import LEGACY_RECORD_IDENTITY_POLICY
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext, audit_policy_decision
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationBusyError,
    PostgresReconciliationRepository,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_postgres_reconciliation_attributes,
    decode_postgres_reconciliation_evidence,
    decode_postgres_reconciliation_lineage,
    decode_postgres_reconciliation_rule,
)
from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    CurrencyRegistry,
    FinancialInputPolicy,
    InvalidAmountError,
)


def _stable_partition_key(values: Sequence[object]) -> str:
    """Hash ordered hard-key values with one shared canonical encoding."""

    payload = json.dumps(list(values), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PostgresReconciliationWorkerError(RuntimeError):
    """Raised when a reconciliation worker cannot safely finish a cycle."""


class ReconciliationCancellationRequested(PostgresReconciliationWorkerError):
    """Raised by an injected matcher when cooperative cancellation is observed."""


@dataclass(frozen=True)
class ReconciliationExecutionResult:
    """Validated matcher output handed to the persistence boundary."""

    results: tuple[Mapping[str, object], ...] = ()
    exceptions: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class ReconciliationPartitionResult:
    """One bounded partition output that can be committed and resumed."""

    partition_key: str
    input_count: int
    results: tuple[Mapping[str, object], ...] = ()
    exceptions: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class ReconciliationInputPartition:
    """A lazy-input partition supplied by a relation-native repository."""

    partition_key: str
    left_inputs: tuple[Mapping[str, Any], ...]
    right_inputs: tuple[Mapping[str, Any], ...]

    @property
    def input_count(self) -> int:
        """Return the bounded number of records in this partition."""

        return len(self.left_inputs) + len(self.right_inputs)


@dataclass(frozen=True)
class ReconciliationExecutionContext:
    """Inputs and control callbacks supplied to one deterministic matcher."""

    run: Mapping[str, Any]
    left_inputs: tuple[Mapping[str, Any], ...]
    right_inputs: tuple[Mapping[str, Any], ...]
    heartbeat: Callable[[int], Mapping[str, Any]]
    cancellation_requested: Callable[[], bool]
    partition_supplier: Callable[[], Iterable[ReconciliationInputPartition]] | None = None

    def raise_if_cancelled(self) -> None:
        """Stop matcher work when an operator has requested cancellation."""

        if self.cancellation_requested():
            raise ReconciliationCancellationRequested("Reconciliation cancellation was requested.")


class ReconciliationMatcher(Protocol):
    """Injected deterministic matcher contract; it must not write PostgreSQL directly."""

    def __call__(self, context: ReconciliationExecutionContext) -> ReconciliationExecutionResult:
        """Return every result and exception for the supplied canonical inputs."""


class ReconciliationPartitionMatcher(Protocol):
    """Optional matcher contract for durable partition-by-partition output."""

    def iter_partition_results(
        self,
        context: ReconciliationExecutionContext,
        *,
        completed_partition_keys: frozenset[str] = frozenset(),
    ) -> Iterable[ReconciliationPartitionResult]:
        """Yield output partitions while skipping already committed checkpoints."""


class LocalDeterministicMatcherAdapter:
    """Adapt the deterministic matcher to canonical hosted records.

    The matcher has no local database dependency. Hosted inputs, checkpoints,
    results, exceptions, audit events, and outbox events remain exclusively in
    the PostgreSQL worker boundary. Rules may opt into hard-key partitioning;
    the adapter never infers partitions.
    """

    def __init__(self) -> None:
        self._engine = DeterministicMatchingEngine(self._currency_precision)

    @staticmethod
    def _currency_precision(currency_code: str) -> tuple[int | None, str | None]:
        try:
            return CurrencyRegistry.get_precision(currency_code), None
        except InvalidAmountError:
            return None, "UNKNOWN_CURRENCY"

    @staticmethod
    def _json_object(value: object, field_name: str) -> dict[str, Any]:
        decoders = {
            "attributes_json": decode_postgres_reconciliation_attributes,
            "lineage": decode_postgres_reconciliation_lineage,
            "evidence": decode_postgres_reconciliation_evidence,
            "rule_json": decode_postgres_reconciliation_rule,
        }
        try:
            return decoders[field_name](value).payload
        except (KeyError, PersistedJsonError) as exc:
            raise PostgresReconciliationWorkerError(f"Stored {field_name} is invalid.") from exc

    @classmethod
    def _canonical_record(
        cls, record: Mapping[str, Any], *, id_field: str, amount_field: str, date_field: str, reference_field: str
    ) -> dict[str, Any]:
        attributes = cls._json_object(record.get("attributes_json", {}), "attributes_json")
        source_id = str(record.get("source_id", "")).strip()
        attributes.setdefault("id", source_id)
        attributes.setdefault(id_field, source_id)
        attributes.setdefault("source_id", source_id)
        attributes.setdefault("currency_code", str(record.get("currency_code", "") or ""))
        attributes.setdefault(
            amount_field,
            record.get("amount_decimal")
            if record.get("amount_decimal") is not None
            else record.get("amount_original", ""),
        )
        attributes.setdefault(
            date_field,
            record.get("date_value") if record.get("date_value") is not None else record.get("date_original", ""),
        )
        attributes.setdefault(
            reference_field, record.get("reference_normalized") or record.get("reference_original", "")
        )
        attributes.setdefault("amount_original", record.get("amount_original", ""))
        attributes["valid"] = bool(record.get("valid", True))
        return attributes

    @staticmethod
    def _partition_fields(rule: Mapping[str, Any]) -> tuple[str, ...]:
        value = rule.get("partition_fields", ())
        if isinstance(value, str):
            fields = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            fields = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise PostgresReconciliationWorkerError("partition_fields must be a comma-separated string or a list.")
        if len(fields) > 8:
            raise PostgresReconciliationWorkerError("partition_fields supports at most 8 fields.")
        if len(set(fields)) != len(fields) or any(len(field) > 128 for field in fields):
            raise PostgresReconciliationWorkerError(
                "partition_fields must contain unique names of at most 128 characters."
            )
        return tuple(fields)

    @staticmethod
    def _partition_limit(rule: Mapping[str, Any]) -> int:
        value = rule.get("partition_max_records", 10_000)
        if isinstance(value, bool):
            raise PostgresReconciliationWorkerError("partition_max_records must be an integer.")
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise PostgresReconciliationWorkerError("partition_max_records must be an integer.") from exc
        if not 1 <= limit <= 100_000:
            raise PostgresReconciliationWorkerError("partition_max_records must be between 1 and 100000.")
        return limit

    @staticmethod
    def _partition_key(record: Mapping[str, Any], fields: Sequence[str]) -> str:
        values = [record.get(field) for field in fields]
        return _stable_partition_key(values)

    @staticmethod
    def _stable_record_key(record: Mapping[str, object]) -> str:
        return json.dumps(dict(record), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _partition_output(
        cls,
        records: Sequence[Mapping[str, object]],
        fields: Sequence[str],
        *,
        add_lineage: bool = True,
        partition_key: str = "",
    ) -> tuple[dict[str, object], ...]:
        decorated: list[dict[str, object]] = []
        for record in records:
            item = {str(key): value for key, value in record.items()}
            if add_lineage:
                lineage = cls._json_object(item.get("lineage", {}), "lineage")
                lineage["partition_fields"] = list(fields)
                if partition_key:
                    lineage["partition_key"] = partition_key
                item["lineage"] = lineage
            elif partition_key:
                evidence = cls._json_object(item.get("evidence", {}), "evidence")
                evidence["partition_fields"] = list(fields)
                evidence["partition_key"] = partition_key
                item["evidence"] = evidence
            decorated.append(item)
        decorated.sort(key=cls._stable_record_key)
        return tuple(decorated)

    def _match_records(
        self,
        *,
        context: ReconciliationExecutionContext,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: str,
        rule: Mapping[str, Any],
    ) -> ReconciliationExecutionResult:
        output = self._engine.match_records(
            left_records=left_records,
            right_records=right_records,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=rule.get("amount_tolerance", "0"),
            date_window_days=int(rule.get("date_window_days", 0)),
            allow_many_to_one=bool(rule.get("allow_many_to_one", False)),
            allow_one_to_many=bool(rule.get("allow_one_to_many", False)),
            allow_many_to_many=bool(rule.get("allow_many_to_many", False)),
            financial_input_policy=cast(
                FinancialInputPolicy,
                rule.get("financial_input_policy", LEGACY_FINANCIAL_INPUT_POLICY),
            ),
            record_identity_policy=str(
                rule.get("record_identity_policy", LEGACY_RECORD_IDENTITY_POLICY),
            ),
        )
        return ReconciliationExecutionResult(results=output.results, exceptions=output.exceptions)

    def _prepared_records(
        self,
        context: ReconciliationExecutionContext,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, list[dict[str, Any]], list[dict[str, Any]]]:
        rule = self._json_object(context.run.get("rule_json", {}), "rule_json")
        amount_field = str(rule.get("amount_field", "amount"))
        date_field = str(rule.get("date_field", "date"))
        reference_field = str(rule.get("reference_field", "reference"))
        exact_fields_value = rule.get("exact_fields", [])
        exact_fields = (
            ",".join(str(value) for value in exact_fields_value)
            if isinstance(exact_fields_value, Sequence) and not isinstance(exact_fields_value, (str, bytes))
            else str(exact_fields_value or "")
        )
        left_records = [
            self._canonical_record(
                record,
                id_field="id",
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
            )
            for record in context.left_inputs
        ]
        right_records = [
            self._canonical_record(
                record,
                id_field="id",
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
            )
            for record in context.right_inputs
        ]
        return (
            rule,
            {"amount_field": amount_field},
            {"date_field": date_field, "reference_field": reference_field},
            exact_fields,
            left_records,
            right_records,
        )

    def iter_partition_results(
        self,
        context: ReconciliationExecutionContext,
        *,
        completed_partition_keys: frozenset[str] = frozenset(),
    ) -> Iterable[ReconciliationPartitionResult]:
        """Yield bounded partition outputs, skipping durable checkpoints."""

        rule, fields_config, date_config, exact_fields, left_records, right_records = self._prepared_records(context)
        partition_fields = self._partition_fields(rule)
        if not partition_fields:
            raise PostgresReconciliationWorkerError("Resumable partition execution requires partition_fields.")
        amount_field = str(fields_config["amount_field"])
        date_field = str(date_config["date_field"])
        reference_field = str(date_config["reference_field"])
        if context.partition_supplier is not None:
            maximum = self._partition_limit(rule)
            for streamed_partition in context.partition_supplier():
                context.raise_if_cancelled()
                if streamed_partition.input_count > maximum:
                    raise PostgresReconciliationWorkerError(
                        f"Partition {streamed_partition.partition_key[:16]} exceeds "
                        f"partition_max_records={maximum}; refine the hard partition fields."
                    )
                if streamed_partition.partition_key in completed_partition_keys:
                    continue
                left_records = [
                    self._canonical_record(
                        record,
                        id_field="id",
                        amount_field=amount_field,
                        date_field=date_field,
                        reference_field=reference_field,
                    )
                    for record in streamed_partition.left_inputs
                ]
                right_records = [
                    self._canonical_record(
                        record,
                        id_field="id",
                        amount_field=amount_field,
                        date_field=date_field,
                        reference_field=reference_field,
                    )
                    for record in streamed_partition.right_inputs
                ]
                context.heartbeat(10)
                output = self._match_records(
                    context=context,
                    left_records=left_records,
                    right_records=right_records,
                    amount_field=amount_field,
                    date_field=date_field,
                    reference_field=reference_field,
                    exact_fields=exact_fields,
                    rule=rule,
                )
                yield ReconciliationPartitionResult(
                    partition_key=streamed_partition.partition_key,
                    input_count=streamed_partition.input_count,
                    results=self._partition_output(
                        output.results, partition_fields, partition_key=streamed_partition.partition_key
                    ),
                    exceptions=self._partition_output(
                        output.exceptions,
                        partition_fields,
                        add_lineage=False,
                        partition_key=streamed_partition.partition_key,
                    ),
                )
            context.heartbeat(95)
            return
        partitions: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for side, records in (("left", left_records), ("right", right_records)):
            for record in records:
                key = self._partition_key(record, partition_fields)
                partitions.setdefault(key, {"left": [], "right": []})[side].append(record)
        maximum = self._partition_limit(rule)
        ordered_keys = sorted(partitions)
        total = max(len(ordered_keys), 1)
        for position, key in enumerate(ordered_keys):
            context.raise_if_cancelled()
            partition = partitions[key]
            if len(partition["left"]) + len(partition["right"]) > maximum:
                raise PostgresReconciliationWorkerError(
                    f"Partition {key[:16]} exceeds partition_max_records={maximum}; refine the hard partition fields."
                )
            context.heartbeat(min(94, max(1, int(position * 90 / total))))
            if key in completed_partition_keys:
                continue
            output = self._match_records(
                context=context,
                left_records=partition["left"],
                right_records=partition["right"],
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=exact_fields,
                rule=rule,
            )
            yield ReconciliationPartitionResult(
                partition_key=key,
                input_count=len(partition["left"]) + len(partition["right"]),
                results=self._partition_output(output.results, partition_fields, partition_key=key),
                exceptions=self._partition_output(
                    output.exceptions,
                    partition_fields,
                    add_lineage=False,
                    partition_key=key,
                ),
            )
        context.heartbeat(95)

    def close(self) -> None:
        """Retain the historical lifecycle hook; the pure engine owns no resource."""

    def __call__(self, context: ReconciliationExecutionContext) -> ReconciliationExecutionResult:
        rule, fields_config, date_config, exact_fields, left_records, right_records = self._prepared_records(context)
        amount_field = str(fields_config["amount_field"])
        date_field = str(date_config["date_field"])
        reference_field = str(date_config["reference_field"])
        partition_fields = self._partition_fields(rule)
        context.raise_if_cancelled()
        if not partition_fields:
            context.heartbeat(50)
            output = self._match_records(
                context=context,
                left_records=left_records,
                right_records=right_records,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=exact_fields,
                rule=rule,
            )
            context.heartbeat(95)
            return output

        parts = tuple(self.iter_partition_results(context))
        results = [record for part in parts for record in part.results]
        exceptions = [record for part in parts for record in part.exceptions]
        results.sort(key=self._stable_record_key)
        exceptions.sort(key=self._stable_record_key)
        context.heartbeat(95)
        return ReconciliationExecutionResult(results=tuple(results), exceptions=tuple(exceptions))


@dataclass(frozen=True)
class PostgresReconciliationWorkerSettings:
    """Bounded worker polling, lease, and batch settings."""

    worker_id: str
    poll_interval_seconds: float = 5.0
    batch_size: int = 10
    lease_seconds: int = 300
    actor_id: str = ""
    policy_context_supplier: Callable[[str], PolicyEvaluationContext] | None = None
    policy_permission: str = "match.run"

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or len(self.worker_id.strip()) > 160:
            raise PostgresReconciliationWorkerError("worker_id must be a non-empty value of at most 160 characters.")
        if self.poll_interval_seconds < 0:
            raise PostgresReconciliationWorkerError("poll_interval_seconds cannot be negative.")
        if not 1 <= self.batch_size <= 1_000:
            raise PostgresReconciliationWorkerError("batch_size must be between 1 and 1000.")
        if not 1 <= self.lease_seconds <= 86_400:
            raise PostgresReconciliationWorkerError("lease_seconds is outside its supported range.")
        if not self.policy_permission.strip():
            raise PostgresReconciliationWorkerError("policy_permission must be non-empty when configured.")

    @property
    def audit_actor_id(self) -> str:
        """Return the non-empty service actor used for audit events."""

        return self.actor_id.strip() or self.worker_id.strip()


@dataclass(frozen=True)
class ReconciliationProcessResult:
    """Outcome of one claimed run."""

    tenant_id: str
    run_id: str
    status: str
    result_count: int = 0
    exception_count: int = 0


@dataclass(frozen=True)
class ReconciliationWorkerRunSummary:
    """Aggregate bounded worker outcomes."""

    cycles: int
    discovered: int
    completed: int
    failed: int
    cancelled: int
    skipped: int

    @classmethod
    def empty(cls) -> ReconciliationWorkerRunSummary:
        return cls(cycles=0, discovered=0, completed=0, failed=0, cancelled=0, skipped=0)

    def add(
        self, *, discovered: int, results: Sequence[ReconciliationProcessResult], skipped: int
    ) -> ReconciliationWorkerRunSummary:
        return ReconciliationWorkerRunSummary(
            cycles=self.cycles + 1,
            discovered=self.discovered + discovered,
            completed=self.completed + sum(result.status == "Complete" for result in results),
            failed=self.failed + sum(result.status == "Failed" for result in results),
            cancelled=self.cancelled + sum(result.status == "Cancelled" for result in results),
            skipped=self.skipped + skipped,
        )


class PostgresReconciliationSchedulerError(RuntimeError):
    """Raised when the multi-worker scheduler cannot safely coordinate a cycle."""


class PostgresReconciliationScheduler:
    """Run multiple durable reconciliation workers in one deployment process.

    PostgreSQL leases remain the source of truth for ownership. Each worker has
    its own stable worker ID and connection factory, so concurrent scheduler
    slots cannot persist the same run twice even when tenant enumeration
    overlaps. A deployment may instead run each worker in a separate process;
    this class provides the equivalent bounded in-process runtime for local
    orchestration and controlled deployments.
    """

    def __init__(
        self,
        worker_factory: Callable[[str], PostgresReconciliationWorker],
        *,
        worker_ids: Iterable[str],
        poll_interval_seconds: float = 5.0,
    ) -> None:
        identifiers = tuple(sorted({str(value).strip() for value in worker_ids if str(value).strip()}))
        if not identifiers or len(identifiers) > 64:
            raise PostgresReconciliationSchedulerError("worker_ids must contain between 1 and 64 non-empty IDs.")
        if any(len(identifier) > 160 for identifier in identifiers):
            raise PostgresReconciliationSchedulerError("worker IDs must be at most 160 characters.")
        if poll_interval_seconds < 0:
            raise PostgresReconciliationSchedulerError("poll_interval_seconds cannot be negative.")
        self.worker_factory = worker_factory
        self.worker_ids = identifiers
        self.poll_interval_seconds = float(poll_interval_seconds)

    def process_once(self) -> ReconciliationWorkerRunSummary:
        """Execute one bounded cycle per worker and aggregate outcomes."""

        try:
            with ThreadPoolExecutor(
                max_workers=len(self.worker_ids), thread_name_prefix="reconforge-reconciliation"
            ) as pool:
                futures = [pool.submit(self.worker_factory(worker_id).process_once) for worker_id in self.worker_ids]
                cycles = [future.result() for future in futures]
        except PostgresReconciliationSchedulerError:
            raise
        except Exception as exc:  # noqa: BLE001 - scheduler failures must stop safely.
            raise PostgresReconciliationSchedulerError("A reconciliation scheduler cycle failed safely.") from exc
        return ReconciliationWorkerRunSummary(
            cycles=sum(item.cycles for item in cycles),
            discovered=sum(item.discovered for item in cycles),
            completed=sum(item.completed for item in cycles),
            failed=sum(item.failed for item in cycles),
            cancelled=sum(item.cancelled for item in cycles),
            skipped=sum(item.skipped for item in cycles),
        )

    def run(self, *, stop_event: Event | None = None, max_cycles: int | None = None) -> ReconciliationWorkerRunSummary:
        """Poll all configured workers until stopped or a bounded cycle count is reached."""

        if max_cycles is not None and max_cycles < 1:
            raise PostgresReconciliationSchedulerError("max_cycles must be positive when supplied.")
        event = stop_event or Event()
        summary = ReconciliationWorkerRunSummary.empty()
        while not event.is_set() and (max_cycles is None or summary.cycles < max_cycles * len(self.worker_ids)):
            cycle = self.process_once()
            summary = ReconciliationWorkerRunSummary(
                cycles=summary.cycles + cycle.cycles,
                discovered=summary.discovered + cycle.discovered,
                completed=summary.completed + cycle.completed,
                failed=summary.failed + cycle.failed,
                cancelled=summary.cancelled + cycle.cancelled,
                skipped=summary.skipped + cycle.skipped,
            )
            if max_cycles is not None and summary.cycles >= max_cycles * len(self.worker_ids):
                break
            event.wait(self.poll_interval_seconds)
        return summary


class PostgresReconciliationWorker:
    """Claim, execute, and persist PostgreSQL reconciliation runs safely.

    The matcher is deliberately injected.  This worker owns leases, fresh
    connection boundaries, cancellation, retries, and atomic persistence; it does not
    pretend that a local SQLite matcher is a PostgreSQL execution engine.
    """

    _RESULT_FIELDS = frozenset(
        {
            "left_id",
            "right_id",
            "match_type",
            "confidence",
            "explanation",
            "amount_difference",
            "date_difference_days",
            "status",
            "reason_code",
            "lineage",
        }
    )
    _EXCEPTION_FIELDS = frozenset(
        {
            "exception_type",
            "source_side",
            "source_id",
            "title",
            "explanation",
            "severity",
            "risk_score",
            "reason_code",
            "owner_id",
            "evidence",
        }
    )

    def __init__(
        self,
        connection_factory: Any,
        *,
        tenant_supplier: Callable[[], Iterable[str]],
        matcher: ReconciliationMatcher,
        settings: PostgresReconciliationWorkerSettings,
    ) -> None:
        self.connection_factory = connection_factory
        self.tenant_supplier = tenant_supplier
        self.matcher = matcher
        self.settings = settings
        self.policy = CentralPolicyEngine()

    def _authorize_tenant(self, tenant_id: str, *, request_id: str = "") -> None:
        """Optionally require a central service-account decision before reads/claims."""

        supplier = self.settings.policy_context_supplier
        if supplier is None:
            return
        try:
            context = supplier(tenant_id)
        except Exception as exc:  # noqa: BLE001 - worker boundary adds safe context.
            raise PostgresReconciliationWorkerError("Unable to resolve worker policy context safely.") from exc
        if context.principal_type != "service_account":
            raise PostgresReconciliationWorkerError("Reconciliation workers require a service-account principal.")
        if context.user_id != self.settings.audit_actor_id:
            raise PostgresReconciliationWorkerError("Worker actor does not match policy identity.")
        if context.tenant_id != tenant_id or context.workspace_id is not None or context.entity_id is not None:
            raise PostgresReconciliationWorkerError("Worker policy scope does not match tenant claim scope.")
        decision = self.policy.evaluate(
            context,
            required_permission=self.settings.policy_permission.strip(),
            enforce_sod=False,
            enforce_ownership=False,
        )
        audit_policy_decision(
            decision,
            actor_id=context.user_id,
            required_permissions=frozenset({self.settings.policy_permission.strip()}),
            surface="postgres-reconciliation.worker.claim",
            request_id=request_id,
            principal_type=context.principal_type,
        )
        if not decision.allowed:
            raise PostgresReconciliationWorkerError(f"Reconciliation worker policy denied: {decision.reason_code}")

    def _transaction(self) -> PostgresTenantBoundary:
        return PostgresTenantBoundary(self.connection_factory)

    def _cancel_requested(self, tenant_id: str, run_id: str) -> bool:
        with self._transaction().transaction(tenant_id) as connection:
            record = PostgresReconciliationRepository(connection).get_run_metadata(tenant_id=tenant_id, run_id=run_id)
            return bool(record.get("cancel_requested", False))

    def _heartbeat(self, tenant_id: str, run_id: str, progress: int) -> Mapping[str, Any]:
        with self._transaction().transaction(tenant_id) as connection:
            return PostgresReconciliationRepository(connection).heartbeat_run(
                tenant_id=tenant_id,
                run_id=run_id,
                worker_id=self.settings.worker_id,
                progress=progress,
                lease_seconds=self.settings.lease_seconds,
            )

    @classmethod
    def _payload(cls, record: Mapping[str, object], allowed: frozenset[str], kind: str) -> dict[str, Any]:
        unknown = set(record).difference(allowed)
        if unknown:
            names = ", ".join(sorted(str(value) for value in unknown))
            raise PostgresReconciliationWorkerError(f"{kind} contains unsupported fields: {names}.")
        return {str(key): value for key, value in record.items()}

    def _persist_and_complete(
        self,
        *,
        tenant_id: str,
        run_id: str,
        execution: ReconciliationExecutionResult,
        request_id: str,
    ) -> ReconciliationProcessResult:
        with self._transaction().transaction(tenant_id) as connection:
            repository = PostgresReconciliationRepository(connection)
            metadata = repository.get_run_metadata(tenant_id=tenant_id, run_id=run_id)
            if bool(metadata.get("cancel_requested", False)):
                cancelled = repository.mark_cancelled(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    worker_id=self.settings.worker_id,
                    actor_id=self.settings.audit_actor_id,
                    request_id=request_id,
                    reason="Cancellation observed before result persistence.",
                )
                return ReconciliationProcessResult(
                    tenant_id, run_id, str(cancelled.get("execution_status", "Cancelled"))
                )
            for record in execution.results:
                values = self._payload(record, self._RESULT_FIELDS, "matcher result")
                repository.append_result(tenant_id=tenant_id, run_id=run_id, **values)
            for record in execution.exceptions:
                values = self._payload(record, self._EXCEPTION_FIELDS, "matcher exception")
                repository.append_exception(tenant_id=tenant_id, run_id=run_id, **values)
            completed = repository.complete_run(
                tenant_id=tenant_id,
                run_id=run_id,
                actor_id=self.settings.audit_actor_id,
                worker_id=self.settings.worker_id,
                request_id=request_id,
                reason="Deterministic matcher execution completed.",
            )
            return ReconciliationProcessResult(
                tenant_id=tenant_id,
                run_id=run_id,
                status=str(completed.get("execution_status", "Complete")),
                result_count=int(completed.get("result_count", 0) or 0),
                exception_count=int(completed.get("exception_count", 0) or 0),
            )

    def _persist_partition(
        self,
        *,
        tenant_id: str,
        run_id: str,
        partition: ReconciliationPartitionResult,
        request_id: str,
    ) -> None:
        """Commit one partition's output and checkpoint in one transaction."""

        with self._transaction().transaction(tenant_id) as connection:
            PostgresReconciliationRepository(connection).append_partition(
                tenant_id=tenant_id,
                run_id=run_id,
                partition_key=partition.partition_key,
                input_count=partition.input_count,
                results=partition.results,
                exceptions=partition.exceptions,
                worker_id=self.settings.worker_id,
                request_id=request_id,
                reason="Deterministic partition output committed for resumable execution.",
            )

    def _fail(self, tenant_id: str, run_id: str, error: str, request_id: str) -> ReconciliationProcessResult:
        with self._transaction().transaction(tenant_id) as connection:
            failed = PostgresReconciliationRepository(connection).fail_run(
                tenant_id=tenant_id,
                run_id=run_id,
                worker_id=self.settings.worker_id,
                actor_id=self.settings.audit_actor_id,
                error=error,
                request_id=request_id,
                reason="Matcher execution failed; run is retryable after explicit requeue.",
            )
            return ReconciliationProcessResult(tenant_id, run_id, str(failed.get("execution_status", "Failed")))

    @staticmethod
    def _rule_mapping(run: Mapping[str, Any]) -> dict[str, Any]:
        """Decode a JSONB rule returned as either a mapping or JSON text."""

        try:
            return decode_postgres_reconciliation_rule(run.get("rule_json", {})).payload
        except PersistedJsonError as exc:
            raise PostgresReconciliationWorkerError("Stored reconciliation rule is invalid.") from exc

    def _stream_input_supplier(
        self,
        *,
        tenant_id: str,
        run_id: str,
        rule: Mapping[str, Any],
    ) -> Callable[[], Iterable[ReconciliationInputPartition]]:
        """Create a lazy tenant-scoped server-cursor partition supplier."""

        raw_fields = rule.get("partition_fields", ())
        if isinstance(raw_fields, str):
            fields = tuple(item.strip() for item in raw_fields.split(",") if item.strip())
        elif isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes, bytearray)):
            fields = tuple(str(item).strip() for item in raw_fields if str(item).strip())
        else:
            raise PostgresReconciliationWorkerError("partition_fields must be a comma-separated string or a list.")
        if not 1 <= len(fields) <= 8 or len(set(fields)) != len(fields):
            raise PostgresReconciliationWorkerError("partition_fields must contain between 1 and 8 unique names.")
        amount_field = str(rule.get("amount_field", "amount"))
        date_field = str(rule.get("date_field", "date"))
        reference_field = str(rule.get("reference_field", "reference"))

        def supplier() -> Iterable[ReconciliationInputPartition]:
            with self._transaction().transaction(tenant_id) as connection:
                repository = PostgresReconciliationRepository(connection)
                for values, left_records, right_records in repository.iter_input_partitions(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    partition_fields=fields,
                    amount_field=amount_field,
                    date_field=date_field,
                    reference_field=reference_field,
                ):
                    yield ReconciliationInputPartition(
                        partition_key=_stable_partition_key(values),
                        left_inputs=left_records,
                        right_inputs=right_records,
                    )

        return supplier

    def process_run(self, *, tenant_id: str, run_id: str, request_id: str = "") -> ReconciliationProcessResult:
        """Claim and execute one run using fresh connections for each phase."""

        self._authorize_tenant(tenant_id, request_id=request_id)
        try:
            with self._transaction().transaction(tenant_id) as connection:
                repository = PostgresReconciliationRepository(connection)
                claimed = repository.claim_run(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    worker_id=self.settings.worker_id,
                    lease_seconds=self.settings.lease_seconds,
                )
                rule = self._rule_mapping(claimed)
                partition_fields = rule.get("partition_fields", ())
                if partition_fields:
                    left_inputs: tuple[Mapping[str, Any], ...] = ()
                    right_inputs: tuple[Mapping[str, Any], ...] = ()
                else:
                    inputs = repository.list_inputs(tenant_id=tenant_id, run_id=run_id)
                    left_inputs = tuple(record for record in inputs if str(record.get("side", "")) == "Left")
                    right_inputs = tuple(record for record in inputs if str(record.get("side", "")) == "Right")
            partition_supplier = (
                self._stream_input_supplier(tenant_id=tenant_id, run_id=run_id, rule=rule) if partition_fields else None
            )
            context = ReconciliationExecutionContext(
                run=claimed,
                left_inputs=left_inputs,
                right_inputs=right_inputs,
                heartbeat=lambda progress: self._heartbeat(tenant_id, run_id, progress),
                cancellation_requested=lambda: self._cancel_requested(tenant_id, run_id),
                partition_supplier=partition_supplier,
            )
            context.raise_if_cancelled()
            partitioned_matcher = getattr(self.matcher, "iter_partition_results", None)
            if partition_fields and callable(partitioned_matcher):
                with self._transaction().transaction(tenant_id) as connection:
                    checkpoints = PostgresReconciliationRepository(connection).list_checkpoints(
                        tenant_id=tenant_id,
                        run_id=run_id,
                    )
                completed_keys = frozenset(str(item["partition_key"]) for item in checkpoints)
                for partition in partitioned_matcher(
                    context,
                    completed_partition_keys=completed_keys,
                ):
                    if not isinstance(partition, ReconciliationPartitionResult):
                        raise PostgresReconciliationWorkerError(
                            "Partition matcher must yield ReconciliationPartitionResult values."
                        )
                    self._persist_partition(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        partition=partition,
                        request_id=request_id,
                    )
                return self._persist_and_complete(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    execution=ReconciliationExecutionResult(),
                    request_id=request_id,
                )
            execution = self.matcher(context)
            if not isinstance(execution, ReconciliationExecutionResult):
                raise PostgresReconciliationWorkerError("Matcher must return ReconciliationExecutionResult.")
            return self._persist_and_complete(
                tenant_id=tenant_id,
                run_id=run_id,
                execution=execution,
                request_id=request_id,
            )
        except ReconciliationCancellationRequested:
            with self._transaction().transaction(tenant_id) as connection:
                cancelled = PostgresReconciliationRepository(connection).mark_cancelled(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    worker_id=self.settings.worker_id,
                    actor_id=self.settings.audit_actor_id,
                    request_id=request_id,
                    reason="Matcher observed cooperative cancellation.",
                )
            return ReconciliationProcessResult(tenant_id, run_id, str(cancelled.get("execution_status", "Cancelled")))
        except PostgresReconciliationBusyError:
            raise
        except Exception as exc:  # noqa: BLE001 - failure is persisted and surfaced as a retryable run state.
            try:
                return self._fail(tenant_id, run_id, str(exc), request_id)
            except Exception as failure_exc:  # noqa: BLE001 - preserve both operational failures.
                raise PostgresReconciliationWorkerError(
                    "Unable to persist reconciliation execution failure."
                ) from failure_exc

    def process_once(self, *, request_id: str = "") -> ReconciliationWorkerRunSummary:
        """Discover a bounded active page per tenant and process claimable runs."""

        try:
            tenants = sorted({str(value).strip() for value in self.tenant_supplier() if str(value).strip()})
        except Exception as exc:
            raise PostgresReconciliationWorkerError("Unable to enumerate reconciliation tenants.") from exc
        outcomes: list[ReconciliationProcessResult] = []
        skipped = 0
        discovered = 0
        for tenant_id in tenants:
            self._authorize_tenant(tenant_id, request_id=request_id)
            with self._transaction().transaction(tenant_id) as connection:
                runs = PostgresReconciliationRepository(connection).list_runs(
                    tenant_id=tenant_id,
                    execution_status="active",
                    limit=self.settings.batch_size,
                )
            discovered += len(runs)
            for run in runs:
                try:
                    outcomes.append(
                        self.process_run(
                            tenant_id=tenant_id,
                            run_id=str(run["id"]),
                            request_id=request_id,
                        )
                    )
                except PostgresReconciliationBusyError:
                    skipped += 1
        return ReconciliationWorkerRunSummary.empty().add(
            discovered=discovered,
            results=outcomes,
            skipped=skipped,
        )

    def run(self, *, stop_event: Event | None = None, max_cycles: int | None = None) -> ReconciliationWorkerRunSummary:
        """Poll until stopped or an optional bounded cycle count is reached."""

        if max_cycles is not None and max_cycles < 1:
            raise PostgresReconciliationWorkerError("max_cycles must be positive when supplied.")
        event = stop_event or Event()
        summary = ReconciliationWorkerRunSummary.empty()
        while not event.is_set() and (max_cycles is None or summary.cycles < max_cycles):
            cycle = self.process_once()
            summary = ReconciliationWorkerRunSummary(
                cycles=summary.cycles + cycle.cycles,
                discovered=summary.discovered + cycle.discovered,
                completed=summary.completed + cycle.completed,
                failed=summary.failed + cycle.failed,
                cancelled=summary.cancelled + cycle.cancelled,
                skipped=summary.skipped + cycle.skipped,
            )
            if max_cycles is not None and summary.cycles >= max_cycles:
                break
            event.wait(self.settings.poll_interval_seconds)
        return summary
