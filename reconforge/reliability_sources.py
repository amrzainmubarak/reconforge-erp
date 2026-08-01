"""Local operational measurement sources with explicit unavailable-state reporting."""

from __future__ import annotations

import sqlite3
import sys
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from reconforge.audit import AuditLedgerError, verify_audit_events
from reconforge.infrastructure.postgres import ConnectionFactory, PostgresTenantBoundary, validate_tenant_id
from reconforge.infrastructure.postgres_ledger import PostgresLedgerRepository
from reconforge.reliability import MetricKey


@dataclass(frozen=True)
class MeasurementSnapshot:
    values: Mapping[MetricKey, int]
    unavailable_sources: tuple[str, ...]


class HttpReliabilityWindow:
    """Bounded in-process request window using exact integer calculations."""

    def __init__(self, *, capacity: int = 10_000) -> None:
        if capacity < 1 or capacity > 1_000_000:
            raise ValueError("HTTP reliability capacity is invalid")
        self._samples: deque[tuple[int, int]] = deque(maxlen=capacity)
        self._lock = Lock()

    def record(self, *, status_code: int, duration_ms: int) -> None:
        if status_code < 100 or status_code > 599 or duration_ms < 0 or duration_ms > 86_400_000:
            raise ValueError("HTTP reliability sample is invalid")
        with self._lock:
            self._samples.append((status_code, duration_ms))

    def measurements(self) -> Mapping[MetricKey, int]:
        with self._lock:
            samples = tuple(self._samples)
        if not samples:
            return {}
        errors = sum(1 for status, _ in samples if status >= 500)
        durations = sorted(duration for _, duration in samples)
        percentile_index = (95 * len(durations) + 99) // 100 - 1
        return {
            MetricKey.HTTP_ERROR_BPS: errors * 10_000 // len(samples),
            MetricKey.HTTP_P95_MS: durations[percentile_index],
        }


