"""Bounded driver contracts; synthetic independent financial proof, no runtime jobs."""
import copy
import importlib.util
import io
import json
import ssl
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_intercompany_cycle_oracle import oracle, packets

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/benchmark_intercompany_api.py"
SPEC = importlib.util.spec_from_file_location("intercompany_api_driver", SCRIPT)
assert SPEC and SPEC.loader
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)
common = importlib.import_module("benchmark_native_api_runtime")


def accepted() -> dict[str, Any]:
    return {"configuration": {"cycles": 2},
        "cycles": [{"index": index, "source_id": f"source-{index}", "tenant_id": f"tenant-{index}", "financial_verification": "passed",
                    "native_effects": [{"effect_id": f"effect-{index}-{number}"} for number in range(5)]} for index in range(2)],
        "requests": [{"cycle": index, "status": 200} for index in range(2) for _ in range(20)],
        "resource_samples": {"status": "complete"}, "source_before": {"commit": "frozen", "tracked_status": ""},
        "source_after": {"commit": "frozen", "tracked_status": ""}, "owned_container_removed": True, "owned_https_process_stopped": True}


def test_percentiles_use_original_vectors_and_refuse_missing_or_nonfinite() -> None:
    result = common.summary([9., 1., 5.])
    assert result["raw_seconds"] == [9., 1., 5.] and result["p50_seconds"] == 5.
    assert result["p95_seconds"] == pytest.approx(8.6) and result["p99_seconds"] == pytest.approx(8.92)
    for values in ([], [-1.], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            common.summary(values)


@pytest.mark.parametrize("mutation", ["missing_cycle", "same_population", "misassigned_requests", "failed_request", "resource_error", "source_changed", "cleanup_failed"])
def test_incomplete_or_substituted_acceptance_is_refused(mutation: str) -> None:
    report = accepted()
    driver.require_completion(report)
    if mutation == "missing_cycle":
        report["cycles"].pop()
    elif mutation == "same_population":
        report["cycles"][1]["native_effects"] = report["cycles"][0]["native_effects"]
    elif mutation == "misassigned_requests":
        report["requests"][0]["cycle"] = 1
    elif mutation == "failed_request":
        report["requests"][0]["status"] = 409
    elif mutation == "resource_error":
        report["resource_samples"]["status"] = "incomplete"
    elif mutation == "source_changed":
        report["source_after"]["commit"] = "later"
    else:
        report["owned_container_removed"] = False
    with pytest.raises(ValueError):
        driver.require_completion(report)


def test_missing_server_observation_and_nonmonotonic_cpu_are_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver.sys, "platform", "unsupported")
    unavailable = common.process_observation(123)
    assert unavailable["cpu_seconds"] is None and unavailable["rss_bytes"] is None and unavailable["status"] == "unavailable"
    with pytest.raises(ValueError):
        common.cpu_delta(unavailable, unavailable)
    with pytest.raises(ValueError):
        common.cpu_delta({"status": "available", "pid": 123, "cpu_seconds": 9.}, {"status": "available", "pid": 123, "cpu_seconds": 8.})
    assert common.cpu_delta({"status": "available", "pid": 123, "cpu_seconds": 8.}, {"status": "available", "pid": 123, "cpu_seconds": 9.}) == 1.


def test_http_failure_retains_exact_status_and_time_without_auth_or_response_values() -> None:
    rows: list[dict[str, Any]] = []
    client = driver.Client("https://localhost:4444", ssl.create_default_context(), rows, 0)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise urllib.error.HTTPError("https://localhost:4444/api/v1/intercompany-operations/sources", 403, "denied", {}, io.BytesIO(b"private-response"))

    client.opener = SimpleNamespace(open=fail)
    with pytest.raises(RuntimeError, match="403"):
        client.request(driver.API + "/sources", {"Authorization": "Bearer private-token"}, {"reason": "private-input"})
    assert rows[0]["status"] == 403 and rows[0]["seconds"] >= 0
    serialized = json.dumps(rows)
    assert all(value not in serialized for value in ("private-token", "private-response", "private-input"))


def test_cycle_uses_all_three_real_action_roles_and_independent_party_reports(tmp_path: Path) -> None:
    proofs, report = packets()
    actions: list[tuple[str, str]] = []

    class Stub:
        def login(self, tenant: str, username: str, password: str) -> dict[str, str]:
            return {"actor": username}

        def request(self, path: str, headers: dict[str, str], body: dict[str, str] | None = None) -> dict[str, Any]:
            actions.append((path, headers["actor"]))
            if path.endswith("/catalog"):
                return {"catalog": {"maps": [{"legal_entity_id": name, "id": name + "-map"} for name in ("entity", "buyer", "group")]}}
            if "/report?" in path:
                return {"report": copy.deepcopy(report)}
            if path.endswith("/sources"):
                return {"plan": proofs[0]["plan"]}
            if path.endswith("/settlements"):
                return {"plan": proofs[1]["plan"]}
            if path.endswith("/eliminations"):
                return {"plan": proofs[2]["plan"]}
            stage = next(index for index, proof in enumerate(proofs) if proof["plan"]["id"] in path)
            return {"evidence": copy.deepcopy(proofs[stage])} if path.endswith("/evidence") else {"plan": copy.deepcopy(proofs[stage]["plan"])}

    result = driver.execute_cycle(Stub(), SimpleNamespace(tenant="synthetic", password="secret"), 0, tmp_path / "cycle", oracle)
    assert result["financial_verification"] == "passed" and len(result["native_effects"]) == 5
    assert len(actions) == 14
    assert all(actor == "browser-checker" for path, actor in actions if path.endswith("/review"))
    assert all(actor == "browser-poster" for path, actor in actions if path.endswith("/post"))
    assert len(result["proofs_sha256"]) == 4 and (tmp_path / "cycle/independent-oracle.json").is_file()


