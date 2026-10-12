"""Stdlib-only diagnostic custody/oracle tests; no Docker/DB/application imports."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/benchmark_wave5_profile_diagnostics.py"
spec = importlib.util.spec_from_file_location("wave5_diagnostic_contract", SCRIPT)
assert spec is not None and spec.loader is not None
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)


def fixture(mode: str = "four-worker") -> tuple[dict, dict, list[str], Path]:
    root, harness = Path("/synthetic/current").resolve(), Path("/synthetic/current/.github/scripts/benchmark_enterprise_finance.py").resolve()
    source = {"commit": d.CURRENT, "tracked_sha256": "e" * 64, "root": str(root), "variant": "current",
              "revision": "0136_pg_inventory_scope"}
    command = [sys.executable, str(harness), *d.arguments(root, mode, Path("/synthetic/evidence/native"))]
    expected = dict.fromkeys(("debit_minor", "credit_minor", "cash_minor", "equity_minor"), "46669102")
    ids = [f"effect-{index}" for index in range(100)]
    effect_hash = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    reads = {label: [{"repetition": index, "status": "complete", "error_count": 0, "requested_effects": 100, "effects": 100,
                      "debit_minor": "46669102", "credit_minor": "46669102", "effects_digest": "f" * 64,
                      "raw_request_latency_seconds": [.1] * (100 if label == "per_effect_baseline" else 1),
                      "request_latency_seconds": {key: .1 for key in ("p50", "p95", "p99")}}
                     for index in range(3)] for label in ("per_effect_baseline", "bounded_batch")}
    packet = {"status": "passed", "source_unchanged": True, "owned_container_removed": True,
              "source_commit": d.CURRENT, "source_commit_after": d.CURRENT, "source_sha256": "e" * 64, "source_sha256_after": "e" * 64,
              "harness_sha256": d.HARNESS_SHA, "harness_sha256_after": d.HARNESS_SHA, "harness_path": str(harness), "command": command,
              "runtime_root": str(root), "launch_cwd": str(root), "counts": [100], "workers": d.PROFILE_CONFIG[mode][0], "repetitions": 3,
              "posting_warmup_cycles": 20, "max_seconds": 1200, "snapshot_lines": 1000 if mode == d.LARGE_MODE else 0, "image": d.IMAGE,
              "profile": "native-three-human-cash-equity-v1", "seed": "enterprise-native-v1", "cost_per_transaction": None,
              "runtime_role_flags": [False, False], "revision": "0136_pg_inventory_scope", "postgres_version": "17.11",
              "postgres_configuration": dict.fromkeys(("fsync", "full_page_writes", "synchronous_commit", "track_io_timing"), "on"),
              "posting": {"requested_cycles": 100, "admitted_cycles": 100, "completed_cycles": 100, "error_count": 0,
                          "not_admitted_cycles": 0, "failed_cycles": [], "completed_indices": list(range(100)), "expected": expected,
                          "ordered_effect_ids": ids, "raw_cycle_latency_seconds": [1.] * 100,
                          "cycle_latency_seconds": dict.fromkeys(("p50", "p95", "p99"), 1.)},
              "posting_warmup": {"status": "passed", "completed_cycles": 20, "indices": list(range(100, 120)),
                                 "outside_measured_population": True, "effect_ids": [f"warm-{i}" for i in range(20)]},
              "verified_reads": [{"count": 100, "status": "passed", "expected": expected, "dataset_effect_ids_sha256": effect_hash,
                                  "financial_effects_digest": "f" * 64, "samples": reads}],
              "posting_profile": {"enabled": True, "function_profile": {"enabled": mode == "serial-cpu", "cycle_ceiling": 32,
                                                                          "functions": [{"function": "synthetic"}]},
                                  "raw_phase_observations": [{"index": index, "phase": f"{stage}.{phase}", "failure_type": None,
                                                              "seconds": .1, "thread_cpu_seconds": .01}
                                                             for index in range(120) for stage in ("prepare", "review", "post")
                                                             for phase in ("identity_enter", "business", "transaction_exit")]},
              "posting_database_profile": {"status": "complete"},
              "resource_sampling": {"status": "complete", "thread_still_running": False, "errors": [], "interval_seconds": 10,
                                    "raw_samples": [{"elapsed_seconds": index * 10, "client_cpu_seconds": index,
                                                     "postgres_database_counters": {"deadlocks": 0},
                                                     "postgres_wal_counters": {"wal_bytes": str(index)}} for index in range(2)]}}
    if mode == d.LARGE_MODE:
        del packet["posting_database_profile"]
        samples = {label: [{"repetition": i, "status": "complete", "lines": 1000, "dimension_links": 668,
                            "debit_minor": "500", "credit_minor": "500", "validation_digest": "b" * 64,
                            "client_execute_calls": 1002 if label == "per_line_baseline" else 3,
                            "peak_python_allocated_bytes": 1000, "seconds": 1. if label == "per_line_baseline" else .5,
                            "client_process_cpu_seconds": .1} for i in range(3)] for label in ("per_line_baseline", "joined_snapshot")}
        packet["snapshot_reads"] = {"status": "passed", "fixture_stage": "complete", "line_count": 1000, "expected_total_minor": "500",
                                    "concurrency": 1, "outside_primary_posting_measurement": True,
                                    "seed": "alternating-cash-equity-one-minor-v1", "runtime_role_flags": [False, False],
                                    "expected_validation_digest": "b" * 64, "samples": samples,
                                    "median_seconds_baseline": 1., "median_seconds_optimized": .5, "measured_speedup": 2.,
                                    "stage_measurements": {stage: {"seconds": 1., "client_process_cpu_seconds": .2}
                                                           for stage in ("prepare", "review", "post")}}
    return packet, source, command, harness


@pytest.mark.parametrize("mode", list(d.MODES))
def test_exact_100_cycle_native_oracle_and_profiler_population(mode: str) -> None:
    packet, source, command, harness = fixture(mode)
    proof = d.verify_financial(packet, source, mode, command, harness)
    assert proof["financial_verification"] == "passed"
    assert proof["oracle_minor"] == "46669102"
    assert proof["read_requests"] == 303 and proof["phase_observations"] == 1080
    assert len(proof["measured_phases"]) == 9 and all(row["count"] == 100 for row in proof["measured_phases"].values())
    assert proof["performance_comparison_accepted"] is False


@pytest.mark.parametrize("variant", list(d.REVISIONS))
def test_all_three_fixed_migration_contracts_and_unknown_heads(variant: str) -> None:
    packet, source, command, harness = fixture()
    source.update(variant=variant, revision=d.REVISIONS[variant], commit={"baseline": d.BASELINE, "current": d.CURRENT,
                                                                       "projection": d.PROJECTION}[variant])
    packet.update(source_commit=source["commit"], source_commit_after=source["commit"], revision=source["revision"])
    assert d.verify_financial(packet, source, "four-worker", command, harness)["financial_verification"] == "passed"
    for wrong in set(d.REVISIONS.values()) - {source["revision"]} | {"0138_future"}:
        with pytest.raises(ValueError):
            d.verify_financial({**packet, "revision": wrong}, source, "four-worker", command, harness)
    with pytest.raises(ValueError):
        d.verify_financial(packet, {**source, "variant": "unknown"}, "four-worker", command, harness)


@pytest.mark.parametrize(("path", "value"), [
    (("counts",), [100.0]), (("workers",), 4.0), (("posting", "completed_cycles"), 100.0),
    (("posting", "error_count"), False), (("posting", "not_admitted_cycles"), 0.0),
    (("posting", "completed_indices", 1), True), (("posting", "expected", "cash_minor"), "46669103"),
    (("posting", "ordered_effect_ids", 99), "effect-0"), (("posting", "raw_cycle_latency_seconds"), [1.] * 99),
    (("posting_warmup", "indices", 0), 100.0), (("posting_warmup", "effect_ids", 0), "effect-0"),
    (("verified_reads", 0, "count"), 100.0), (("verified_reads", 0, "samples", "bounded_batch", 1, "repetition"), True),
    (("verified_reads", 0, "samples", "bounded_batch", 0, "effects"), 100.0),
    (("verified_reads", 0, "dataset_effect_ids_sha256"), "0" * 64),
    (("verified_reads", 0, "samples", "bounded_batch", 0, "debit_minor"), "46669101"),
    (("posting_profile", "raw_phase_observations", 0, "index"), False),
    (("posting_profile", "raw_phase_observations", 0, "seconds"), float("nan")),
    (("source_commit_after",), d.BASELINE), (("harness_sha256_after",), "0" * 64),
    (("revision",), "0136_pg_inventory_hierarchy_rls"), (("owned_container_removed",), False),
    (("postgres_configuration", "fsync"), "off"), (("runtime_role_flags",), [0, 0]),
    (("resource_sampling", "raw_samples", 1, "client_cpu_seconds"), -1),
])
def test_rehashed_malformed_population_never_gains_financial_acceptance(path: tuple, value: object) -> None:
    packet, source, command, harness = fixture()
    target = packet
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        d.verify_financial(packet, source, "four-worker", command, harness)


def words() -> list[str]:
    return ["docker", "run", "--detach", "--rm", "--name", "reconforge-enterprise-finance-0123456789ab",
            "--label", d.OWNER, "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", d.IMAGE,
            "-c", "shared_preload_libraries=pg_stat_statements", "-c", "pg_stat_statements.track=all",
            "-c", "pg_stat_statements.track_planning=on", "-c", "track_io_timing=on", "-c", "join_collapse_limit=8",
            "-c", "from_collapse_limit=8"]


def container(intent: dict, cid: str = "a" * 64) -> dict:
    return {"Id": cid, "Name": "/" + intent["name"], "Created": "2026-10-12T01:00:01Z", "Image": "sha256:" + "b" * 64,
            "Config": {"Image": d.IMAGE, "Labels": {"reconforge.owner": "enterprise-finance-benchmark"},
                       "Cmd": intent["cmd"], "Entrypoint": ["docker-entrypoint.sh"]},
            "HostConfig": {"AutoRemove": True, "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                           "PublishAllPorts": False, "Privileged": False,
                           "PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]}},
            "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "34567"}]}}}


@pytest.mark.parametrize(("path", "value"), [(('Id',), 'c' * 64), (('Name',), '/foreign'),
    (('Created',), '2026-10-12T00:59:59Z'), (('Config', 'Image'), 'postgres:17.11-alpine'),
    (('Config', 'Labels', 'reconforge.owner'), 'foreign'), (('Config', 'Cmd'), ['sleep', '100']),
    (('Config', 'Entrypoint'), ['foreign-entrypoint']), (('HostConfig', 'AutoRemove'), False),
    (('HostConfig', 'RestartPolicy', 'Name'), 'always'), (('HostConfig', 'PublishAllPorts'), True),
    (('HostConfig', 'Privileged'), True), (('HostConfig', 'PortBindings', '5432/tcp', 0, 'HostIp'), '0.0.0.0'),
    (('NetworkSettings', 'Ports', '5432/tcp', 0, 'HostIp'), '0.0.0.0')])
def test_foreign_or_predating_container_is_never_owned(path: tuple, value: object) -> None:
    intent = {**d.docker_words(words(), "four-worker"), "observed_at": "2026-10-12T01:00:00+00:00"}
    raw = container(intent)
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        d.verify_container(raw, intent, "a" * 64)


def test_typed_creation_before_spawn_exact_response_and_no_env_capture(tmp_path: Path) -> None:
    calls, audits = [], []
    process = {"pid": 1, "start_ticks": 2, "executable": "/python", "session": 1, "process_group": 1}

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        if argv[:3] == ["docker", "container", "ls"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if argv[:2] == ["docker", "run"]:
            assert (tmp_path / "creation-intent.json").is_file()
            audits[0]("subprocess.Popen", ("docker", argv, None, {"private": "not retained"}))
            return subprocess.CompletedProcess(argv, 0, "a" * 64 + "\n", "")
        if argv[:2] == ["docker", "inspect"]:
            intent = d.read(tmp_path / "creation-intent.json")
            raw = container(intent)
            raw["Created"] = "2099-10-12T01:00:01Z"
            return subprocess.CompletedProcess(argv, 0, json.dumps([raw]), "")
        raise AssertionError("Unexpected subprocess")

    with patch.object(d.sys, "addaudithook", side_effect=audits.append), patch.object(d.subprocess, "run", side_effect=fake):
        d.install_observer(tmp_path, "four-worker", process)
        outcome = d.subprocess.run(words(), env={"POSTGRES_PASSWORD": "synthetic-do-not-retain"}, capture_output=True, text=True)
    assert outcome.stdout.strip() == "a" * 64
    assert d.read(tmp_path / "creation-response.json")["container_id"] == "a" * 64
    assert "synthetic-do-not-retain" not in "".join(path.read_text() for path in tmp_path.iterdir())
    assert calls[0][:3] == ["docker", "container", "ls"]


def test_preexisting_exact_name_refuses_before_creation(tmp_path: Path) -> None:
    with patch.object(d.sys, "addaudithook"), patch.object(d.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"c" * 64)) as run:
        d.install_observer(tmp_path, "four-worker", {})
        with pytest.raises(ValueError, match="already exists"):
            d.subprocess.run(words())
    assert run.call_count == 1
    assert not (tmp_path / "creation-response.json").exists()


def test_cleanup_no_ack_or_bad_seal_never_deletes_container(tmp_path: Path) -> None:
    with patch.object(d, "checked") as call:
        proof = d.cleanup(tmp_path, deadline=time.monotonic() + 10)
    assert proof["status"] == "unverified"
    call.assert_not_called()
    d.save(tmp_path / "creation-intent.json", {"process": {}})
    d.save(tmp_path / "creation-audit.json", {})
    d.save(tmp_path / "creation-response.json", {"process": {}, "container_id": "a" * 64, "intent_sha256": "0" * 64,
                                                "audit_sha256": d.digest(tmp_path / "creation-audit.json"), "returncode": 0})
    with patch.object(d, "checked") as call, pytest.raises(ValueError):
        d.cleanup(tmp_path, deadline=time.monotonic() + 10)
    call.assert_not_called()


def test_cleanup_uses_only_acknowledged_id_and_verifies_absence(tmp_path: Path) -> None:
    process = {"pid": 1}
    intent = {**d.docker_words(words(), "four-worker"), "observed_at": "2026-10-12T01:00:00+00:00", "process": process}
    d.save(tmp_path / "creation-intent.json", intent)
    d.save(tmp_path / "creation-audit.json", {})
    d.save(tmp_path / "creation-response.json", {"process": process, "container_id": "a" * 64,
                                                "intent_sha256": d.digest(tmp_path / "creation-intent.json"),
                                                "audit_sha256": d.digest(tmp_path / "creation-audit.json"), "returncode": 0})
    d.save(tmp_path / "created-container.json", d.verify_container(container(intent), intent, "a" * 64))
    with patch.object(d, "checked", side_effect=[("a" * 64).encode(), json.dumps([container(intent)]).encode(), b"", b""]) as call:
        proof = d.cleanup(tmp_path, deadline=time.monotonic() + 10)
    assert proof["status"] == "verified_absent" and proof["deleted_by_parent"] is True
    assert call.call_args_list[2].args[0] == ["docker", "rm", "--force", "a" * 64]


def test_near_deadline_no_child_or_output_admitted(tmp_path: Path) -> None:
    with patch.object(d.subprocess, "Popen") as spawn, pytest.raises(ValueError, match="No new child"):
        d.one(tmp_path, {}, tmp_path / "harness", "four-worker", tmp_path / "not-created", deadline=time.monotonic() + 120)
    spawn.assert_not_called()
    assert not (tmp_path / "not-created").exists()


def test_changed_pid_birth_prevents_signal_or_group_kill() -> None:
    process = SimpleNamespace(pid=1, poll=lambda: None)
    with patch.object(d, "identity", return_value={"pid": 1, "start_ticks": 3}), patch.object(d.signal, "pidfd_send_signal", create=True) as send:
        with pytest.raises(ValueError):
            d.stop(process, 5, {"pid": 1, "start_ticks": 2}, deadline=time.monotonic() + 10)
        send.assert_not_called()


def test_post_completion_source_timeout_preserves_cleanup_reserve(tmp_path: Path) -> None:
    clock = {"now": 100.}
    retained = {"pid": 1, "start_ticks": 2, "executable": str(Path(sys.executable).resolve()), "session": 1, "process_group": 1}
    process = SimpleNamespace(pid=1, returncode=None, stdin=SimpleNamespace(write=lambda _: None, flush=lambda: None))
    process.poll = lambda: process.returncode
    expected = {"commit": d.CURRENT, "variant": "current", "revision": d.REVISIONS["current"]}
    directory = tmp_path / "child"

    def spawn(*args: object, **kwargs: object) -> object:
        d.save(directory / "worker-complete.json", {"exit_code": 0, "origin_status": "passed"})
        return process

    def late_source(*args: object, **kwargs: object) -> dict:
        assert kwargs["deadline"] == 880.
        clock["now"] = 881.
        return {"commit": d.CURRENT}

    def stopped(*args: object, **kwargs: object) -> None:
        assert kwargs["deadline"] == 1000.
        process.returncode = -9

    with patch.object(d.time, "monotonic", side_effect=lambda: clock["now"]), patch.object(d.subprocess, "Popen", side_effect=spawn), \
         patch.object(d, "identity", return_value=retained), patch.object(d.os, "pidfd_open", return_value=5, create=True), \
         patch.object(d.os, "close"), patch.object(d, "source", side_effect=late_source), patch.object(d, "stop", side_effect=stopped), \
         patch.object(d, "cleanup", return_value={"status": "verified_absent"}) as cleanup:
        proof = d.one(tmp_path, expected, tmp_path / "harness", "four-worker", directory, deadline=1000.)
    assert proof["status"] == "failed" and "cleanup reserve retained" in proof["primary_failure"]["failure"]
    assert cleanup.call_args.kwargs["deadline"] == 1000.


def test_atomic_original_packets_never_overwrite_or_accept_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "original.json"
    d.save(path, {"status": "failed"})
    with pytest.raises(FileExistsError):
        d.save(path, {"status": "passed"})
    assert d.read(path)["status"] == "failed"
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError):
        d.read(path)


def test_fixed_modes_image_common_harness_bounds_and_independence() -> None:
    assert (d.BUSINESS_SECONDS, d.CHILD_SECONDS, d.TOTAL_SECONDS, d.RESERVE) == (1200, 1500, 3300, 120)
    for mode, (workers, flags) in d.MODES.items():
        command = d.arguments(Path("/runtime"), mode, Path("/fresh"))
        assert command[command.index("--workers") + 1] == str(workers)
        assert all(flag in command for flag in flags)
        assert command[command.index("--postgres-image") + 1] == d.IMAGE
    assert "reconforge.infrastructure.postgres_finance_core" not in sys.modules


def test_large_journal_selection_has_nine_exact_balanced_fresh_runs() -> None:
    selected = d.schedule(False, 3)
    assert [row[1] for row in selected] == ["baseline", "current", "projection", "current", "projection", "baseline", "projection", "baseline", "current"]
    assert len({row[2] for row in selected}) == 9
    assert all(row[0] == d.LARGE_MODE for row in selected)
    for variant in d.REVISIONS:
        assert sum(row[1] == variant for row in selected) == 3
    command = d.arguments(Path("/runtime"), d.LARGE_MODE, Path("/fresh"))
    assert command[command.index("--snapshot-lines") + 1] == "1000"
    assert command[command.index("--workers") + 1] == "4"
    assert "--profile-stages" in command and "--profile-database" not in command and "--profile-cpu" not in command
    assert len(d.schedule(True, None)) == 6 and len(d.schedule(False, None)) == 3
    for include, repetitions in ((True, 3), (False, 2), (False, 3.0), (False, True)):
        with pytest.raises(ValueError):
            d.schedule(include, repetitions)


def test_large_journal_has_independent_whole_source_and_reviewed_read_oracle() -> None:
    packet, source, command, harness = fixture(d.LARGE_MODE)
    verified = d.verify_financial(packet, source, d.LARGE_MODE, command, harness)
    large = verified["large_journal"]
    assert large["lines"] == 1000 and large["dimension_links"] == 668 and large["snapshot_read_requests"] == 6
    assert large["debit_minor"] == large["credit_minor"] == "500" and verified["performance_comparison_accepted"] is False
    # Old six-mode admission cannot relabel a1000-line population as snapshot-off.
    with pytest.raises(ValueError):
        d.verify_financial(packet, source, "four-worker", command, harness)


@pytest.mark.parametrize(("path", "value"), [
    (("line_count",), 1000.0), (("concurrency",), True), (("fixture_stage",), "post"), (("expected_total_minor",), "501"),
    (("expected_validation_digest",), "unknown"), (("outside_primary_posting_measurement",), 1),
    (("stage_measurements", "post", "seconds"), float("nan")), (("stage_measurements", "review", "client_process_cpu_seconds"), True),
    (("samples", "joined_snapshot", 0, "dimension_links"), 667), (("samples", "joined_snapshot", 0, "dimension_links"), 668.0),
    (("samples", "joined_snapshot", 0, "lines"), 1000.0), (("samples", "per_line_baseline", 1, "repetition"), True),
    (("samples", "joined_snapshot", 1, "debit_minor"), "499"), (("samples", "joined_snapshot", 2, "credit_minor"), "501"),
    (("samples", "joined_snapshot", 2, "validation_digest"), "c" * 64), (("samples", "per_line_baseline"), []),
    (("median_seconds_optimized",), .1), (("measured_speedup",), 10),
])
def test_large_journal_rehashed_false_projections_refuse(path: tuple, value: object) -> None:
    packet, _, _, _ = fixture(d.LARGE_MODE)
    snapshot = packet["snapshot_reads"]
    target = snapshot
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        d.verify_snapshot(packet)


def test_large_probe_requires_pinned_oracle_before_any_output_or_child(tmp_path: Path) -> None:
    with patch.object(d.subprocess, "Popen") as spawn, pytest.raises(ValueError, match="oracle|helper"):
        d.one(tmp_path, {}, tmp_path / "harness", d.LARGE_MODE, tmp_path / "missing-helper", deadline=time.monotonic() + 1500)
    spawn.assert_not_called()
    assert not (tmp_path / "missing-helper").exists()


@pytest.mark.parametrize("capture_fails", [False, True])
@pytest.mark.parametrize("missing_configuration_seal", [False, True])
def test_live_native_oracle_capture_precedes_exact_cleanup_and_failure_is_retained(tmp_path: Path, capture_fails: bool,
                                                                                 missing_configuration_seal: bool) -> None:
    calls, audits = [], []
    process = {"pid": 1, "start_ticks": 2, "executable": "/python", "session": 1, "process_group": 1}
    argv = words()[:13] + ["-c", "join_collapse_limit=8", "-c", "from_collapse_limit=8"]

    def fake(words: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(words[1] if words[:1] == ["docker"] else "other")
        if words[:3] == ["docker", "container", "ls"]:
            return subprocess.CompletedProcess(words, 0, b"", b"")
        if words[:2] == ["docker", "run"]:
            audits[0]("subprocess.Popen", ("docker", words, None, None))
            return subprocess.CompletedProcess(words, 0, "a" * 64 + "\n", "")
        if words[:2] == ["docker", "inspect"]:
            raw = container(d.read(tmp_path / "creation-intent.json"))
            raw["Created"] = "2099-10-12T01:00:01Z"
            return subprocess.CompletedProcess(words, 0, json.dumps([raw]), "")
        if words == ["docker", "rm", "--force", "a" * 64]:
            return subprocess.CompletedProcess(words, 0, "a" * 64, "")
        raise AssertionError("Unexpected subprocess")

    def capture(**kwargs: object) -> None:
        assert kwargs["container_id"] == "a" * 64 and kwargs["source_process"] == process
        assert kwargs["run"] is original_run and kwargs["output"] == tmp_path
        calls.append("capture")
        if capture_fails:
            raise ValueError("Synthetic independent journal refusal")

    with patch.object(d.sys, "addaudithook", side_effect=audits.append), patch.object(d.subprocess, "run", side_effect=fake):
        original_run = d.subprocess.run
        d.install_observer(tmp_path, d.LARGE_MODE, process, SimpleNamespace(capture=capture))
        d.subprocess.run(argv, capture_output=True, text=True)
        if missing_configuration_seal:
            (tmp_path / "created-container.json").unlink()
        d.subprocess.run(["docker", "rm", "--force", "a" * 64], capture_output=True, text=True)
    if missing_configuration_seal:
        assert "capture" not in calls and calls[-1] == "rm"
    else:
        assert calls[-2:] == ["capture", "rm"]
    assert (tmp_path / "ledger-capture-failure.json").is_file() is (capture_fails or missing_configuration_seal)
    if capture_fails and not missing_configuration_seal:
        assert d.read(tmp_path / "ledger-capture-failure.json")["failure_type"] == "ValueError"


def large_population() -> list[dict]:
    entry = "GLE-" + hashlib.sha256(b"work|BENCH-SNAPSHOT-DIMENSIONS").hexdigest()[:16]
    return [{"variant": variant, "ledger": {"external_report_anchor": True, "line_count": 1000, "dimension_links": 668,
                                           "debit_minor": 500, "credit_minor": 500, "tenant_id": f"tenant-{i}",
                                           "entry_id": entry, "effect_id": f"large-{i}"},
             "container_id": f"{i:064x}", "primary_effect_ids": [f"primary-{i}-{n}" for n in range(100)],
             "warm_effect_ids": [f"warm-{i}-{n}" for n in range(20)]}
            for i, (_, variant, _) in enumerate(d.schedule(False, 3))]


def test_nine_whole_journal_oracles_have_fresh_disjoint_native_populations() -> None:
    proof = d.verify_large_population(large_population())
    assert proof["complete_runs"] == proof["fresh_tenants"] == proof["fresh_servers"] == proof["large_journals"] == 9
    assert proof["native_effects_including_primary_warm_and_large"] == 1089
    assert proof["observed_distinct_bare_entry_ids"] == 1 and proof["native_identity_scope"] == "tenant_id plus native ID"
    assert proof["large_lines"] == 9000 and proof["large_dimension_links"] == 6012
    assert proof["large_journal_debit_minor"] == proof["large_journal_credit_minor"] == 4500
    assert proof["snapshot_read_requests"] == 54 and proof["performance_comparison_accepted"] is False
    with pytest.raises(ValueError):
        d.verify_large_population(large_population()[:8])


@pytest.mark.parametrize(("key", "value"), [("tenant_id", "tenant-0"), ("entry_id", ""), ("effect_id", "primary-1-0"),
                                          ("debit_minor", 500.0), ("dimension_links", 668.0), ("external_report_anchor", 1)])
def test_rehashed_or_incomplete_large_sources_refuse(key: str, value: object) -> None:
    rows = large_population()
    rows[1]["ledger"][key] = value
    with pytest.raises(ValueError):
        d.verify_large_population(rows)


def test_bare_effect_ids_may_repeat_in_distinct_native_tenants() -> None:
    rows = large_population()
    for row in rows:
        row["ledger"]["effect_id"] = "large-effect"
        row["primary_effect_ids"] = [f"primary-{i}" for i in range(100)]
        row["warm_effect_ids"] = [f"warm-{i}" for i in range(20)]
    proof = d.verify_large_population(rows)
    assert proof["native_effects_including_primary_warm_and_large"] == 1089
    assert proof["observed_distinct_bare_effect_ids"] == 121