def process_memory_mib() -> int:
    """Read process resident memory with standard-library platform APIs."""

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory = psapi.GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        get_memory.restype = wintypes.BOOL
        if not get_memory(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("unable to read process memory")
        resident_bytes = int(counters.WorkingSetSize)
    else:
        import resource

        maximum_resident = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        resident_bytes = maximum_resident if sys.platform == "darwin" else maximum_resident * 1_024
    return (resident_bytes + 1_048_575) // 1_048_576


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(UTC)


class SQLiteReliabilityCollector:
    """Collect aggregate local signals without returning business identifiers."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        http_window: HttpReliabilityWindow | None = None,
        dependency_probes: tuple[Callable[[], bool], ...] = (),
        memory_mib: Callable[[], int] | None = None,
    ) -> None:
        self._connection = connection
        self._http_window = http_window
        self._dependency_probes = dependency_probes
        self._memory_mib = memory_mib

    def collect(self, *, observed_at: datetime) -> MeasurementSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("reliability observation time must include a timezone")
        now = observed_at.astimezone(UTC)
        values: dict[MetricKey, int] = {}
        unavailable: list[str] = []
        if self._http_window is None:
            unavailable.append("http_window")
        else:
            http_values = self._http_window.measurements()
            values.update(http_values)
            if not http_values:
                unavailable.append("http_window")
        try:
            row = self._connection.execute(
                "SELECT COUNT(*), MIN(created_at) FROM durable_jobs WHERE status IN ('queued', 'retrying')"
            ).fetchone()
            count = int(row[0])
            values[MetricKey.QUEUE_DEPTH] = count
            if count == 0:
                values[MetricKey.OLDEST_JOB_AGE_SECONDS] = 0
            else:
                age = int((now - _parse_utc(str(row[1]))).total_seconds())
                if age < 0:
                    raise ValueError("queued job timestamp is in the future")
                values[MetricKey.OLDEST_JOB_AGE_SECONDS] = age
        except (sqlite3.DatabaseError, TypeError, ValueError, OverflowError):
            unavailable.append("durable_jobs")
        try:
            values[MetricKey.AUDIT_FAILURES] = len(verify_audit_events(self._connection).issues)
        except AuditLedgerError:
            unavailable.append("audit_ledger")
        failures = 0
        for probe in self._dependency_probes:
            try:
                failures += 0 if probe() is True else 1
            except Exception:  # dependency adapters must not break the collector
                failures += 1
        values[MetricKey.DEPENDENCY_FAILURES] = failures
        if self._memory_mib is None:
            unavailable.append("process_memory")
        else:
            try:
                memory = self._memory_mib()
                if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0 or memory > 10**12:
                    raise ValueError("invalid memory measurement")
                values[MetricKey.PROCESS_MEMORY_MIB] = memory
            except (RuntimeError, OSError, ValueError):
                unavailable.append("process_memory")
        return MeasurementSnapshot(values, tuple(sorted(set(unavailable))))


class PostgresReliabilityCollector:
    """Collect tenant-scoped server aggregates through forced-RLS transactions."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        tenant_id: str,
        http_window: HttpReliabilityWindow | None = None,
        dependency_probes: tuple[Callable[[], bool], ...] = (),
        memory_mib: Callable[[], int] | None = None,
    ) -> None:
        self._boundary = PostgresTenantBoundary(connection_factory)
        self._tenant_id = validate_tenant_id(tenant_id)
        self._http_window = http_window
        self._dependency_probes = dependency_probes
        self._memory_mib = memory_mib

    def collect(self, *, observed_at: datetime) -> MeasurementSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("reliability observation time must include a timezone")
        now = observed_at.astimezone(UTC)
        values: dict[MetricKey, int] = {}
        unavailable: list[str] = []
        if self._http_window is None:
            unavailable.append("http_window")
        else:
            http_values = self._http_window.measurements()
            values.update(http_values)
            if not http_values:
                unavailable.append("http_window")
        try:
            with self._boundary.transaction(self._tenant_id) as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*), MIN(created_at)
                    FROM reconforge.durable_jobs
                    WHERE tenant_id = %s AND status IN ('queued', 'retrying')
                    """,
                    (self._tenant_id,),
                ).fetchone()
                count = int(row[0])
                values[MetricKey.QUEUE_DEPTH] = count
                if count == 0:
                    values[MetricKey.OLDEST_JOB_AGE_SECONDS] = 0
                else:
                    created_at = row[1]
                    oldest = created_at if isinstance(created_at, datetime) else _parse_utc(str(created_at))
                    if oldest.tzinfo is None or oldest.utcoffset() is None:
                        raise ValueError("stored PostgreSQL job timestamp has no timezone")
                    age = int((now - oldest.astimezone(UTC)).total_seconds())
                    if age < 0:
                        raise ValueError("queued job timestamp is in the future")
                    values[MetricKey.OLDEST_JOB_AGE_SECONDS] = age
                verification = PostgresLedgerRepository(connection).verify_audit_events(tenant_id=self._tenant_id)
                values[MetricKey.AUDIT_FAILURES] = len(verification["issues"])
        except Exception:  # optional driver errors are normalized without leaking DSNs or SQL details
            values.pop(MetricKey.QUEUE_DEPTH, None)
            values.pop(MetricKey.OLDEST_JOB_AGE_SECONDS, None)
            values.pop(MetricKey.AUDIT_FAILURES, None)
            unavailable.extend(("durable_jobs", "audit_ledger"))
        failures = 0
        for probe in self._dependency_probes:
            try:
                failures += 0 if probe() is True else 1
            except Exception:
                failures += 1
        values[MetricKey.DEPENDENCY_FAILURES] = failures
        if self._memory_mib is None:
            unavailable.append("process_memory")
        else:
            try:
                memory = self._memory_mib()
                if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0 or memory > 10**12:
                    raise ValueError("invalid memory measurement")
                values[MetricKey.PROCESS_MEMORY_MIB] = memory
            except (RuntimeError, OSError, ValueError):
                unavailable.append("process_memory")
        return MeasurementSnapshot(values, tuple(sorted(set(unavailable))))
