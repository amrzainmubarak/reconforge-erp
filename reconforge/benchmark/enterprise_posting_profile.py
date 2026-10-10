"""Opt-in client profiling of unchanged native posting and identity boundaries.

Only phase labels, statement-template digests, durations and exception types are
retained. SQL parameters, SQL text, identity credentials and financial rows are
never collected. Deferred server triggers are visible in actor-exit time; this
is not a server query profiler or an authorization/transaction shortcut.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class PostingProfile:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._observations: list[dict[str, Any]] = []
        self._sql: dict[str, dict[str, Any]] = {}

    def _phase(self, index: int, phase: str, started: float, failure: str | None = None) -> None:
        if self.enabled:
            with self._lock:
                self._observations.append({"index": index, "phase": phase,
                    "seconds": time.perf_counter() - started, "failure_type": failure})

    @contextmanager
    def actor(self, runtime: Any, username: str, index: int, phase: str) -> Iterator[tuple[Any, Any, Any]]:
        if not self.enabled:
            with runtime.actor(username) as values:
                yield values
            return
        started = time.perf_counter()
        entered = False
        exit_started = started
        failure: str | None = None
        try:
            with runtime.actor(username) as (connection, auth, actor):
                entered = True
                self._phase(index, phase + ".identity_enter", started)
                body_started = time.perf_counter()
                try:
                    yield _ProfiledConnection(connection, self, phase), auth, actor
                except Exception as exc:
                    failure = type(exc).__name__
                    raise
                finally:
                    self._phase(index, phase + ".business", body_started, failure)
                    exit_started = time.perf_counter()
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            self._phase(index, phase + (".transaction_exit" if entered else ".identity_enter"),
                        exit_started if entered else started, failure)

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
                row = phases.setdefault(observation["phase"], {"observations": 0, "seconds": 0.0, "failures": 0})
                row["observations"] += 1
                row["seconds"] += observation["seconds"]
                row["failures"] += int(observation["failure_type"] is not None)
            return {"enabled": self.enabled, "scope": "client identity entry, business calls and transaction exit; no server-internal timings",
                "raw_phase_observations": sorted(self._observations, key=lambda row: (row["index"], row["phase"])),
                "phase_totals": phases, "statement_templates": sorted(self._sql.values(), key=lambda row: -row["seconds"]),
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
