"""Bounded actual HTTPS manufacturing cycles with independently verified native cost.

Two original material receipts are posted in each fresh synthetic tenant BEFORE
timing. The measured business window covers six normal login/step-up requests and
sixteen manufacturing requests: BOM, reservation/whole issue, reviewed cancellation,
two partial good/scrap outputs, and final authorized native order read. Four new
manufacturing effects are timed; six effects including the original inputs are
verified. File export/oracle work is measured separately from business latency.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

API = "/api/v1/manufacturing-execution"


class ApiClient(Protocol):
    def login(self, tenant: str, username: str, password: str, *, entity_id: str | None = None) -> dict[str, str]: ...
    def request(self, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]: ...


def save(path: Path, value: Any) -> str:
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_projection(value: Any, key: str = "") -> Any:
    """Decode exact API decimal strings only at the original monetary/quantity keys."""
    if type(value) is dict:
        return {name: raw_projection(part, name) for name, part in value.items()}
    if type(value) is list:
        return [raw_projection(part) for part in value]
    if (key.endswith("_minor") or key.endswith("_scaled")) and type(value) is str:
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value or int(value) > 9_000_000_000_000_000_000:
            raise ValueError("Exact original API money/quantity required")
        return int(value)
    return value


def execute_cycle(client: ApiClient, runtime: Any, index: int, directory: Path, oracle: Any,
                  proof_exporter: Callable[[Any], dict[str, Any]] | None = None) -> dict[str, Any]:
    directory.mkdir()
    started, client_cpu = time.perf_counter(), time.process_time()
    humans = {role: client.login(runtime.tenant, "browser-" + role, runtime.password, entity_id="entity") for role in ("maker", "checker", "poster")}

    def create(path: str, key: str, body: dict[str, Any], actor: str = "maker") -> dict[str, Any]:
        return client.request(API + path, humans[actor], body)[key]

    def phase(source: dict[str, Any], family: str, operation: str, actor: str) -> dict[str, Any]:
        return create(f"/{family}/{source['id']}/{operation}", "bom" if family == "boms" else "order" if family == "orders" else "completion",
                      {"command_id": f"cycle-{index}-{source['id']}-{operation}", "expected_digest": source["source_digest"],
                       "reason": "Independent actual HTTPS " + operation}, actor)

    bom = create("/boms", "bom", {"command_id": f"cycle-{index}-bom", "number": f"API-BOM-{index}", "version": 1,
                 "output_item_code": "PRODUCT", "output_quantity": "10", "components": [{"item_code": "ITEM", "quantity": "2"}, {"item_code": "MATERIAL", "quantity": "3.000"}],
                 "reason": "Synthetic exact original base-UOM recipe"})
    bom = phase(bom, "boms", "approve", "checker")
    order = create("/orders", "order", {"command_id": f"cycle-{index}-order", "number": f"API-WORK-{index}", "bom_version_id": bom["id"],
                   "output_quantity": "10", "component_location_code": "MAIN/STOCK", "finished_location_code": "MAIN/STOCK",
                   "component_policy_code": "FIFO", "finished_policy_code": "MFG", "journal_code": "STOCK", "wip_account_code": "WIP", "scrap_account_code": "SCRAP",
                   "period_id": "period", "posting_date": "2026-10-04", "reason": "Synthetic whole original material reservation"})
    for operation, actor in (("prepare", "maker"), ("review", "checker"), ("post", "poster")):
        order = phase(order, "orders", operation, actor)
    for attempt, (good, scrap, terminal) in enumerate((("3", "1", "cancel"), ("3", "1", "post"), ("6", "0", "post"))):
        child = create(f"/orders/{order['id']}/completions", "completion", {"command_id": f"cycle-{index}-output-{attempt}",
                       "good_quantity": good, "scrap_quantity": scrap, "period_id": "period", "posting_date": "2026-10-05",
                       "reason": "Synthetic original partial good and abnormal scrap"})
        child = phase(child, "completions", "review", "checker")
        phase(child, "completions", terminal, "poster")
    public_order = client.request(API + f"/orders/{order['id']}", humans["poster"])["order"]
    seconds, cpu = time.perf_counter() - started, time.process_time() - client_cpu
    save(directory / "public-order.json", public_order)

    if proof_exporter is None:
        proof_exporter = importlib.import_module("tests.manufacturing_execution_browser").manufacturing_execution_proof
    export_started = time.perf_counter()
    proof = proof_exporter(runtime)
    proof_hash = save(directory / "manufacturing-proof.json", proof)
    export_seconds = time.perf_counter() - export_started
    validation_started = time.perf_counter()
    financial = oracle.verify_proof(proof)
    native = proof["populations"]["manufacturing_execution_orders"][0]
    decoded = raw_projection(public_order)
    expected_public = {**native["payload"], **{key: native[key] for key in ("phase", "source_digest", "issue_plan", "issue_digest", "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor")},
                       "completions": [{**child["payload"], **{key: child[key] for key in ("phase", "source_digest", "reviewer_id", "receipt_effect", "scrap_effect_id")}}
                                       for child in sorted(proof["populations"]["manufacturing_execution_completions"], key=lambda row: row["id"])], "wip_minor": 0}
    if proof["tenant_id"] != runtime.tenant or decoded != expected_public:
        raise ValueError("Final HTTPS original order/financial projection differs from native proof")
    original = [row["posting_effect_id"] for row in proof["populations"]["inventory_receipt_plans"] if not row["source_number"].startswith("ME1C-")]
    timed = [native["issue_effect_id"]]
    for child in proof["populations"]["manufacturing_execution_completions"]:
        if child["phase"] == 2:
            if child["receipt_effect"]:
                timed.append(child["receipt_effect"]["effect_id"])
            if child["scrap_effect_id"]:
                timed.append(child["scrap_effect_id"])
    oracle_hash = save(directory / "independent-oracle.json", {**financial, "original_proof_sha256": proof_hash})
    return {"index": index, "tenant_id": runtime.tenant, "source_id": order["id"], "seconds": seconds, "client_cpu_seconds": cpu,
            **financial, "preseeded_input_effect_ids": sorted(original), "timed_manufacturing_effect_ids": sorted(timed),
            "original_proof_sha256": proof_hash, "independent_oracle_sha256": oracle_hash,
            "proof_export_seconds": export_seconds, "independent_oracle_seconds": time.perf_counter() - validation_started,
            "receipt_identity_candidates": [row["payload"]["receipt_identity_candidates"] for row in proof["populations"]["manufacturing_execution_completions"]]}


def require_financial_completion(report: dict[str, Any]) -> None:
    rows, count = report["cycles"], report["configuration"]["cycles"]
    if type(count) is not int or not 1 <= count <= 50 or len(rows) != count or any(type(row["index"]) is not int for row in rows) or {row["index"] for row in rows} != set(range(count)):
        raise ValueError("Every bounded original manufacturing cycle required")
    all_ids = []
    for row in rows:
        if row["financial_verification"] != "passed" or (row["issued_material_minor"], row["finished_cost_minor"], row["abnormal_scrap_minor"], row["remaining_wip_minor"], row["balanced_turnover_minor"]) != ("2900", "2610", "290", "0", "21133"):
            raise ValueError("Independent actual original manufacturing cost conservation required")
        original, timed, verified = row["preseeded_input_effect_ids"], row["timed_manufacturing_effect_ids"], row["original_effect_ids"]
        if len(original) != 2 or len(timed) != 4 or len(verified) != 6 or len(set(verified)) != 6 or set(original) & set(timed) or set(original) | set(timed) != set(verified):
            raise ValueError("Two preseeded original input effects and four timed manufacturing effects must be disjoint and complete")
        if any(type(value) is not str or not value for value in verified) or row["posting_effects"] != 6:
            raise ValueError("Six exact original native effect identities required")
        all_ids.extend(verified)
        for key in ("seconds", "client_cpu_seconds", "proof_export_seconds", "independent_oracle_seconds"):
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
                raise ValueError("Complete finite original timing observations required")
        for key in ("original_proof_sha256", "independent_oracle_sha256"):
            if type(row[key]) is not str or len(row[key]) != 64 or any(char not in "0123456789abcdef" for char in row[key]):
                raise ValueError("Original native proof and independent oracle byte digests required")
        if len(row["receipt_identity_candidates"]) != 3 or any(type(value) is not int or not 1 <= value <= 4096 for value in row["receipt_identity_candidates"]):
            raise ValueError("Original bounded same-date native identity search observations required")
    if len(set(all_ids)) != len(all_ids) or any(len({row[key] for row in rows}) != count or any(type(row[key]) is not str or not row[key] for row in rows) for key in ("tenant_id", "source_id")):
        raise ValueError("Every original manufacturing cycle requires a fresh tenant, source and native effect population")


class ManufacturingScenario:
    name = "manufacturing_execution"
    schema_version = "manufacturing-https-benchmark-v1"
    tool_path = Path(__file__).resolve()
    oracle_path = tool_path.with_name("verify_manufacturing_cycle_oracle.py")
    oracle_paths: tuple[Path, ...] = (oracle_path,)
    expected_requests_per_cycle = 22
    measurement_scope = "Sequential fresh synthetic tenant; masters and2original material receipt effects seeded before timing;22actual HTTPS authentication/manufacturing requests and4newnative manufacturing effects per cycle; business-cycle latency excludes read-only proof export/oracle; overall client/server/database observations include that proof work; no retries, no MRP/high-volume acceptance"

    def __init__(self) -> None:
        spec = importlib.util.spec_from_file_location("independent_manufacturing_oracle", self.oracle_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Independent stdlib original manufacturing oracle unavailable")
        self.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.oracle)

    def seed(self, admin_dsn: str, app_dsn: str) -> Any:
        return importlib.import_module("tests.manufacturing_execution_browser").seed_manufacturing_execution_browser(admin_dsn, app_dsn)

    def redaction_secrets(self, runtime: Any) -> list[str]:
        return [runtime.password]

    def execute_cycle(self, client: ApiClient, runtime: Any, index: int, directory: Path) -> dict[str, Any]:
        return execute_cycle(client, runtime, index, directory, self.oracle)

    def require_financial_completion(self, report: dict[str, Any]) -> None:
        require_financial_completion(report)

    def financial_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        return {"financial_verification": "passed", "successful_cycles": len(report["cycles"]), "native_posting_effects": 6 * len(report["cycles"]), "timed_native_posting_effects": 4 * len(report["cycles"])}


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from benchmark_native_api_runtime import run
    return run(ManufacturingScenario())


if __name__ == "__main__":
    raise SystemExit(main())
