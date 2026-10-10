"""Opt-in client profiling of unchanged native posting and identity boundaries.

Only phase labels, statement-template digests, durations and exception types are
retained. SQL parameters, SQL text, identity credentials and financial rows are
never collected. Deferred server triggers are visible in actor-exit time; this
is not a server query profiler or an authorization/transaction shortcut.
"""
from __future__ import annotations

import cProfile
import hashlib
import pstats
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class PostingProfile:
    def __init__(self, enabled: bool = True, *, profile_cpu: bool = False) -> None:
        self.enabled = enabled
        self.profile_cpu = profile_cpu
        self._lock = threading.Lock()
        self._observations: list[dict[str, Any]] = []
        self._sql: dict[str, dict[str, Any]] = {}
        self._functions: dict[tuple[str, str, int, str], dict[str, Any]] = {}

    def _phase(self, index: int, phase: str, started: float, failure: str | None = None,
               cpu_started: float | None = None) -> None:
        if self.enabled:
            with self._lock:
                self._observations.append({"index": index, "phase": phase,
                    "seconds": time.perf_counter() - started, "failure_type": failure,
                    "thread_cpu_seconds": None if cpu_started is None else time.thread_time() - cpu_started})

    @contextmanager
    def actor(self, runtime: Any, username: str, index: int, phase: str) -> Iterator[tuple[Any, Any, Any]]:
        # Profile only the first32 cycles, separately per worker thread. Retain
        # code identifiers and counters, never arguments, locals or SQL content.
        profiler = cProfile.Profile() if self.enabled and self.profile_cpu and 0 <= index < 32 else None
        try:
            if profiler is not None:
                profiler.enable()
            with self._actor(runtime, username, index, phase) as values:
                yield values
        finally:
            if profiler is not None:
                profiler.disable()
                stats = pstats.Stats(profiler)
                with self._lock:
                    for (filename, line, function), (primitive, calls, own, cumulative, _callers) in getattr(stats, "stats").items():
                        key = (phase, filename, line, function)
                        row = self._functions.setdefault(key, {"phase": phase, "filename": filename,
                            "line": line, "function": function, "primitive_calls": 0, "calls": 0,
                            "self_seconds": 0.0, "cumulative_seconds": 0.0})
                        row["primitive_calls"] += primitive
                        row["calls"] += calls
                        row["self_seconds"] += own
                        row["cumulative_seconds"] += cumulative

    @contextmanager
    def _actor(self, runtime: Any, username: str, index: int, phase: str) -> Iterator[tuple[Any, Any, Any]]:
        if not self.enabled:
            with runtime.actor(username) as values:
                yield values
            return
        started = time.perf_counter()
        cpu_started = time.thread_time()
        entered = False
        exit_started = started
        exit_cpu = cpu_started
        failure: str | None = None
        try:
            with runtime.actor(username) as (connection, auth, actor):
                entered = True
                self._phase(index, phase + ".identity_enter", started, cpu_started=cpu_started)
                body_started = time.perf_counter()
                body_cpu = time.thread_time()
                try:
                    yield _ProfiledConnection(connection, self, phase), auth, actor
                except Exception as exc:
                    failure = type(exc).__name__
                    raise
                finally:
                    self._phase(index, phase + ".business", body_started, failure, body_cpu)
                    exit_started = time.perf_counter()
                    exit_cpu = time.thread_time()
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            self._phase(index, phase + (".transaction_exit" if entered else ".identity_enter"),
                        exit_started if entered else started, failure, exit_cpu if entered else cpu_started)

    def statement(self, query: Any, phase: str, started: float, failure: str | None) -> None:
        # Composed queries might contain literals. Hash their representation
        # rather than ever retaining SQL text; parameters are never inspected.
        fingerprint = hashlib.sha256(str(query).encode()).hexdigest()
        key = phase + ":" + fingerprint
        with self._lock:
            row = self._sql.setdefault(key, {"phase": phase, "statement_template_sha256": fingerprint,
                "calls": 0, "seconds": 0.0, "failures": 0})
            row["calls"] += 1
            row["seconds"] += time.perf_counter() - started
            row["failures"] += int(failure is not None)

    def report(self) -> dict[str, Any]:
        with self._lock:
            phases: dict[str, dict[str, Any]] = {}
            for observation in self._observations:
                row = phases.setdefault(observation["phase"], {"observations": 0, "seconds": 0.0,
                    "thread_cpu_seconds": 0.0, "failures": 0})
                row["observations"] += 1
                row["seconds"] += observation["seconds"]
                row["thread_cpu_seconds"] += observation["thread_cpu_seconds"] or 0.0
                row["failures"] += int(observation["failure_type"] is not None)
            return {"enabled": self.enabled, "scope": "client identity entry, business calls and transaction exit; no server-internal timings",
                "raw_phase_observations": sorted(self._observations, key=lambda row: (row["index"], row["phase"])),
                "phase_totals": phases, "statement_templates": sorted(self._sql.values(), key=lambda row: -row["seconds"]),
                "function_profile": {"enabled": self.enabled and self.profile_cpu, "cycle_ceiling": 32,
                    "timer_scope": "cProfile wall durations include blocking I/O; phase thread CPU excludes other workers",
                    "functions": sorted(self._functions.values(), key=lambda row: (-row["self_seconds"], row["phase"], row["filename"], row["line"]))},
                "sensitive_collection": "no SQL text, parameters, credentials, error messages or financial rows"}


class _ProfiledConnection:
    def __init__(self, connection: Any, profile: PostingProfile, phase: str) -> None:
        self._connection, self._profile, self._phase = connection, profile, phase

    def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        started, failure = time.perf_counter(), None
        try:
            return self._connection.execute(query, *args, **kwargs)
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            self._profile.statement(query, self._phase, started, failure)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)
