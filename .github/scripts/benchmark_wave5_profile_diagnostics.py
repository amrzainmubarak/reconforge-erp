#!/usr/bin/env python3
"""Linux-only owned synthetic100-cycle profiling; never performance acceptance.

Run the unchanged final22 harness against three isolated committed checkouts.
No credential/DSN/environment values are added to the ownership evidence. The
worker waits for retained pidfd/session admission before importing the harness;
only its successful Docker creation's immutable full ID is eligible for removal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import signal
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

BASELINE = "6362724f2337a79c3d7569574f7bf9591a018524"
CURRENT = "22ebfd78e293aafa13d81b3a0bbf287491951115"
PROJECTION = "a4a5282aaf29ff89e182569888877fa606dde6a5"
HARNESS_SHA = "7bce2382df24d439d39386f0e02c07bf362c4f451649dbd8d7f225c8a920396b"
IMAGE = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3"
OWNER = "reconforge.owner=enterprise-finance-benchmark"
BUSINESS_SECONDS, CHILD_SECONDS, TOTAL_SECONDS, RESERVE = 1200, 1500, 3300, 120
MODES = {"four-worker": (4, ["--profile-stages", "--profile-database"]),
         "serial-cpu": (1, ["--profile-stages", "--profile-cpu"])}
REVISIONS = {"baseline": "0132_pg_stock_inverse_dispatch", "current": "0136_pg_inventory_scope",
             "projection": "0137_pg_intercompany_projection"}
REQUIRED_MODULES = {"reconforge.infrastructure.postgres_finance_core", "reconforge.infrastructure.postgres_finance_posting",
                    "reconforge.benchmark.resource_sampling", "tests.erp_expansion_browser_seed"}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def read(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_bytes(), object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    require(type(result) is dict, "Expected JSON object")
    return result


def save(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.link(temporary, path)  # Atomic publication, preserving exclusive original evidence.
    finally:
        temporary.unlink(missing_ok=True)


def checked(argv: list[str], *, root: Path | None = None, deadline: float, timeout: int = 30) -> bytes:
    remaining = deadline - time.monotonic()
    require(remaining > 0, "Absolute diagnostic deadline exhausted")
    result = subprocess.run(argv, cwd=root, capture_output=True, timeout=min(timeout, remaining), check=False)
    require(result.returncode == 0, "Read-only provenance command failed")
    return result.stdout


def source(root: Path, commit: str, *, deadline: float) -> dict[str, Any]:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "Exact source commit required")
    require(checked(["git", "rev-parse", "HEAD"], root=root, deadline=deadline).decode().strip() == commit,
            "Actual source head differs")
    require(not checked(["git", "status", "--porcelain", "--untracked-files=normal"], root=root, deadline=deadline),
            "Clean committed source with no untracked imports required")
    names = sorted(filter(None, checked(["git", "ls-files", "-z"], root=root, deadline=deadline).decode().split("\0")))
    result = hashlib.sha256()
    for name in names:
        require(time.monotonic() < deadline, "Source fingerprint deadline exhausted")
        path = root / name
        require(path.resolve().is_relative_to(root), "Tracked source outside checkout")
        result.update(name.encode())
        result.update(bytes.fromhex(digest(path)))
    return {"commit": commit, "tracked_sha256": result.hexdigest(), "tracked_files": len(names),
            "root": str(root), "git_tree": checked(["git", "rev-parse", "HEAD^{tree}"], root=root, deadline=deadline).decode().strip()}


def projection_tree(root: Path, commit: str, *, deadline: float) -> dict[str, Any]:
    checked(["git", "merge-base", "--is-ancestor", PROJECTION, commit], root=root, deadline=deadline)
    result = {}
    for path in ("reconforge", "alembic"):
        original = checked(["git", "rev-parse", f"{PROJECTION}:{path}"], root=root, deadline=deadline).decode().strip()
        actual = checked(["git", "rev-parse", f"{commit}:{path}"], root=root, deadline=deadline).decode().strip()
        require(original == actual, "Projection operational tree differs from reviewed projection")
        result[path] = actual
    return {"reviewed_ancestor": PROJECTION, "actual_commit": commit, "operational_trees": result}


def identity(pid: int) -> dict[str, Any]:
    raw = Path(f"/proc/{pid}/stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    return {"pid": pid, "start_ticks": int(fields[19]), "executable": str(Path(f"/proc/{pid}/exe").resolve()),
            "session": int(fields[3]), "process_group": int(fields[2])}


def numeric(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def exact_ints(value: dict[str, Any], names: tuple[str, ...]) -> None:
    require(all(type(value[name]) is int for name in names), "Counter must be an exact nonboolean integer")


def percentile(raw: list[Any], retained: dict[str, Any]) -> None:
    require(bool(raw) and all(numeric(value) for value in raw), "Invalid original latency vector")
    ordered = sorted(raw)
    require(all(numeric(retained[name]) and retained[name] == ordered[math.ceil(len(raw) * fraction) - 1]
                for name, fraction in (("p50", .5), ("p95", .95), ("p99", .99))), "Retained percentile differs from original raw vector")


def verify_financial(packet: dict[str, Any], expected_source: dict[str, Any], mode: str, command: list[str], harness: Path) -> dict[str, Any]:
    require(expected_source["variant"] in REVISIONS and expected_source["revision"] == REVISIONS[expected_source["variant"]],
            "Unknown expected diagnostic migration contract")
    require(packet["status"] == "passed" and packet["source_unchanged"] is True and packet["owned_container_removed"] is True,
            "Incomplete financial/source/cleanup report")
    require(packet["source_commit"] == packet["source_commit_after"] == expected_source["commit"]
            and packet["source_sha256"] == packet["source_sha256_after"] == expected_source["tracked_sha256"], "Runtime source differs")
    require(packet["harness_sha256"] == packet["harness_sha256_after"] == HARNESS_SHA
            and Path(packet["harness_path"]).resolve() == harness and packet["command"] == command
            and Path(packet["runtime_root"]).resolve() == Path(expected_source["root"])
            and Path(packet["launch_cwd"]).resolve() == Path(expected_source["root"]), "Common harness/command differs")
    exact_ints(packet, ("workers", "repetitions", "posting_warmup_cycles", "max_seconds", "snapshot_lines"))
    require(packet["counts"] == [100] and all(type(v) is int for v in packet["counts"])
            and packet["workers"] == MODES[mode][0] and packet["repetitions"] == 3 and packet["posting_warmup_cycles"] == 20
            and packet["max_seconds"] == BUSINESS_SECONDS and packet["snapshot_lines"] == 0 and packet["image"] == IMAGE
            and packet["profile"] == "native-three-human-cash-equity-v1" and packet["seed"] == "enterprise-native-v1"
            and packet["cost_per_transaction"] is None and packet["runtime_role_flags"] == [False, False]
            and all(type(v) is bool for v in packet["runtime_role_flags"]), "Profile configuration/current restricted role differs")
    require(packet["revision"] == expected_source["revision"]
            and packet["postgres_version"].startswith("17.11")
            and all(packet["postgres_configuration"][key] == "on" for key in ("fsync", "full_page_writes", "synchronous_commit")),
            "Migration/version/durability differs")
    posting = packet["posting"]
    exact_ints(posting, ("requested_cycles", "admitted_cycles", "completed_cycles", "error_count", "not_admitted_cycles"))
    require(posting["requested_cycles"] == posting["admitted_cycles"] == posting["completed_cycles"] == 100
            and posting["error_count"] == posting["not_admitted_cycles"] == 0 and posting["failed_cycles"] == []
            and posting["completed_indices"] == list(range(100)) and all(type(v) is int for v in posting["completed_indices"]),
            "Incomplete/failed native posting population")
    total = str(sum(1 + int(hashlib.sha256(f"enterprise-native-v1:{i}".encode()).hexdigest()[:16], 16) % 1_000_000 for i in range(100)))
    expected = dict.fromkeys(("debit_minor", "credit_minor", "cash_minor", "equity_minor"), total)
    require(total == "46669102" and posting["expected"] == expected, "Independent SHA256/integer oracle differs")
    effects = posting["ordered_effect_ids"]
    require(len(effects) == len(set(effects)) == 100 and all(type(v) is str and v for v in effects), "Native effect population differs")
    warm = packet["posting_warmup"]
    exact_ints(warm, ("completed_cycles",))
    require(warm["status"] == "passed" and warm["completed_cycles"] == 20 and warm["indices"] == list(range(100, 120))
            and all(type(v) is int for v in warm["indices"]) and warm["outside_measured_population"] is True
            and len(warm["effect_ids"]) == len(set(warm["effect_ids"])) == 20 and all(type(v) is str and v for v in warm["effect_ids"])
            and not set(warm["effect_ids"]) & set(effects), "Warmup/native population overlaps")
    require(len(posting["raw_cycle_latency_seconds"]) == 100, "Missing raw native latency vector")
    percentile(posting["raw_cycle_latency_seconds"], posting["cycle_latency_seconds"])
    reads = packet["verified_reads"]
    require(len(reads) == 1, "Missing verified native read profile")
    profile = reads[0]
    exact_ints(profile, ("count",))
    effect_hash = hashlib.sha256(json.dumps(effects, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    require(profile["count"] == 100 and profile["status"] == "passed" and profile["expected"] == expected
            and profile["dataset_effect_ids_sha256"] == effect_hash and re.fullmatch(r"[a-f0-9]{64}", profile["financial_effects_digest"])
            and set(profile["samples"]) == {"per_effect_baseline", "bounded_batch"}, "Read financial/population binding differs")
    for label, rows in profile["samples"].items():
        require([row["repetition"] for row in rows] == [0, 1, 2], "Missing original read repetitions")
        for row in rows:
            exact_ints(row, ("repetition", "requested_effects", "effects", "error_count"))
            require(row["status"] == "complete" and row["requested_effects"] == row["effects"] == 100 and row["error_count"] == 0
                    and row["debit_minor"] == row["credit_minor"] == total and row["effects_digest"] == profile["financial_effects_digest"]
                    and len(row["raw_request_latency_seconds"]) == (100 if label == "per_effect_baseline" else 1), "Read financial oracle failed")
            percentile(row["raw_request_latency_seconds"], row["request_latency_seconds"])
    retained = packet["posting_profile"]
    rows = retained["raw_phase_observations"]
    keys = {(i, f"{stage}.{phase}") for i in range(120) for stage in ("prepare", "review", "post")
            for phase in ("identity_enter", "business", "transaction_exit")}
    require(retained["enabled"] is True and retained["function_profile"]["enabled"] is (mode == "serial-cpu")
            and len(rows) == 1080 and all(type(row["index"]) is int and type(row["phase"]) is str for row in rows)
            and {(row["index"], row["phase"]) for row in rows} == keys and all(row["failure_type"] is None for row in rows)
            and all(numeric(row[key]) for row in rows for key in ("seconds", "thread_cpu_seconds")), "Incomplete typed phase population")
    if mode == "four-worker":
        require(packet["posting_database_profile"]["status"] == "complete" and packet["postgres_configuration"]["track_io_timing"] == "on",
                "Native PostgreSQL query discovery missing")
    else:
        exact_ints(retained["function_profile"], ("cycle_ceiling",))
        require(retained["function_profile"]["cycle_ceiling"] == 32 and retained["function_profile"]["functions"], "Serial function profile missing")
    sampling = packet["resource_sampling"]
    require(sampling["status"] == "complete" and sampling["thread_still_running"] is False and sampling["errors"] == [],
            "Incomplete resource observation")
    samples = sampling["raw_samples"]
    require(type(sampling["interval_seconds"]) is int and sampling["interval_seconds"] == 10 and len(samples) >= 2
            and all(numeric(row["elapsed_seconds"]) and numeric(row["client_cpu_seconds"]) for row in samples)
            and all(a["elapsed_seconds"] < b["elapsed_seconds"] and a["client_cpu_seconds"] <= b["client_cpu_seconds"]
                    for a, b in zip(samples, samples[1:], strict=False)), "Resource observations are incomplete/unordered")
    for a, b in zip(samples, samples[1:], strict=False):
        require(set(a["postgres_database_counters"]) == set(b["postgres_database_counters"])
                and all(numeric(value) and numeric(b["postgres_database_counters"][key]) and value <= b["postgres_database_counters"][key]
                        for key, value in a["postgres_database_counters"].items())
                and int(a["postgres_wal_counters"]["wal_bytes"]) <= int(b["postgres_wal_counters"]["wal_bytes"]),
                "Observed PostgreSQL cumulative counters decreased")
    measured = [row for row in rows if row["index"] < 100]
    phases = {phase: {"count": len(group), "wall_seconds_sum": sum(row["seconds"] for row in group),
                      "thread_cpu_seconds_sum": sum(row["thread_cpu_seconds"] for row in group),
                      "wall_seconds_median": statistics.median(row["seconds"] for row in group)}
              for phase in sorted({row["phase"] for row in measured}) if (group := [row for row in measured if row["phase"] == phase])}
    return {"financial_verification": "passed", "oracle_minor": total, "cycles": 100, "warmups": 20, "read_requests": 303,
            "phase_observations": 1080, "measured_phases": phases, "performance_comparison_accepted": False}


def docker_words(words: list[str], mode: str) -> dict[str, Any]:
    require(all(type(word) is str for word in words), "Original typed Docker argv required")
    prefix = ["docker", "run", "--detach", "--rm", "--name"]
    require(words[:5] == prefix and len(words) > 14 and re.fullmatch(r"reconforge-enterprise-finance-[a-f0-9]{12}", words[5]),
            "Unexpected owned Docker creation")
    require(words[6:14] == ["--label", OWNER, "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", IMAGE, "-c"],
            "Unexpected Docker ownership/image/port arguments")
    options = (["-c", "shared_preload_libraries=pg_stat_statements", "-c", "pg_stat_statements.track=all",
                "-c", "pg_stat_statements.track_planning=on", "-c", "track_io_timing=on"] if mode == "four-worker" else [])
    options += ["-c", "join_collapse_limit=8", "-c", "from_collapse_limit=8"]
    require(words[13:] == options, "Owned PostgreSQL server options differ")
    return {"name": words[5], "image": IMAGE, "label": OWNER, "cmd": options, "entrypoint": ["docker-entrypoint.sh"],
            "command_sha256": hashlib.sha256(json.dumps(words, separators=(",", ":")).encode()).hexdigest()}


def verify_container(value: dict[str, Any], intent: dict[str, Any], cid: str) -> dict[str, Any]:
    require(re.fullmatch(r"[a-f0-9]{64}", cid) is not None and value["Id"] == cid and value["Name"] == "/" + intent["name"],
            "Acknowledged immutable container identity differs")
    config = value["Config"]
    require(config["Image"] == intent["image"] and config["Labels"].get("reconforge.owner") == "enterprise-finance-benchmark"
            and config["Cmd"] == intent["cmd"] and config["Entrypoint"] == intent["entrypoint"], "Owned container immutable configuration differs")
    host = value["HostConfig"]
    require(host["AutoRemove"] is True and host["RestartPolicy"]["Name"] == "no"
            and host["PublishAllPorts"] is False and host["Privileged"] is False
            and set(host["PortBindings"]) == {"5432/tcp"}, "Owned container restart/removal/publication policy differs")
    bindings = host["PortBindings"]["5432/tcp"]
    require(len(bindings) == 1 and bindings[0]["HostIp"] == "127.0.0.1" and type(bindings[0]["HostPort"]) is str
            and (bindings[0]["HostPort"] in ("", "0") or re.fullmatch(r"[1-9][0-9]{0,4}", bindings[0]["HostPort"])
                 and int(bindings[0]["HostPort"]) <= 65535), "Typed loopback-only ephemeral port binding differs")
    ports = value["NetworkSettings"]["Ports"]
    require(set(ports) == {"5432/tcp"} and len(ports["5432/tcp"]) == 1 and ports["5432/tcp"][0]["HostIp"] == "127.0.0.1"
            and type(ports["5432/tcp"][0]["HostPort"]) is str and re.fullmatch(r"[1-9][0-9]{0,4}", ports["5432/tcp"][0]["HostPort"])
            and int(ports["5432/tcp"][0]["HostPort"]) <= 65535, "Actual PostgreSQL listener is not one loopback-only port")
    created = datetime.fromisoformat(value["Created"].replace("Z", "+00:00"))
    require(created >= datetime.fromisoformat(intent["observed_at"]), "Container predates original audited creation")
    return {"container_id": cid, "name": value["Name"], "created_at": value["Created"], "image": config["Image"],
            "image_id": value["Image"], "cmd": config["Cmd"], "entrypoint": config["Entrypoint"], "owner_label": intent["label"],
            "auto_remove": host["AutoRemove"], "restart_policy": host["RestartPolicy"], "port_bindings": host["PortBindings"],
            "actual_ports": ports, "publish_all_ports": host["PublishAllPorts"], "privileged": host["Privileged"]}


def install_observer(directory: Path, mode: str, process: dict[str, Any]) -> None:
    original = subprocess.run
    pending: list[str] | None = None

    def audit(event: str, values: tuple[Any, ...]) -> None:
        if event == "subprocess.Popen" and pending is not None:
            require(type(values[1]) in (list, tuple) and list(values[1]) == pending, "Native typed creation differs")
            save(directory / "creation-audit.json", {"status": "matched", "process": process,
                 "command_sha256": hashlib.sha256(json.dumps(pending, separators=(",", ":")).encode()).hexdigest()})

    def observed(*args: Any, **kwargs: Any) -> Any:
        nonlocal pending
        words = args[0] if args else kwargs.get("args")
        creation = type(words) in (list, tuple) and len(words) > 1 and list(words[:2]) == ["docker", "run"]
        intent = None
        if creation:
            intent = {**docker_words(list(words), mode), "process": process, "observed_at": datetime.now(UTC).isoformat()}
            absence = original(["docker", "container", "ls", "--all", "--no-trunc", "--filter", f"name=^/{intent['name']}$",
                                "--format", "{{.ID}}"], capture_output=True, timeout=5, check=False)
            require(absence.returncode == 0 and not absence.stdout.strip(), "Exact container name already exists; no creation admitted")
            intent["pre_spawn_exact_name_absent"] = True
            save(directory / "creation-intent.json", intent)
            pending = list(words)
        if type(words) in (list, tuple) and list(words[:3]) == ["docker", "rm", "--force"]:
            seal = read(directory / "creation-response.json")
            require(list(words) == ["docker", "rm", "--force", seal["container_id"]], "Public harness cleanup ID differs from acknowledged ownership")
        try:
            result = original(*args, **kwargs)
        finally:
            pending = None
        if creation:
            require(result.returncode == 0, "Docker creation not acknowledged; ownership unverified")
            response = result.stdout.decode() if type(result.stdout) is bytes else result.stdout
            require(type(response) is str and re.fullmatch(r"[a-f0-9]{64}", response.strip()), "No exact Docker creation response ID")
            cid = response.strip()
            save(directory / "creation-response.json", {"process": process, "container_id": cid,
                 "intent_sha256": digest(directory / "creation-intent.json"), "audit_sha256": digest(directory / "creation-audit.json"),
                 "response_sha256": hashlib.sha256(response.encode()).hexdigest(), "returncode": 0})
            inspected = original(["docker", "inspect", cid], capture_output=True, text=True, timeout=10, check=False)
            require(inspected.returncode == 0, "Acknowledged container immutable configuration unavailable")
            records = json.loads(inspected.stdout)
            require(len(records) == 1 and intent is not None, "Owned container inspect population differs")
            save(directory / "created-container.json", verify_container(records[0], intent, cid))
        return result

    sys.addaudithook(audit)
    subprocess.run = observed


def child(spec_path: Path) -> int:
    spec = read(spec_path)
    directory, root, harness = (Path(spec[key]).resolve() for key in ("directory", "root", "harness"))
    process = identity(os.getpid())
    require(process["pid"] == process["session"] == process["process_group"] and process["executable"] == str(Path(sys.executable).resolve()),
            "Actual Linux interpreter/session identity differs")
    require(digest(harness) == HARNESS_SHA and digest(Path(__file__)) == spec["launcher_sha256"], "Common harness/worker bytes differ")
    admission_line = sys.stdin.readline()
    require(admission_line.strip() == "ADMIT", "Retained parent admission absent")
    require(read(directory / "admission.json")["process"] == process, "Retained pidfd admission differs")
    install_observer(directory, spec["mode"], process)
    sys.argv = [str(harness), *spec["business_args"]]
    code = 1
    try:
        runpy.run_path(str(harness), run_name="__main__")
    except SystemExit as exc:
        code = exc.code if type(exc.code) is int else 1
    except BaseException as exc:
        save(directory / "worker-failure.json", {"failure_type": type(exc).__name__})
    finally:
        tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=root, timeout=30).decode().split("\0"))
        origins, foreign = [], []
        for name, module in sorted(sys.modules.items()):
            if name == "reconforge" or name.startswith(("reconforge.", "tests.")):
                filename = getattr(module, "__file__", None)
                if filename:
                    actual = Path(filename).resolve()
                    row = {"module": name, "path": str(actual)}
                    origins.append(row)
                    if not actual.is_relative_to(root) or actual.relative_to(root).as_posix() not in tracked:
                        foreign.append(row)
        status = "passed" if not foreign and REQUIRED_MODULES.issubset({row["module"] for row in origins}) else "failed"
        save(directory / "origins.json", {"status": status, "process": process, "runtime_root": str(root), "origins": origins,
             "foreign_modules": foreign, "harness_sha256_after": digest(harness)})
        save(directory / "worker-complete.json", {"exit_code": code, "origin_status": status})
        # Keep the admitted session leader alive until cleanup/source checks end.
        # Its PID/group cannot be recycled before parent release/retained stop.
        require(sys.stdin.readline().strip() == "RELEASE", "Parent completion release absent")
    return code if status == "passed" else 1


def cleanup(directory: Path, *, deadline: float) -> dict[str, Any]:
    response = directory / "creation-response.json"
    if not response.is_file():
        return {"status": "unverified", "reason": "No acknowledged immutable creation ID; no container deletion attempted"}
    seal, intent = read(response), read(directory / "creation-intent.json")
    require(seal["intent_sha256"] == digest(directory / "creation-intent.json")
            and seal["audit_sha256"] == digest(directory / "creation-audit.json") and seal["process"] == intent["process"]
            and seal["returncode"] == 0, "Original creation custody seal differs")
    cid = seal["container_id"]
    require(type(cid) is str and re.fullmatch(r"[a-f0-9]{64}", cid), "No full immutable container ID")
    rows = checked(["docker", "container", "ls", "--all", "--no-trunc", "--filter", f"id={cid}", "--format", "{{.ID}}"],
                   deadline=deadline, timeout=10).decode().split()
    if not rows:
        return {"status": "verified_absent", "container_id": cid, "deleted_by_parent": False}
    require(rows == [cid], "Exact ownership presence query differs")
    actual = json.loads(checked(["docker", "inspect", cid], deadline=deadline, timeout=10))
    require(len(actual) == 1, "Immutable ownership inspect differs")
    captured = verify_container(actual[0], intent, cid)
    if (directory / "created-container.json").exists():
        require(captured == read(directory / "created-container.json"), "Immutable container was replaced")
    checked(["docker", "rm", "--force", cid], deadline=deadline, timeout=10)
    require(not checked(["docker", "container", "ls", "--all", "--no-trunc", "--filter", f"id={cid}", "--format", "{{.ID}}"],
                        deadline=deadline, timeout=10).strip(), "Owned exact-ID cleanup not verified")
    return {"status": "verified_absent", "container_id": cid, "deleted_by_parent": True}


def stop(process: subprocess.Popen[Any], pidfd: int, retained: dict[str, Any], *, deadline: float) -> None:
    if process.poll() is not None:
        return
    require(identity(process.pid) == retained, "Retained session leader identity changed")
    signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
    stopped_deadline = min(deadline, time.monotonic() + 2)
    while time.monotonic() < stopped_deadline:
        raw = Path(f"/proc/{process.pid}/stat").read_text()
        if raw[raw.rfind(")") + 2:].split()[0] == "T":
            break
        time.sleep(.01)
    else:
        raise ValueError("Retained session leader could not be stopped before group termination")
    require(identity(process.pid) == retained and retained["session"] == retained["process_group"] == process.pid,
            "Stopped owned session identity differs")
    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=max(.01, min(5, deadline - time.monotonic())))


def arguments(root: Path, mode: str, output: Path) -> list[str]:
    return ["--counts", "100", "--workers", str(MODES[mode][0]), "--repetitions", "3", "--posting-warmup", "20",
            "--max-seconds", str(BUSINESS_SECONDS), "--runtime-root", str(root), "--postgres-image", IMAGE,
            "--snapshot-lines", "0", *MODES[mode][1], "--output", str(output)]


def one(root: Path, expected: dict[str, Any], harness: Path, mode: str, directory: Path, *, deadline: float) -> dict[str, Any]:
    require(deadline - time.monotonic() > RESERVE + 30, "No new child admitted near overall deadline")
    require(not directory.exists(), "Fresh child evidence directory required")
    directory.mkdir()
    spec = {"root": str(root), "directory": str(directory), "harness": str(harness), "mode": mode,
            "launcher_sha256": digest(Path(__file__)), "business_args": arguments(root, mode, directory / "native")}
    save(directory / "spec.json", spec)
    result: dict[str, Any] = {"status": "failed", "mode": mode, "source_before": expected, "performance_comparison_accepted": False}
    process, pidfd, retained = None, None, None
    end = min(deadline - RESERVE, time.monotonic() + CHILD_SECONDS)
    try:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(root)
        environment.pop("PYTHONHOME", None)
        with (directory / "worker.log").open("xb") as log:
            process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(directory / "spec.json")],
                                       cwd=root, env=environment, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, text=True)
            retained = identity(process.pid)
            require(retained["pid"] == retained["session"] == retained["process_group"]
                    and retained["executable"] == str(Path(sys.executable).resolve()), "Actual worker executable/session differs")
            pidfd = os.pidfd_open(process.pid)
            require(identity(process.pid) == retained, "Worker birth changed before retained pidfd admission")
            result["process"] = retained
            save(directory / "admission.json", {"process": retained, "retained_pidfd": True})
            require(process.stdin is not None, "Worker admission pipe absent")
            process.stdin.write("ADMIT\n")
            process.stdin.flush()
            while not (directory / "worker-complete.json").is_file():
                require(process.poll() is None and time.monotonic() < end, "Worker failed or diagnostic deadline exhausted")
                time.sleep(.2)
            complete = read(directory / "worker-complete.json")
            require(complete["exit_code"] == 0 and type(complete["exit_code"]) is int and complete["origin_status"] == "passed",
                    "Worker original financial/origin status failed")
        require(time.monotonic() < end, "Work deadline exhausted before success-side provenance; cleanup reserve retained")
        result["source_after"] = {**source(root, expected["commit"], deadline=end),
                                  "variant": expected["variant"], "revision": expected["revision"]}
        require(result["source_after"] == expected, "Actual source changed during diagnostics")
        require(time.monotonic() < end, "Work deadline exhausted during success-side provenance; cleanup reserve retained")
        origins = read(directory / "origins.json")
        require(origins["status"] == "passed" and origins["process"] == retained and origins["runtime_root"] == str(root)
                and origins["foreign_modules"] == [] and origins["harness_sha256_after"] == HARNESS_SHA, "Full source-origin closure differs")
        tracked = set(checked(["git", "ls-files", "-z"], root=root, deadline=end).decode().split("\0"))
        require(REQUIRED_MODULES.issubset({row["module"] for row in origins["origins"]})
                and all(Path(row["path"]).resolve().is_relative_to(root)
                        and Path(row["path"]).resolve().relative_to(root).as_posix() in tracked for row in origins["origins"]),
                "Origin paths are detached from actual tracked runtime")
        raw = directory / "native" / "result.json"
        result["original_result_sha256"] = digest(raw)
        result["verification"] = verify_financial(read(raw), expected, mode, [sys.executable, str(harness), *spec["business_args"]], harness)
        require(time.monotonic() < end, "Work deadline exhausted during financial/origin verification; cleanup reserve retained")
        result["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        result["primary_failure"] = {"failure_type": type(exc).__name__, "failure": str(exc)}
    finally:
        try:
            if process is not None and process.poll() is None:
                if result["status"] == "passed" and process.stdin is not None:
                    process.stdin.write("RELEASE\n")
                    process.stdin.flush()
                    process.wait(timeout=max(.01, min(5, deadline - time.monotonic())))
                    require(process.returncode == 0, "Released worker exit status failed")
                elif pidfd is not None and retained is not None:
                    stop(process, pidfd, retained, deadline=deadline)
                else:
                    process.kill()  # retained Popen handle before admission; no subprocess can exist
                    process.wait(timeout=5)
            result["process_cleanup"] = {"status": "verified_exited" if process is None or process.poll() is not None else "unverified"}
        except Exception as exc:
            result["process_cleanup"] = {"status": "unverified", "failure_type": type(exc).__name__}
            result["status"] = "failed"
        finally:
            if pidfd is not None:
                os.close(pidfd)
        try:
            result["container_cleanup"] = cleanup(directory, deadline=deadline)
            require(result["container_cleanup"]["status"] == "verified_absent", "Acknowledged ownership cleanup is unverified")
        except Exception as exc:
            result["container_cleanup"] = {"status": "unverified", "failure_type": type(exc).__name__}
            result["status"] = "failed"
        raw = directory / "native" / "result.json"
        if raw.is_file():
            result["original_result_sha256"] = digest(raw)
        save(directory / "diagnostic.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--current-root", type=Path)
    parser.add_argument("--projection-root", type=Path)
    parser.add_argument("--projection-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--include-serial", action="store_true", help="After three four-worker runs, require all three serial CPU discoveries")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(sys.platform == "linux" and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "Linux retained pidfd support required")
    if args.worker is not None:
        return child(args.worker.resolve())
    require(args.baseline_root is not None and args.current_root is not None and args.projection_root is not None and args.output is not None,
            "Three explicit runtime roots and fresh output required")
    modes = list(MODES) if args.include_serial else ["four-worker"]
    roots = {"baseline": args.baseline_root.resolve(), "current": args.current_root.resolve(), "projection": args.projection_root.resolve()}
    require(len(set(roots.values())) == 3, "Three separate source checkouts required")
    commits = {"baseline": BASELINE, "current": CURRENT, "projection": args.projection_commit}
    deadline = time.monotonic() + TOTAL_SECONDS
    sources = {label: {**source(root, commits[label], deadline=deadline), "variant": label, "revision": REVISIONS[label]}
               for label, root in roots.items()}
    trees = projection_tree(roots["projection"], commits["projection"], deadline=deadline)
    harness = roots["current"] / ".github" / "scripts" / "benchmark_enterprise_finance.py"
    require(digest(harness) == HARNESS_SHA, "Unchanged final22 common harness required")
    output = args.output.resolve()
    require(not output.exists() and all(not output.is_relative_to(root) or output.is_relative_to(root / "output") for root in roots.values()),
            "Fresh ignored/outside-source output required")
    output.mkdir(parents=True)
    report: dict[str, Any] = {"schema_version": "wave5-linux-profile-diagnostics-v1", "status": "failed",
                             "started_at": datetime.now(UTC).isoformat(), "sources": sources, "projection_tree": trees,
                             "harness_sha256": HARNESS_SHA, "launcher_sha256": digest(Path(__file__)),
                             "python_executable": str(Path(sys.executable).resolve()), "python_executable_sha256": digest(Path(sys.executable).resolve()),
                             "python": sys.version, "business_seconds": BUSINESS_SECONDS, "child_seconds": CHILD_SECONDS,
                             "overall_seconds": TOTAL_SECONDS, "cleanup_reserve_seconds": RESERVE, "runs": [],
                             "performance_comparison_accepted": False, "limits": [
                                 "Instrumented diagnostics only; fresh ephemeral Linux runner differs from original Windows hardware.",
                                 "Identity-enter includes connection/KDF/scope/permissions/commit; no direct auth SQL split.",
                                 "Phase wall sums overlap across workers; thread CPU excludes other worker threads.",
                                 "Client process CPU includes observer thread; cProfile wall includes blocking/I/O and covers at most32 serial cycles.",
                                 "Restricted-role nested pg_stat_statements times overlap; do not sum into wall time or infer backend CPU.",
                                 "Container and client CPU observation windows differ; no aggregate whole-host/process-tree CPU or monetary cost.",
                                 "Resource peaks are sampled and can miss spikes; startup/migration/masters are outside posting CPU windows."]}
    try:
        for mode in modes:
            for label, root in roots.items():
                value = one(root, sources[label], harness, mode, output / f"{mode}-{label}", deadline=deadline)
                report["runs"].append({"variant": label, "mode": mode, "status": value["status"],
                                       "diagnostic_sha256": digest(output / f"{mode}-{label}" / "diagnostic.json")})
                require(value["status"] == "passed", "Stopped after original failed/incomplete diagnostic; no next child admitted")
        require(len(report["runs"]) == 3 * len(modes), "Incomplete selected diagnostic population")
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        report["failure_type"] = type(exc).__name__
        report["failure"] = str(exc)
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        save(output / "diagnostics.json", report)
    print(json.dumps({"status": report["status"], "runs": len(report["runs"]), "performance_comparison_accepted": False}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
