"""Bounded real HTTPS IC1 cycles; independent native-book proof, no superiority claim.

Each sequential cycle uses a fresh synthetic tenant and three explicitly authorized
books. Master data and independently reviewed report maps are seeded BEFORE timing;
all recognition, partial settlement and native elimination effects use the normal
API. Authentication/step-up are timed. No auth token, password or DSN is exported.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
import os
import secrets
import socket
import ssl
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3"
API = "/api/v1/intercompany-operations"
SERVER = """import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from reconforge.api import create_api_app
import uvicorn
app=create_api_app(Path(sys.argv[2])/'local.db',tenant_db_root=Path(sys.argv[2])/'tenants',
    postgres_dsn=os.environ['IC_API_APP_DSN'],postgres_require_tls=False,
    allowed_hosts=('localhost',),secure_transport=True)
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[3]),ssl_certfile=sys.argv[4],
    ssl_keyfile=sys.argv[5],log_level='warning')
"""


def utc() -> str:
    return datetime.now(UTC).isoformat()


def save(path: Path, value: Any) -> str:
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None,
            timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=check)  # nosec B603


def source_state(root: Path) -> dict[str, Any]:
    names = command(["git", "ls-files", "-z"], cwd=root).stdout.split("\0")
    digest = hashlib.sha256()
    for name in sorted(filter(None, names)):
        digest.update(name.encode())
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    return {"commit": command(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip(),
            "tracked_sha256": digest.hexdigest(),
            "tracked_status": command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root).stdout}


def summary(values: list[float]) -> dict[str, Any]:
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Complete nonnegative finite raw latency observations required")
    ordered = sorted(values)

    def percentile(p: float) -> float:
        position = (len(ordered) - 1) * p
        lower = math.floor(position)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)

    return {"count": len(values), "p50_seconds": percentile(.5), "p95_seconds": percentile(.95),
            "p99_seconds": percentile(.99), "raw_seconds": values,
            "method": "linear interpolation at (n-1)*p; seconds are engineering observations"}


def process_observation(pid: int) -> dict[str, Any]:
    """Read the actual server process; unavailable counters remain explicit nulls."""
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            class Memory(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                            *[(name, ctypes.c_size_t) for name in ("peak", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]

            loader_name = "WinDLL"  # Native API is absent from non-Windows ctypes stubs.
            loader = getattr(ctypes, loader_name)
            kernel = loader("kernel32", use_last_error=True)
            psapi = loader("psapi", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
            kernel.GetProcessTimes.restype = wintypes.BOOL
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                raise OSError("Server process observation unavailable")
            try:
                creation, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
                memory = Memory()
                memory.cb = ctypes.sizeof(memory)
                if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)) or not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                    raise OSError("Server process observation refused")
                def ticks(value: Any) -> int:
                    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
                return {"status": "available", "pid": pid, "cpu_seconds": (ticks(system) + ticks(user)) / 10_000_000,
                        "rss_bytes": int(memory.rss), "process_lifetime_peak_rss_bytes": int(memory.peak)}
            finally:
                kernel.CloseHandle(handle)
        if sys.platform.startswith("linux"):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return {"status": "available", "pid": pid,
                    "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
                    "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"), "process_lifetime_peak_rss_bytes": None}
        raise OSError("Unsupported server observation platform")
    except (OSError, AttributeError, ValueError, IndexError) as exc:
        return {"status": "unavailable", "pid": pid, "cpu_seconds": None, "rss_bytes": None,
                "process_lifetime_peak_rss_bytes": None, "exception_type": type(exc).__name__}


def cpu_delta(before: dict[str, Any], after: dict[str, Any]) -> float:
    if before.get("status") != "available" or after.get("status") != "available" or before.get("pid") != after.get("pid"):
        raise ValueError("Server CPU observation unavailable or changed process")
    difference = after["cpu_seconds"] - before["cpu_seconds"]
    if not math.isfinite(difference) or difference < 0:
        raise ValueError("Server CPU counters are nonmonotonic")
    return float(difference)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class Client:
    def __init__(self, base: str, context: ssl.SSLContext, rows: list[dict[str, Any]], cycle: int) -> None:
        self.base, self.rows, self.cycle = base, rows, cycle
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())

    def request(self, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith("/api/v1/") or ".." in path or "\n" in path:
            raise ValueError("Only fixed local API paths admitted")
        raw = None if body is None else json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        req = urllib.request.Request(self.base + path, data=raw, headers={"Content-Type": "application/json", **headers}, method="GET" if raw is None else "POST")
        row: dict[str, Any] = {"cycle": self.cycle, "method": req.method, "path": path, "started_at": utc(), "status": None}
        started = time.perf_counter()
        try:
            with self.opener.open(req, timeout=45) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
                row.update(status=response.status, response_bytes=len(payload))
                if response.status != 200 or len(payload) > 16 * 1024 * 1024:
                    raise ValueError("Unexpected or oversized API response")
                result = json.loads(payload)
                if not isinstance(result, dict):
                    raise ValueError("Object API response required")
                return result
        except urllib.error.HTTPError as exc:
            row.update(status=exc.code, exception_type=type(exc).__name__)
            raise RuntimeError(f"API status{exc.code} refused at{path}") from None
        except Exception as exc:
            row["exception_type"] = type(exc).__name__
            raise
        finally:
            row["seconds"] = time.perf_counter() - started
            self.rows.append(row)

    def login(self, tenant: str, username: str, password: str) -> dict[str, str]:
        identity = self.request("/api/v1/auth/login", {"X-ReconForge-Tenant": tenant}, {"username": username, "password": password})
        headers = {"X-ReconForge-Tenant": tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org",
                   "Authorization": "Bearer " + identity["access_token"]}
        self.request("/api/v1/auth/step-up", headers, {"password": password})
        return headers


def execute_cycle(client: Client, runtime: Any, index: int, directory: Path, oracle: Any) -> dict[str, Any]:
    directory.mkdir()
    started, client_cpu = time.perf_counter(), time.process_time()
    humans = {role: client.login(runtime.tenant, "browser-" + role, runtime.password) for role in ("maker", "checker", "poster")}
    original, cash = 10001 + 17 * index, 3000 + 3 * index
    body = {"command_id": f"cycle-{index}-recognize", "seller_entity_id": "entity", "buyer_entity_id": "buyer", "adjustment_entity_id": "group",
            "reference": f"API-IC1-{index:08d}", "amount_minor": str(original), "period_id": "period", "posting_date": "2026-10-03", "journal_code": "STOCK",
            "receivable_account_code": "IC_AR", "payable_account_code": "IC_AP", "revenue_account_code": "IC_REVENUE", "expense_account_code": "IC_EXPENSE",
            "cash_account_code": "CASH", "reason": "Synthetic actual HTTPS paired recognition"}
    source_id = ""
    proofs = []
    for stage, kind in enumerate(("recognize", "settle", "eliminate")):
        if stage == 0:
            plan = client.request(API + "/sources", humans["maker"], body)["plan"]
            source_id = plan["source_id"]
        else:
            change = {"command_id": f"cycle-{index}-{kind}", "period_id": "period", "posting_date": f"2026-10-0{stage + 3}", "reason": "Synthetic actual HTTPS " + kind}
            if stage == 1:
                change["amount_minor"] = str(cash)
            path = API + f"/sources/{source_id}/" + ("settlements" if stage == 1 else "eliminations")
            plan = client.request(path, humans["maker"], change)["plan"]
        for phase, role in (("review", "checker"), ("post", "poster")):
            plan = client.request(API + f"/plans/{plan['id']}/{phase}", humans[role],
                                  {"command_id": f"cycle-{index}-{kind}-{phase}", "expected_plan_digest": plan["plan_digest"], "reason": "Independent synthetic " + role})["plan"]
        proof = client.request(API + f"/plans/{plan['id']}/evidence", humans["poster"])["evidence"]
        proofs.append(proof)
        save(directory / f"ic-proof-{stage}.json", proof)
    maps = client.request(API + "/catalog", humans["poster"])["catalog"]["maps"]
    selected = {item["legal_entity_id"]: item["id"] for item in maps}
    query = urllib.parse.urlencode({"seller_map_id": selected["entity"], "buyer_map_id": selected["buyer"], "adjustment_map_id": selected["group"],
                                    "period_id": "period", "as_of_date": "2026-10-05"})
    report = client.request(API + f"/sources/{source_id}/report?" + query, humans["poster"])["report"]
    seconds, cpu = time.perf_counter() - started, time.process_time() - client_cpu
    save(directory / "ic-group-report.json", report)
    validation_started = time.perf_counter()
    financial = oracle.verify(proofs, report)
    hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in oracle.FILES}
    save(directory / "independent-oracle.json", {**financial, "inputs_sha256": hashes})
    return {"index": index, "tenant_id": runtime.tenant, "source_id": source_id, "seconds": seconds, "client_cpu_seconds": cpu,
            "original_minor": str(original), "partial_cash_minor": str(cash), "native_effects": financial["native_effects"],
            "financial_verification": financial["financial_verification"], "proofs_sha256": hashes,
            "independent_oracle_seconds": time.perf_counter() - validation_started}


def require_completion(report: dict[str, Any]) -> None:
    cycles, count = report["cycles"], report["configuration"]["cycles"]
    if type(count) is not int or len(cycles) != count or any(type(row["index"]) is not int for row in cycles) or {row["index"] for row in cycles} != set(range(count)) or any(row["financial_verification"] != "passed" for row in cycles):
        raise ValueError("Every requested original cycle and independent financial proof required")
    ids = [row["effect_id"] for cycle in cycles for row in cycle["native_effects"]]
    if len(ids) != count * 5 or any(len(row["native_effects"]) != 5 for row in cycles) or any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(ids) != len(set(ids)) or len({row["tenant_id"] for row in cycles}) != count or len({row["source_id"] for row in cycles}) != count:
        raise ValueError("Fresh unique tenants and five original native effects per cycle required")
    requests = report["requests"]
    if len(requests) != count * 20 or any(type(row["cycle"]) is not int or row["cycle"] not in range(count) or row["status"] != 200 or "exception_type" in row for row in requests) or any(sum(row["cycle"] == index for row in requests) != 20 for index in range(count)):
        raise ValueError("Exactly twenty successful actual HTTPS requests per cycle required")
    if report["resource_samples"]["status"] != "complete" or report["source_before"] != report["source_after"] or report["source_after"]["tracked_status"]:
        raise ValueError("Complete resource observation and unchanged clean source required")
    if not report["owned_container_removed"] or not report["owned_https_process_stopped"]:
        raise ValueError("Owned process and container cleanup required")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--postgres-cpus", type=int, default=2)
    parser.add_argument("--postgres-memory-mib", type=int, default=1024)
    parser.add_argument("--sample-seconds", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 50 or not 60 <= args.max_seconds <= 1800 or not 1 <= args.postgres_cpus <= 4 or not 512 <= args.postgres_memory_mib <= 4096 or not 1 <= args.sample_seconds <= 60:
        parser.error("Explicit bounded cycles, deadline, CPU, RAM and sample interval required")
    runtime_root, output = args.runtime_root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(runtime_root))
    import psycopg
    from psycopg import sql

    from reconforge.benchmark.container_resource_counters import PATHS, parse_counters
    from reconforge.benchmark.resource_sampling import ResourceSampler
    create_localhost_certificate = importlib.import_module("tests.https_runtime").create_localhost_certificate
    seed_intercompany_browser = importlib.import_module("tests.intercompany_operations_browser_seed").seed_intercompany_browser

    spec = importlib.util.spec_from_file_location("independent_intercompany_oracle", Path(__file__).with_name("verify_intercompany_cycle_oracle.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Independent stdlib oracle unavailable")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    report: dict[str, Any] = {"schema_version": "intercompany-https-benchmark-v1", "started_at": utc(), "status": "failed", "image": IMAGE,
        "configuration": {"cycles": args.cycles, "workers": 1, "warmup_cycles": 0, "max_seconds": args.max_seconds,
            "postgres_cpus": args.postgres_cpus, "postgres_memory_mib": args.postgres_memory_mib, "sample_seconds": args.sample_seconds},
        "measurement_scope": "Sequential fresh synthetic tenant per cycle; masters/maps seeded before timing; login+step-up+three-human business+proof/report HTTPS timed; urllib opens fresh connections; no retries",
        "performance_comparison_accepted": False, "cost_per_transaction": None, "rpo": None, "rto": None,
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "oracle_sha256": hashlib.sha256(Path(str(oracle.__file__)).read_bytes()).hexdigest(),
        "runtime_root": str(runtime_root), "requests": [], "cycles": [], "owned_container_removed": False, "owned_https_process_stopped": False}
    server: subprocess.Popen[str] | None = None
    sampler: Any = None
    container = ""
    temporary_directory = tempfile.TemporaryDirectory(prefix="reconforge-ic-api-")
    name = "reconforge-ic-api-" + uuid4().hex
    secrets_to_redact: list[str] = []
    environment = os.environ.copy()
    total_started = time.monotonic()

    def counters() -> dict[str, Any]:
        raw = {key: command(["docker", "exec", container, "cat", path], timeout=15).stdout for key, path in PATHS.items()}
        return {"observed_at": utc(), "raw": raw, "parsed": parse_counters(raw)}

    try:
        report["source_before"] = source_state(runtime_root)
        if report["source_before"]["tracked_status"]:
            raise ValueError("Frozen clean runtime checkout required")
        password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        secrets_to_redact.extend((password, app_password))
        environment["POSTGRES_PASSWORD"] = password
        container = command(["docker", "run", "--detach", "--rm", "--name", name, "--label", "reconforge.ic_api_benchmark=owned",
                             "--cpus", str(args.postgres_cpus), "--memory", f"{args.postgres_memory_mib}m", "--env", "POSTGRES_PASSWORD",
                             "--publish", "127.0.0.1::5432", IMAGE], env=environment).stdout.strip()
        report["owned_container_id"] = container
        port = command(["docker", "port", container, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        admin_dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
        app_dsn = f"postgresql://ic_api_app:{app_password}@127.0.0.1:{port}/postgres"
        secrets_to_redact.extend((admin_dsn, app_dsn))
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(admin_dsn, connect_timeout=2) as connection:
                    connection.execute(sql.SQL("CREATE ROLE ic_api_app LOGIN PASSWORD {}").format(sql.Literal(app_password)))
                    version = connection.execute("SHOW server_version").fetchone()
                    if version is None:
                        raise ValueError("Native server version missing")
                    report["postgres_version"] = version[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.2)
        environment["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        migrated = command([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=runtime_root, env=environment, timeout=180)
        (output / "migration.log").write_text(migrated.stdout + migrated.stderr, encoding="utf-8")
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("GRANT USAGE ON SCHEMA reconforge TO ic_api_app")
            connection.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO ic_api_app")
            connection.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO ic_api_app")
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision is None:
                raise ValueError("Native schema revision missing")
            report["revision"] = revision[0]
            report["durability"] = {}
            for setting in ("fsync", "synchronous_commit", "full_page_writes"):
                value = connection.execute(sql.SQL("SHOW {}").format(sql.Identifier(setting))).fetchone()
                if value is None:
                    raise ValueError("Native durability observation missing")
                report["durability"][setting] = value[0]
        if set(report["durability"].values()) != {"on"}:
            raise ValueError("Full native durability required")
        with psycopg.connect(app_dsn) as connection:
            flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            if flags is None:
                raise ValueError("Native application role observation missing")
            report["app_role_flags"] = list(flags)
        if report["app_role_flags"] != [False, False]:
            raise ValueError("Non-superuser, non-bypass-RLS application required")
        seed_started = time.perf_counter()
        runtimes = [seed_intercompany_browser(admin_dsn, app_dsn) for _ in range(args.cycles)]
        secrets_to_redact.extend(runtime.password for runtime in runtimes)
        report["master_seed_seconds"] = time.perf_counter() - seed_started
        with (output / "https-runtime.log").open("w", encoding="utf-8") as log:
            temporary = Path(temporary_directory.name)
            certificate, key = create_localhost_certificate(temporary)
            report["tls"] = {"verification": "generated localhost certificate trusted explicitly; hostname and chain verified", "certificate_sha256": hashlib.sha256(certificate.read_bytes()).hexdigest()}
            context = ssl.create_default_context(cafile=str(certificate))
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                https_port = listener.getsockname()[1]
            environment["IC_API_APP_DSN"] = app_dsn
            server = subprocess.Popen([sys.executable, "-c", SERVER, str(runtime_root), str(temporary), str(https_port), str(certificate), str(key)],  # nosec B603
                cwd=runtime_root, env=environment, stdout=log, stderr=subprocess.STDOUT, text=True)
            url = f"https://localhost:{https_port}"
            readiness = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Owned HTTPS runtime exited; inspect retained runtime log")
                try:
                    with urllib.request.urlopen(url + "/api/v1/health", context=context, timeout=1) as response:  # nosec B310
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > readiness:
                        raise RuntimeError("Verified HTTPS readiness timeout") from None
                    time.sleep(.2)
            report["db_counters_before"] = counters()
            report["server_process_before"] = process_observation(server.pid)
            sampler = ResourceSampler(lambda: {"server_process": process_observation(server.pid)}, interval_seconds=args.sample_seconds,
                                      max_samples=args.max_seconds // args.sample_seconds + 2)
            sampler.start()
            measured_started, cpu_started = time.perf_counter(), time.process_time()
            for index, runtime in enumerate(runtimes):
                if time.monotonic() - total_started > args.max_seconds:
                    raise RuntimeError("Bounded admission deadline exhausted before requested cycles completed")
                row = execute_cycle(Client(url, context, report["requests"], index), runtime, index, output / f"cycle-{index:04d}", oracle)
                report["cycles"].append(row)
                save(output / "progress.json", {"schema_version": report["schema_version"], "completed_cycles": len(report["cycles"]), "cycles": report["cycles"], "requests": report["requests"]})
            report["measurement_seconds"] = time.perf_counter() - measured_started
            report["client_cpu_seconds"] = time.process_time() - cpu_started
            report["resource_samples"] = sampler.stop()
            sampler = None
            report["server_process_after"] = process_observation(server.pid)
            report["server_cpu_seconds"] = cpu_delta(report["server_process_before"], report["server_process_after"])
            report["db_counters_after"] = counters()
            delta = report["db_counters_after"]["parsed"]["cpu_microseconds"]["usage_usec"] - report["db_counters_before"]["parsed"]["cpu_microseconds"]["usage_usec"]
            if delta < 0:
                raise ValueError("Database CPU counters nonmonotonic")
            report["database_cpu_seconds"] = delta / 1_000_000
            report["cycle_latencies"] = summary([row["seconds"] for row in report["cycles"]])
            report["request_latencies"] = summary([row["seconds"] for row in report["requests"]])
            report["resource_scope"] = "Server GetProcessTimes or /proc CPU; client process_time includes observer thread; PostgreSQL cgroup CPU includes read-only exec counter overhead; RSS samples can miss spikes; startup/migration/master seed excluded from CPU deltas, lifetime peak includes them"
    except Exception as exc:
        diagnostic = str(exc)
        for secret in secrets_to_redact:
            diagnostic = diagnostic.replace(secret, "[redacted]")
        report.update(error_type=type(exc).__name__, error=diagnostic)
    finally:
        if sampler is not None:
            report["resource_samples"] = sampler.stop()
        if server is not None:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            report["owned_https_process_stopped"] = server.poll() is not None
        temporary_directory.cleanup()
        if container:
            observed = command(["docker", "inspect", "--format", "{{.Id}}", name], check=False)
            if observed.returncode == 0 and observed.stdout.strip() == container:
                command(["docker", "stop", "--time", "5", container], check=False)
                for _ in range(30):
                    if command(["docker", "inspect", container], check=False).returncode != 0:
                        report["owned_container_removed"] = True
                        break
                    time.sleep(.1)
        report["source_after"] = source_state(runtime_root)
        report["finished_at"] = utc()
        report["elapsed_seconds"] = time.monotonic() - total_started
        try:
            if "error_type" in report:
                raise ValueError("Original failure retained")
            require_completion(report)
            report.update(status="passed", financial_verification="passed", successful_cycles=len(report["cycles"]),
                          native_posting_effects=5 * len(report["cycles"]))
        except (KeyError, ValueError) as exc:
            report.setdefault("acceptance_error", str(exc))
        digest = save(output / "result.json", report)
        print(json.dumps({"status": report["status"], "report": str(output / "result.json"), "sha256": digest,
                          "completed_cycles": len(report["cycles"]), "elapsed_seconds": report["elapsed_seconds"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
