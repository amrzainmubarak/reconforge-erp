"""Shared bounded native HTTPS observation runtime; financial checks remain owned.

No business source is prepared here. A typed scenario seeds explicit masters, runs
actual API actions, and independently verifies its own native financial population.
This runner owns frozen-source, TLS, resource observation and cleanup contracts.
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
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3"
SERVER = """import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from reconforge.api import create_api_app
import uvicorn
Path(sys.argv[2],'server-identity.json').write_text(json.dumps({'schema_version':'owned-native-api-process-v1',
    'run_id':sys.argv[6],'pid':os.getpid(),'runtime_root':str(Path(sys.argv[1]).resolve()),
    'api_module_file':str(Path(sys.modules[create_api_app.__module__].__file__).resolve()),
    'python_version':sys.version,'executable':sys.executable}),encoding='utf-8')
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
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                raise OSError("Server process observation unavailable")
            try:
                creation, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
                exit_code = wintypes.DWORD()
                memory = Memory()
                memory.cb = ctypes.sizeof(memory)
                if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)) or not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                    raise OSError("Server process observation refused")
                def ticks(value: Any) -> int:
                    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
                return {"status": "available", "pid": pid, "cpu_seconds": (ticks(system) + ticks(user)) / 10_000_000,
                        "rss_bytes": int(memory.rss), "process_lifetime_peak_rss_bytes": int(memory.peak),
                        "birth_identity": str(ticks(creation)), "running": exit_code.value == 259}
            finally:
                kernel.CloseHandle(handle)
        if sys.platform.startswith("linux"):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return {"status": "available", "pid": pid,
                    "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
                    "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"), "process_lifetime_peak_rss_bytes": None,
                    "birth_identity": fields[19], "running": fields[0] not in {"Z", "X"}}
        raise OSError("Unsupported server observation platform")
    except (OSError, AttributeError, ValueError, IndexError) as exc:
        return {"status": "unavailable", "pid": pid, "cpu_seconds": None, "rss_bytes": None,
                "process_lifetime_peak_rss_bytes": None, "exception_type": type(exc).__name__}


def cpu_delta(before: dict[str, Any], after: dict[str, Any]) -> float:
    if before.get("status") != "available" or after.get("status") != "available" or before.get("pid") != after.get("pid"):
        raise ValueError("Server CPU observation unavailable or changed process")
    if before.get("birth_identity") != after.get("birth_identity") or before.get("running") is False or after.get("running") is False:
        raise ValueError("Server process lifetime changed during measurement")
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
            try:
                error = json.loads(exc.read(4096))
                fields = error.get("error", {}) if isinstance(error, dict) else {}
                if isinstance(fields, dict):
                    selected = {key: value for key, value in fields.items() if key in {"code", "message", "request_id"} and isinstance(value, str)}
                    authorization = headers.get("Authorization", "")
                    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
                    redactions = [authorization, token, *(str(value) for key, value in (body or {}).items() if key in {"password", "access_token", "refresh_token"})]
                    for key, value in selected.items():
                        for secret in filter(None, redactions):
                            value = value.replace(secret, "[redacted]")
                        selected[key] = value
                    row["api_error"] = selected
            except (ValueError, OSError):
                row["error_body_status"] = "unavailable_or_not_json"
            raise RuntimeError(f"API status{exc.code} refused at{path}") from None
        except Exception as exc:
            row["exception_type"] = type(exc).__name__
            raise
        finally:
            row["seconds"] = time.perf_counter() - started
            self.rows.append(row)

    def login(self, tenant: str, username: str, password: str, *, entity_id: str | None = None) -> dict[str, str]:
        identity = self.request("/api/v1/auth/login", {"X-ReconForge-Tenant": tenant}, {"username": username, "password": password})
        headers = {"X-ReconForge-Tenant": tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org",
                   "Authorization": "Bearer " + identity["access_token"]}
        if entity_id is not None:
            headers["X-ReconForge-Legal-Entity"] = entity_id
        self.request("/api/v1/auth/step-up", headers, {"password": password})
        return headers


class NativeApiScenario(Protocol):
    name: str
    schema_version: str
    tool_path: Path
    oracle_path: Path
    expected_requests_per_cycle: int
    measurement_scope: str

    def seed(self, admin_dsn: str, app_dsn: str) -> Any: ...
    def execute_cycle(self, client: Client, runtime: Any, index: int, directory: Path) -> dict[str, Any]: ...
    def require_financial_completion(self, report: dict[str, Any]) -> None: ...
    def financial_summary(self, report: dict[str, Any]) -> dict[str, Any]: ...


def require_server_identity(identity: dict[str, Any], root: Path, run_id: str) -> int:
    if identity.get("schema_version") != "owned-native-api-process-v1" or identity.get("run_id") != run_id or type(identity.get("pid")) is not int or identity["pid"] <= 0 or identity["pid"] == os.getpid():
        raise ValueError("Actual owned API process identity required")
    if Path(identity["runtime_root"]).resolve() != root or not Path(identity["api_module_file"]).resolve().is_relative_to(root):
        raise ValueError("API module origin must be within the frozen runtime checkout")
    return int(identity["pid"])


