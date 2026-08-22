"""Prove bounded receiver-side write-back idempotency with durable SQLite state."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import sqlite3
import subprocess  # nosec B404 - fixed git metadata command below
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from reconforge.connectors.writeback_receiver import (
    SQLiteWritebackReceiverStore,
    WritebackReceiverDisposition,
    WritebackReceiverError,
    WritebackReceiverRequest,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIVER_SOURCE = ROOT / "reconforge/connectors/writeback_receiver.py"


class ReceiverDrillError(RuntimeError):
    """Raised when the bounded receiver conformance drill is not proven."""


class _ProcessLike(Protocol):
    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...


def _request(key: str, *, payload: bytes) -> WritebackReceiverRequest:
    return WritebackReceiverRequest(
        schema_version="writeback-receiver-request-v1",
        receiver_id="synthetic-provider",
        operation="payment.create",
        idempotency_key=key,
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


def _receive_worker(
    database: str,
    request_data: dict[str, Any],
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    start.wait(timeout=20)
    request = WritebackReceiverRequest.model_validate(request_data)
    result = SQLiteWritebackReceiverStore(Path(database)).receive(request)
    results.put((result.disposition.value, result.response.response_digest))


def _crash_after_commit(database: str, request_data: dict[str, Any]) -> None:
    request = WritebackReceiverRequest.model_validate(request_data)
    result = SQLiteWritebackReceiverStore(Path(database)).receive(request)
    if result.disposition is not WritebackReceiverDisposition.APPLIED:
        os._exit(91)
    os._exit(0)


def _join(process: _ProcessLike, *, label: str) -> None:
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        raise ReceiverDrillError(f"{label} timed out")
    if process.exitcode != 0:
        raise ReceiverDrillError(f"{label} failed with exit code {process.exitcode}")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _base_commit() -> str:
    completed = subprocess.run(  # nosec B603 - fixed executable and arguments
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _backup(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _immutability_checks(database: Path) -> tuple[bool, bool]:
    update_refused = False
    delete_refused = False
    connection = sqlite3.connect(database)
    try:
        try:
            connection.execute("UPDATE writeback_receiver_receipts SET operation = 'changed'")
        except sqlite3.IntegrityError as exc:
            update_refused = "receipt_immutable" in str(exc)
        connection.rollback()
        try:
            connection.execute("DELETE FROM writeback_receiver_effects")
        except sqlite3.IntegrityError as exc:
            delete_refused = "effect_immutable" in str(exc)
        connection.rollback()
    finally:
        connection.close()
    return update_refused, delete_refused


def run_drill(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    context = multiprocessing.get_context("spawn")
    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="reconforge-e828-receiver-") as temporary:
        temporary_path = Path(temporary)
        database = temporary_path / "receiver.db"
        restored_database = temporary_path / "restored.db"
        store = SQLiteWritebackReceiverStore(database)
        store.initialize()

        sequential = _request("receiver-sequential-1", payload=b'{"reference":"sequential"}')
        first = store.receive(sequential)
        replay = store.receive(sequential)
        if (
            first.disposition is not WritebackReceiverDisposition.APPLIED
            or replay.disposition is not WritebackReceiverDisposition.REPLAYED
            or first.response != replay.response
        ):
            raise ReceiverDrillError("sequential receiver replay contract failed")

        conflict_refused = False
        try:
            store.receive(_request("receiver-sequential-1", payload=b'{"reference":"retargeted"}'))
        except WritebackReceiverError as exc:
            conflict_refused = str(exc) == "writeback_receiver_idempotency_conflict"
        if not conflict_refused:
            raise ReceiverDrillError("same-key payload retargeting was not refused")

        concurrent = _request("receiver-concurrent-1", payload=b'{"reference":"concurrent"}')
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_receive_worker,
                args=(str(database), concurrent.model_dump(mode="json"), start, results),
            )
            for _ in range(8)
        ]
        try:
            for process in processes:
                process.start()
            start.set()
            concurrent_results = [results.get(timeout=30) for _ in processes]
            for index, process in enumerate(processes):
                _join(process, label=f"concurrent receiver {index}")
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            results.close()
            results.join_thread()
        concurrent_dispositions = [item[0] for item in concurrent_results]
        concurrent_response_digests = {item[1] for item in concurrent_results}
        if (
            concurrent_dispositions.count(WritebackReceiverDisposition.APPLIED.value) != 1
            or concurrent_dispositions.count(WritebackReceiverDisposition.REPLAYED.value) != 7
            or len(concurrent_response_digests) != 1
        ):
            raise ReceiverDrillError("concurrent receiver convergence failed")

        crash = _request("receiver-crash-1", payload=b'{"reference":"crash"}')
        crash_process = context.Process(
            target=_crash_after_commit,
            args=(str(database), crash.model_dump(mode="json")),
        )
        crash_process.start()
        _join(crash_process, label="crash-after-commit receiver")
        crash_replay = store.receive(crash)
        if crash_replay.disposition is not WritebackReceiverDisposition.REPLAYED:
            raise ReceiverDrillError("crash retry did not replay the committed receiver effect")

        update_refused, delete_refused = _immutability_checks(database)
        counts = store.counts()
        history_digest = store.canonical_history_digest()
        if counts.receipts != 3 or counts.effects != 3:
            raise ReceiverDrillError("receiver receipt/effect cardinality diverged")

        _backup(database, restored_database)
        restored = SQLiteWritebackReceiverStore(restored_database)
        restored_counts = restored.counts()
        restored_history_digest = restored.canonical_history_digest()
        restored_replay = restored.receive(crash)
        if restored_replay.disposition is not WritebackReceiverDisposition.REPLAYED:
            raise ReceiverDrillError("restored receiver did not retain replay identity")

        checks = {
            "sequential_apply_once": True,
            "exact_response_replay": True,
            "same_key_payload_conflict_refused": conflict_refused,
            "eight_processes_converged": True,
            "one_concurrent_effect": True,
            "crash_after_commit_replayed": True,
            "receipt_update_refused": update_refused,
            "effect_delete_refused": delete_refused,
            "independent_backup_restored": restored_counts == counts,
            "restored_history_digest_equal": restored_history_digest == history_digest,
            "restored_replay_created_no_effect": restored.counts() == restored_counts,
        }
        if not all(checks.values()):
            raise ReceiverDrillError("receiver conformance contains a failed check")
        observation = {
            "runtime": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "multiprocessing_start_method": context.get_start_method(),
            },
            "cases": {
                "sequential": {
                    "first_disposition": first.disposition.value,
                    "replay_disposition": replay.disposition.value,
                    "request_digest": sequential.request_digest,
                    "response_digest": first.response.response_digest,
                },
                "concurrent": {
                    "processes": len(processes),
                    "applied": concurrent_dispositions.count(WritebackReceiverDisposition.APPLIED.value),
                    "replayed": concurrent_dispositions.count(WritebackReceiverDisposition.REPLAYED.value),
                    "request_digest": concurrent.request_digest,
                    "response_digest": next(iter(concurrent_response_digests)),
                },
                "crash_after_commit": {
                    "child_exit_code": crash_process.exitcode,
                    "retry_disposition": crash_replay.disposition.value,
                    "request_digest": crash.request_digest,
                    "response_digest": crash_replay.response.response_digest,
                },
            },
            "history": {
                "receipts": counts.receipts,
                "effects": counts.effects,
                "canonical_sha256": history_digest,
                "restored_receipts": restored_counts.receipts,
                "restored_effects": restored_counts.effects,
                "restored_canonical_sha256": restored_history_digest,
            },
            "checks": checks,
        }
    cleanup_complete = temporary_path is not None and not temporary_path.exists()
    if not cleanup_complete:
        raise ReceiverDrillError("receiver conformance temporary directory cleanup was not verified")

    report: dict[str, Any] = {
        "schema_version": "writeback-receiver-idempotency-drill-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "profile": "synthetic-sqlite-writeback-receiver-idempotency",
        "subject": {
            "base_commit": _base_commit(),
            "receiver_source_sha256": _source_digest(RECEIVER_SOURCE),
            "runner_source_sha256": _source_digest(Path(__file__)),
        },
        **observation,
        "cleanup_complete": cleanup_complete,
        "limitations": [
            "single_host_sqlite_reference_receiver",
            "synthetic_digest_only_effects",
            "no_live_vendor_or_provider_status_contract",
            "no_cross_host_consensus_or_database_failover",
            "no_accounting_posting_or_production_claim",
        ],
    }
    report["report_digest"] = _canonical_digest(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = run_drill(arguments.output.resolve(strict=False))
    print(
        "writeback_receiver_idempotency=passed "
        f"report_digest={report['report_digest']} history_digest={report['history']['canonical_sha256']}"
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
