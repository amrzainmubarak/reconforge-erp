"""Real HTTPS IC1 recognition, partial cash and native reviewed elimination.

The common runtime owns only isolation/TLS/resource/cleanup; all five original
financial effects and three independent books are verified by the IC1 oracle.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_native_api_runtime import Client, require_common_completion, run, save  # noqa: E402

API = "/api/v1/intercompany-operations"


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


def require_financial_completion(report: dict[str, Any]) -> None:
    cycles, count = report["cycles"], report["configuration"]["cycles"]
    if type(count) is not int or len(cycles) != count or any(type(row["index"]) is not int for row in cycles) or {row["index"] for row in cycles} != set(range(count)) or any(row["financial_verification"] != "passed" for row in cycles):
        raise ValueError("Every requested original cycle and independent financial proof required")
    ids = [row["effect_id"] for cycle in cycles for row in cycle["native_effects"]]
    # Local effect IDs may repeat across fresh tenants; native ownership is the pair.
    scoped_ids = [(cycle["tenant_id"], row["effect_id"]) for cycle in cycles for row in cycle["native_effects"]]
    if len(ids) != count * 5 or any(len(row["native_effects"]) != 5 for row in cycles) or any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(scoped_ids) != len(set(scoped_ids)) or len({row["tenant_id"] for row in cycles}) != count or len({row["source_id"] for row in cycles}) != count:
        raise ValueError("Fresh unique tenants and five original native effects per cycle required")


def require_completion(report: dict[str, Any]) -> None:
    require_common_completion(report, 20)
    require_financial_completion(report)


class IntercompanyScenario:
    name = "intercompany_operations"
    schema_version = "intercompany-https-benchmark-v1"
    tool_path = Path(__file__).resolve()
    oracle_path = tool_path.with_name("verify_intercompany_cycle_oracle.py")
    oracle_paths: tuple[Path, ...] = (oracle_path,)
    expected_requests_per_cycle = 20
    measurement_scope = "Sequential fresh synthetic tenant per cycle; masters/reviewed maps seeded before timing; login+step-up+three-human business+proof/report HTTPS timed; urllib opens fresh connections; no retries"

    def __init__(self) -> None:
        spec = importlib.util.spec_from_file_location("independent_intercompany_oracle", self.oracle_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Independent stdlib oracle unavailable")
        self.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.oracle)

    def seed(self, admin_dsn: str, app_dsn: str) -> Any:
        return importlib.import_module("tests.intercompany_operations_browser_seed").seed_intercompany_browser(admin_dsn, app_dsn)

    def redaction_secrets(self, runtime: Any) -> list[str]:
        return [runtime.password]

    def execute_cycle(self, client: Client, runtime: Any, index: int, directory: Path) -> dict[str, Any]:
        return execute_cycle(client, runtime, index, directory, self.oracle)

    def require_financial_completion(self, report: dict[str, Any]) -> None:
        require_financial_completion(report)

    def financial_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        return {"financial_verification": "passed", "successful_cycles": len(report["cycles"]),
                "native_posting_effects": 5 * len(report["cycles"]), "timed_native_posting_effects": 5 * len(report["cycles"])}


def main() -> int:
    return run(IntercompanyScenario())


if __name__ == "__main__":
    raise SystemExit(main())
