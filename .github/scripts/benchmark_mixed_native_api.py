"""Sequential IC1 and ME1 cohorts on one verified HTTPS/PG observation runtime.

Each owner uses its own fresh tenant, normal API actions and original independent
financial oracle. This composition creates no cross-domain financial ownership.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_native_api_runtime import Client, NativeApiScenario, run  # noqa: E402

IC = "intercompany"
ME = "manufacturing"


def identifier(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 200:
        raise ValueError("Exact original nonempty financial identity required")
    return value


class MixedScenario:
    name = "intercompany_then_manufacturing_independent_tenants"
    schema_version = "mixed-native-api-benchmark-v1"
    tool_path = Path(__file__).resolve()
    expected_requests_per_cycle = 42
    measurement_scope = (
        "Sequential cohort on one actual HTTPS server/PostgreSQL container: IC1 then ME1 in separate fresh tenants; "
        "masters and ME1's two original material-receipt effects seeded before timing; 42 actual HTTPS requests; "
        "11 original native effects verified, 9 timed business effects per cohort. Cohort wall time includes "
        "both owners' proof/oracle work and waits. Cohort client process_time includes in-process proof/oracle "
        "work and the observer thread, excludes wait time and external subprocess CPU; both original oracles "
        "run in-process. Retain each owner's business latency separately (both exclude independent "
        "oracle work; ME1 also excludes native proof export). No cross-domain financial linkage, retries or fair "
        "baseline comparison is claimed."
    )

    def __init__(self, intercompany: NativeApiScenario | None = None, manufacturing: NativeApiScenario | None = None) -> None:
        self.intercompany = intercompany if intercompany is not None else importlib.import_module("benchmark_intercompany_api").IntercompanyScenario()
        self.manufacturing = manufacturing if manufacturing is not None else importlib.import_module("benchmark_manufacturing_api").ManufacturingScenario()
        counts = (self.intercompany.expected_requests_per_cycle, self.manufacturing.expected_requests_per_cycle)
        if (self.intercompany.name, self.manufacturing.name) != ("intercompany_operations", "manufacturing_execution") or any(type(value) is not int for value in counts) or counts != (20, 22):
            raise ValueError("Exactly the original 20-request IC1 and 22-request ME1 owner contracts required")
        if self.intercompany.oracle_paths != (self.intercompany.oracle_path,) or self.manufacturing.oracle_paths != (self.manufacturing.oracle_path,):
            raise ValueError("Exactly both original independent owner oracles required")
        self.oracle_path = self.intercompany.oracle_path
        self.oracle_paths: tuple[Path, ...] = (self.intercompany.oracle_path, self.manufacturing.oracle_path)
        if self.oracle_paths[0].resolve() == self.oracle_paths[1].resolve():
            raise ValueError("Independent owners must retain distinct original oracle paths")

    def seed(self, admin_dsn: str, app_dsn: str) -> tuple[Any, Any]:
        return (self.intercompany.seed(admin_dsn, app_dsn), self.manufacturing.seed(admin_dsn, app_dsn))

    def redaction_secrets(self, runtime: Any) -> list[str]:
        if type(runtime) is not tuple or len(runtime) != 2:
            raise ValueError("Literal two-owner cohort runtime required")
        return self.intercompany.redaction_secrets(runtime[0]) + self.manufacturing.redaction_secrets(runtime[1])

    def execute_cycle(self, client: Client, runtime: Any, index: int, directory: Path) -> dict[str, Any]:
        if type(runtime) is not tuple or len(runtime) != 2:
            raise ValueError("Literal two-owner cohort runtime required")
        directory.mkdir()
        started, cpu_started = time.perf_counter(), time.process_time()
        intercompany = self.intercompany.execute_cycle(client, runtime[0], index, directory / IC)
        manufacturing = self.manufacturing.execute_cycle(client, runtime[1], index, directory / ME)
        seconds, cpu = time.perf_counter() - started, time.process_time() - cpu_started
        if intercompany["financial_verification"] != "passed" or manufacturing["financial_verification"] != "passed":
            raise ValueError("Both original financial oracles must verify the cohort")
        row = {"index": index, "seconds": seconds, "client_cpu_seconds": cpu,
               "financial_verification": "passed", IC: intercompany, ME: manufacturing,
               "component_tools_sha256": {IC: hashlib.sha256(self.intercompany.tool_path.read_bytes()).hexdigest(),
                                           ME: hashlib.sha256(self.manufacturing.tool_path.read_bytes()).hexdigest()}}
        return row

    def require_financial_completion(self, report: dict[str, Any]) -> None:
        count, cycles = report["configuration"]["cycles"], report["cycles"]
        if type(count) is not int or not 1 <= count <= 50 or type(cycles) is not list or len(cycles) != count or any(type(row["index"]) is not int for row in cycles) or {row["index"] for row in cycles} != set(range(count)):
            raise ValueError("Every original bounded cohort index required")
        if any(row["financial_verification"] != "passed" or type(row[IC]) is not dict or type(row[ME]) is not dict or type(row[IC]["index"]) is not int or type(row[ME]["index"]) is not int or row[IC]["index"] != row["index"] or row[ME]["index"] != row["index"] for row in cycles):
            raise ValueError("Each cohort must retain both matching original owner cycles")
        # No aggregate oracle replaces either owner's original verifier.
        for key, owner in ((IC, self.intercompany), (ME, self.manufacturing)):
            owner.require_financial_completion({"configuration": {"cycles": count}, "cycles": [row[key] for row in cycles]})
        tenants: list[str] = []
        sources: list[str] = []
        effects: list[tuple[str, str]] = []
        timed: list[tuple[str, str]] = []
        for row in cycles:
            first, second = row[IC], row[ME]
            tenants.extend(identifier(part["tenant_id"]) for part in (first, second))
            sources.extend(identifier(part["source_id"]) for part in (first, second))
            ic_effects = [identifier(effect["effect_id"]) for effect in first["native_effects"]]
            me_effects = [identifier(effect) for effect in second["original_effect_ids"]]
            me_timed = [identifier(effect) for effect in second["timed_manufacturing_effect_ids"]]
            if len(ic_effects) != 5 or len(me_effects) != 6 or len(me_timed) != 4 or type(second["posting_effects"]) is not int or second["posting_effects"] != 6 or not set(me_timed).issubset(me_effects):
                raise ValueError("Exactly five IC1 and six original/four timed ME1 effects required")
            # Native posting identities are keyed by tenant, including seeded receipts.
            # Equal local IDs in distinct tenants are separate original effects.
            effects.extend((first["tenant_id"], value) for value in ic_effects)
            effects.extend((second["tenant_id"], value) for value in me_effects)
            timed.extend((first["tenant_id"], value) for value in ic_effects)
            timed.extend((second["tenant_id"], value) for value in me_timed)
        if len(set(tenants)) != 2 * count or len(set(sources)) != 2 * count or len(effects) != 11 * count or len(set(effects)) != 11 * count or len(timed) != 9 * count or len(set(timed)) != 9 * count:
            raise ValueError("Separate fresh owner tenants, sources and disjoint original/timed native populations required")

    def financial_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        self.require_financial_completion(report)
        count = len(report["cycles"])
        return {"financial_verification": "passed", "successful_cycles": count,
                "native_posting_effects": 11 * count, "timed_native_posting_effects": 9 * count}


def main() -> int:
    return run(MixedScenario())


if __name__ == "__main__":
    raise SystemExit(main())