def process_is_stopped(pid: int) -> bool | None:
    """Distinguish a missing/exited process from an unavailable observation."""
    try:
        if os.name == "nt":
            from ctypes import wintypes

            loader_name = "WinDLL"
            kernel = getattr(ctypes, loader_name)("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                error_api = "get_last_error"
                return True if getattr(ctypes, error_api)() == 87 else None
            try:
                code = wintypes.DWORD()
                return code.value != 259 if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
            finally:
                kernel.CloseHandle(handle)
        if sys.platform.startswith("linux"):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return fields[0] in {"Z", "X"}
        return None
    except FileNotFoundError:
        return True
    except (OSError, AttributeError, IndexError):
        return None


def stop_server(server: subprocess.Popen[str], actual_process: dict[str, Any] | None = None) -> bool:
    if server.poll() is None:
        # Windows venv redirectors can retain a separate interpreter child.
        # The tree is rooted only at the Popen process owned by this run.
        if os.name == "nt":
            command(["taskkill", "/PID", str(server.pid), "/T", "/F"], check=False, timeout=15)
        else:
            server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
    if server.poll() is None:
        return False
    if actual_process is None:
        return True
    pid = actual_process["pid"]
    if process_is_stopped(pid) is True:
        return True
    # An already-exited venv redirector can leave its owned child alive. Check
    # retained birth identity before terminating that exact interpreter tree.
    live = process_observation(pid)
    if live.get("status") != "available" or not actual_process.get("birth_identity") or live.get("birth_identity") != actual_process["birth_identity"]:
        return False
    if os.name == "nt":
        command(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, timeout=15)
    else:
        import signal

        os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if process_is_stopped(pid) is True:
            return True
        time.sleep(.1)
    return False


def require_common_completion(report: dict[str, Any], expected_requests_per_cycle: int) -> None:
    count = report["configuration"]["cycles"]
    requests = report["requests"]
    if type(count) is not int or not 1 <= count <= 50:
        raise ValueError("Exact bounded requested cycle count required")
    if type(expected_requests_per_cycle) is not int or not 1 <= expected_requests_per_cycle <= 200:
        raise ValueError("Explicit bounded scenario request contract required")
    if len(requests) != count * expected_requests_per_cycle or any(type(row["cycle"]) is not int or row["cycle"] not in range(count) or row["status"] != 200 or "exception_type" in row for row in requests) or any(sum(row["cycle"] == index for row in requests) != expected_requests_per_cycle for index in range(count)):
        raise ValueError("Every declared actual HTTPS request must complete successfully")
    if report["resource_samples"]["status"] != "complete" or report["source_before"] != report["source_after"] or report["source_after"]["tracked_status"]:
        raise ValueError("Complete resource observation and unchanged clean source required")
    if not report["owned_container_removed"] or not report["owned_https_process_stopped"]:
        raise ValueError("Owned process and container cleanup required")


def complete_report(report: dict[str, Any], scenario: NativeApiScenario) -> None:
    if "error_type" in report or report.get("cleanup_errors"):
        raise ValueError("Original runtime or cleanup failure retained")
    require_common_completion(report, scenario.expected_requests_per_cycle)
    scenario.require_financial_completion(report)
    financial = scenario.financial_summary(report)
    if set(financial) != {"financial_verification", "successful_cycles", "native_posting_effects", "timed_native_posting_effects"} or financial["financial_verification"] != "passed" or type(financial["successful_cycles"]) is not int or financial["successful_cycles"] != len(report["cycles"]):
        raise ValueError("Scenario financial completion summary is missing or malformed")
    total, timed = financial["native_posting_effects"], financial["timed_native_posting_effects"]
    if type(total) is not int or type(timed) is not int or not 0 < timed <= total:
        raise ValueError("Explicit positive native and timed financial effect counts required")
    report.update(financial)
    report["status"] = "passed"


def run(scenario: NativeApiScenario, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=scenario.measurement_scope)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--postgres-cpus", type=int, default=2)
    parser.add_argument("--postgres-memory-mib", type=int, default=1024)
    parser.add_argument("--sample-seconds", type=int, default=5)
    args = parser.parse_args(argv)
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

    report: dict[str, Any] = {"schema_version": scenario.schema_version, "scenario": scenario.name, "started_at": utc(), "status": "failed", "image": IMAGE,
        "configuration": {"cycles": args.cycles, "workers": 1, "warmup_cycles": 0, "max_seconds": args.max_seconds,
            "postgres_cpus": args.postgres_cpus, "postgres_memory_mib": args.postgres_memory_mib, "sample_seconds": args.sample_seconds},
        "measurement_scope": scenario.measurement_scope,
        "performance_comparison_accepted": False, "cost_per_transaction": None, "rpo": None, "rto": None,
        "tool_sha256": hashlib.sha256(scenario.tool_path.read_bytes()).hexdigest(), "common_runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "oracle_sha256": hashlib.sha256(scenario.oracle_path.read_bytes()).hexdigest(),
        "runtime_root": str(runtime_root), "requests": [], "cycles": [], "owned_container_removed": False, "owned_https_process_stopped": False}
    server: subprocess.Popen[str] | None = None
    sampler: Any = None
    container = ""
    temporary_directory = tempfile.TemporaryDirectory(prefix="reconforge-ic-api-")
    run_id = uuid4().hex
    name = "reconforge-native-api-" + run_id
    secrets_to_redact: list[str] = []
    environment = os.environ.copy()
    total_started = time.monotonic()

    def counters() -> dict[str, Any]:
        raw = {key: command(["docker", "exec", container, "cat", path], timeout=15).stdout for key, path in PATHS.items()}
        return {"observed_at": utc(), "raw": raw, "parsed": parse_counters(raw)}

    def cleanup(stage: str, action: Any) -> None:
        try:
            action()
        except Exception as exc:
            report.setdefault("cleanup_errors", []).append({"stage": stage, "exception_type": type(exc).__name__})

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
        runtimes = [scenario.seed(admin_dsn, app_dsn) for _ in range(args.cycles)]
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
            server = subprocess.Popen([sys.executable, "-c", SERVER, str(runtime_root), str(temporary), str(https_port), str(certificate), str(key), run_id],  # nosec B603
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
            identity = json.loads((temporary / "server-identity.json").read_bytes())
            server_pid = require_server_identity(identity, runtime_root, run_id)
            report["actual_api_process"] = identity
            report["launcher_pid"] = server.pid
            save(output / "server-identity.json", identity)
            report["db_counters_before"] = counters()
            report["server_process_before"] = process_observation(server_pid)
            if report["server_process_before"].get("status") != "available" or report["server_process_before"].get("running") is not True:
                raise ValueError("Actual API interpreter observation unavailable")
            def observe_server() -> dict[str, Any]:
                observation = process_observation(server_pid)
                if observation.get("status") != "available" or observation.get("running") is not True or observation.get("birth_identity") != report["server_process_before"]["birth_identity"]:
                    raise ValueError("Actual server process observation unavailable or replaced")
                return {"server_process": observation}
            sampler = ResourceSampler(observe_server, interval_seconds=args.sample_seconds,
                                      max_samples=args.max_seconds // args.sample_seconds + 2)
            sampler.start()
            measured_started, cpu_started = time.perf_counter(), time.process_time()
            for index, runtime in enumerate(runtimes):
                if time.monotonic() - total_started > args.max_seconds:
                    raise RuntimeError("Bounded admission deadline exhausted before requested cycles completed")
                row = scenario.execute_cycle(Client(url, context, report["requests"], index), runtime, index, output / f"cycle-{index:04d}")
                report["cycles"].append(row)
                save(output / "progress.json", {"schema_version": report["schema_version"], "completed_cycles": len(report["cycles"]), "cycles": report["cycles"], "requests": report["requests"]})
            report["measurement_seconds"] = time.perf_counter() - measured_started
            report["client_cpu_seconds"] = time.process_time() - cpu_started
            report["resource_samples"] = sampler.stop()
            sampler = None
            report["server_process_after"] = process_observation(server_pid)
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
            cleanup("sampler", lambda: report.update(resource_samples=sampler.stop()))
        if server is not None:
            cleanup("https_process", lambda: report.update(owned_https_process_stopped=stop_server(server, report.get("server_process_before"))))
        cleanup("temporary_directory", temporary_directory.cleanup)
        def remove_container() -> None:
            observed = command(["docker", "inspect", "--format", "{{.Id}}", name], check=False)
            if observed.returncode == 0 and observed.stdout.strip() == container:
                command(["docker", "stop", "--time", "5", container], check=False)
                for _ in range(30):
                    if command(["docker", "inspect", container], check=False).returncode != 0:
                        report["owned_container_removed"] = True
                        break
                    time.sleep(.1)
        if container:
            cleanup("postgres_container", remove_container)
        cleanup("source_after", lambda: report.update(source_after=source_state(runtime_root)))
        report["finished_at"] = utc()
        report["elapsed_seconds"] = time.monotonic() - total_started
        try:
            complete_report(report, scenario)
        except Exception as exc:
            report.setdefault("acceptance_error_type", type(exc).__name__)
            report.setdefault("acceptance_error", "Runtime, resource or owned financial completion contract refused")
        digest = save(output / "result.json", report)
        print(json.dumps({"status": report["status"], "report": str(output / "result.json"), "sha256": digest,
                          "completed_cycles": len(report["cycles"]), "elapsed_seconds": report["elapsed_seconds"]}))
    return 0 if report["status"] == "passed" else 1