def test_server_identity_binds_actual_child_run_and_module_origin(tmp_path: Path) -> None:
    identity = {"schema_version": "owned-native-api-process-v1", "run_id": "owned-run", "pid": common.os.getpid() + 1000,
                "runtime_root": str(tmp_path), "api_module_file": str(tmp_path / "reconforge/api.py")}
    assert common.require_server_identity(identity, tmp_path, "owned-run") == identity["pid"]
    for mutation in ({"run_id": "other-run"}, {"pid": common.os.getpid()}, {"pid": True},
                     {"api_module_file": str(tmp_path.parent / "foreign/api.py")}, {"runtime_root": str(tmp_path.parent)}):
        with pytest.raises(ValueError):
            common.require_server_identity({**identity, **mutation}, tmp_path, "owned-run")
    with pytest.raises(ValueError, match="lifetime"):
        common.cpu_delta({"status": "available", "pid": 123, "cpu_seconds": 1., "birth_identity": "old"},
                         {"status": "available", "pid": 123, "cpu_seconds": 2., "birth_identity": "new"})


def test_exited_launcher_still_closes_owned_child_but_never_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = []
    server = SimpleNamespace(pid=123, poll=lambda: 0)
    actual = {"status": "available", "pid": 456, "birth_identity": "owned-birth"}
    stages = iter([False, True])
    monkeypatch.setattr(common.os, "name", "nt")
    monkeypatch.setattr(common, "process_is_stopped", lambda pid: next(stages))
    monkeypatch.setattr(common, "process_observation", lambda pid: actual)
    monkeypatch.setattr(common, "command", lambda args, **kwargs: commands.append(args))
    assert common.stop_server(server, actual) is True
    assert commands == [["taskkill", "/PID", "456", "/T", "/F"]]
    commands.clear()
    monkeypatch.setattr(common, "process_is_stopped", lambda pid: False)
    monkeypatch.setattr(common, "process_observation", lambda pid: {**actual, "birth_identity": "new-process"})
    assert common.stop_server(server, actual) is False
    assert commands == []


def test_structured_http_error_retains_code_but_redacts_reflected_token_and_password() -> None:
    rows: list[dict[str, Any]] = []
    client = common.Client("https://localhost:4444", ssl.create_default_context(), rows, 0)

    def fail(*args: Any, **kwargs: Any) -> None:
        payload = json.dumps({"error": {"code": "scope_denied", "message": "token=private-token password=private-password",
                                       "request_id": "request-1", "debug": "never export"}}).encode()
        raise urllib.error.HTTPError("https://localhost:4444/api/v1/auth/step-up", 403, "denied", {}, io.BytesIO(payload))

    client.opener = SimpleNamespace(open=fail)
    with pytest.raises(RuntimeError, match="403"):
        client.request("/api/v1/auth/step-up", {"Authorization": "Bearer private-token"}, {"password": "private-password"})
    assert rows[0]["api_error"]["code"] == "scope_denied" and rows[0]["api_error"]["request_id"] == "request-1"
    assert all(value not in json.dumps(rows) for value in ("private-token", "private-password", "never export"))


@pytest.mark.parametrize("failure", ["oracle_refuses", "summary_override", "boolean_effects", "zero_timed", "cleanup_error"])
def test_common_runtime_cannot_overrule_owned_financial_or_cleanup_refusal(failure: str) -> None:
    report = {**accepted(), "status": "failed"}
    scenario = SimpleNamespace(expected_requests_per_cycle=20, require_financial_completion=driver.require_financial_completion,
        financial_summary=lambda report: {"financial_verification": "passed", "successful_cycles": 2,
                                           "native_posting_effects": 10, "timed_native_posting_effects": 10})
    common.complete_report(report, scenario)
    assert report["status"] == "passed"
    report = {**accepted(), "status": "failed"}
    if failure == "oracle_refuses":
        def refuse(report: Any) -> None:
            raise ValueError("Independent manufacturing effect population is wrong")
        scenario.require_financial_completion = refuse
    elif failure == "cleanup_error":
        report["cleanup_errors"] = [{"stage": "postgres_container", "exception_type": "TimeoutExpired"}]
    else:
        patch = {"status": "passed"} if failure == "summary_override" else {"native_posting_effects": True} if failure == "boolean_effects" else {"timed_native_posting_effects": 0}
        scenario.financial_summary = lambda report: {"financial_verification": "passed", "successful_cycles": 2,
                                                    "native_posting_effects": 10, "timed_native_posting_effects": 10, **patch}
    with pytest.raises(ValueError):
        common.complete_report(report, scenario)
    assert report["status"] == "failed" and "financial_verification" not in report
