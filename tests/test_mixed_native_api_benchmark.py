"""Composition damage tests; owned financial oracles remain separate contracts."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/benchmark_mixed_native_api.py"
spec = importlib.util.spec_from_file_location("mixed_native_api_driver", SCRIPT)
assert spec and spec.loader
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class OwnedContract:
    """A test double records delegation and can refuse independently of a label."""

    def __init__(self, name: str, root: Path, events: list[Any]) -> None:
        self.name, self.events, self.next_tenant, self.refuse = name, events, 0, False
        self.retained_populations: dict[str, tuple[str, ...]] = {}
        self.expected_requests_per_cycle = 20 if name == "intercompany_operations" else 22
        self.tool_path = root / (name + "_tool.py")
        self.oracle_path = root / (name + "_original_oracle.py")
        self.oracle_paths = (self.oracle_path,)
        self.tool_path.write_text(name, encoding="utf-8")
        self.oracle_path.write_text("independent " + name, encoding="utf-8")

    def seed(self, admin_dsn: str, app_dsn: str) -> Any:
        self.next_tenant += 1
        return SimpleNamespace(tenant=f"{self.name}-{self.next_tenant}", password=f"private-{self.name}")

    def redaction_secrets(self, runtime: Any) -> list[str]:
        return [runtime.password]

    def execute_cycle(self, client: Any, runtime: Any, index: int, directory: Path) -> dict[str, Any]:
        directory.mkdir()
        self.events.append((self.name, client, runtime, index, directory))
        row = {"index": index, "tenant_id": runtime.tenant, "source_id": "source-" + runtime.tenant,
               "financial_verification": "passed", "seconds": .01, "client_cpu_seconds": .001}
        ids = [f"effect-{runtime.tenant}-{number}" for number in range(5 if self.expected_requests_per_cycle == 20 else 6)]
        if self.expected_requests_per_cycle == 22:
            ids[:2] = ["seeded-material-receipt-0", "seeded-material-receipt-1"]
        self.retained_populations[runtime.tenant] = tuple(ids)
        if self.expected_requests_per_cycle == 20:
            row["native_effects"] = [{"effect_id": value} for value in ids]
        else:
            row.update(original_effect_ids=ids, timed_manufacturing_effect_ids=ids[2:], posting_effects=6)
        return row

    def require_financial_completion(self, report: dict[str, Any]) -> None:
        self.events.append((self.name, "financial_completion", report))
        if self.refuse or any(row["financial_verification"] != "passed" for row in report["cycles"]):
            raise ValueError("Original independent owner refused its financial proof")
        for row in report["cycles"]:
            ids = tuple(effect["effect_id"] for effect in row["native_effects"]) if self.expected_requests_per_cycle == 20 else tuple(row["original_effect_ids"])
            if self.retained_populations.get(row["tenant_id"]) != ids:
                raise ValueError("Original scoped native population changed")


def scenario(tmp_path: Path) -> tuple[Any, list[Any]]:
    events: list[Any] = []
    return driver.MixedScenario(OwnedContract("intercompany_operations", tmp_path, events),
                                OwnedContract("manufacturing_execution", tmp_path, events)), events


def population(tmp_path: Path, count: int = 2) -> tuple[Any, dict[str, Any], list[Any]]:
    mixed, events = scenario(tmp_path)
    client = object()
    rows = [mixed.execute_cycle(client, mixed.seed("admin", "app"), index, tmp_path / f"cohort-{index}") for index in range(count)]
    return mixed, {"configuration": {"cycles": count}, "cycles": rows}, events


def test_literal_seed_and_sequential_original_callbacks_share_client_without_merging_tenants(tmp_path: Path) -> None:
    mixed, events = scenario(tmp_path)
    runtime = mixed.seed("admin", "app")
    assert type(runtime) is tuple and len(runtime) == 2 and runtime[0].tenant != runtime[1].tenant
    assert mixed.redaction_secrets(runtime) == [runtime[0].password, runtime[1].password]
    client = object()
    result = mixed.execute_cycle(client, runtime, 0, tmp_path / "cohort")
    actions = [item for item in events if len(item) == 5]
    assert [row[0] for row in actions] == ["intercompany_operations", "manufacturing_execution"]
    assert actions[0][1] is actions[1][1] is client and actions[0][4].name == "intercompany" and actions[1][4].name == "manufacturing"
    assert mixed.oracle_paths == (mixed.intercompany.oracle_path, mixed.manufacturing.oracle_path)
    assert mixed.expected_requests_per_cycle == 42 and "Cohort wall/client CPU includes" in mixed.measurement_scope
    assert mixed.financial_summary({"configuration": {"cycles": 1}, "cycles": [result]}) == {
        "financial_verification": "passed", "successful_cycles": 1, "native_posting_effects": 11, "timed_native_posting_effects": 9}


@pytest.mark.parametrize("damage", ["missing_component", "cross_tenant", "cross_source", "cross_effect", "missing_effect",
                                  "foreign_timed", "float_count", "bool_count", "bool_index", "wrong_component_index", "bool_identity"])
def test_cohort_cannot_hide_missing_or_overlapping_original_owner_populations(tmp_path: Path, damage: str) -> None:
    mixed, report, _ = population(tmp_path)
    mixed.require_financial_completion(report)
    row = report["cycles"][1]
    if damage == "missing_component":
        row.pop("manufacturing")
    elif damage in {"cross_tenant", "cross_source"}:
        key = "tenant_id" if damage == "cross_tenant" else "source_id"
        row["manufacturing"][key] = row["intercompany"][key]
    elif damage == "cross_effect":
        row["manufacturing"]["original_effect_ids"][0] = row["intercompany"]["native_effects"][0]["effect_id"]
    elif damage == "missing_effect":
        row["intercompany"]["native_effects"].pop()
    elif damage == "foreign_timed":
        row["manufacturing"]["timed_manufacturing_effect_ids"][0] = "not-an-original-effect"
    elif damage in {"float_count", "bool_count"}:
        row["manufacturing"]["posting_effects"] = 6.0 if damage == "float_count" else True
    elif damage == "bool_index":
        row["index"] = True
    elif damage == "wrong_component_index":
        row["manufacturing"]["index"] = 0
    else:
        row["manufacturing"]["tenant_id"] = True
    with pytest.raises((KeyError, ValueError)):
        mixed.require_financial_completion(report)


@pytest.mark.parametrize("key", ["intercompany", "manufacturing"])
def test_passed_outer_label_never_overrides_either_original_owner_verifier(tmp_path: Path, key: str) -> None:
    mixed, report, _ = population(tmp_path)
    original = copy.deepcopy(report)
    getattr(mixed, key).refuse = True
    with pytest.raises(ValueError, match="Original independent owner"):
        mixed.financial_summary(report)
    assert report == original


@pytest.mark.parametrize("count", [21, 22.0, True])
def test_changed_request_or_oracle_owner_contract_is_not_admitted(tmp_path: Path, count: Any) -> None:
    mixed, _ = scenario(tmp_path)
    mixed.manufacturing.expected_requests_per_cycle = count
    with pytest.raises(ValueError, match="owner contracts"):
        driver.MixedScenario(mixed.intercompany, mixed.manufacturing)
    mixed.manufacturing.expected_requests_per_cycle = 22
    mixed.manufacturing.oracle_path = mixed.intercompany.oracle_path
    mixed.manufacturing.oracle_paths = (mixed.intercompany.oracle_path,)
    with pytest.raises(ValueError, match="distinct original"):
        driver.MixedScenario(mixed.intercompany, mixed.manufacturing)


def test_original_receipt_ids_can_repeat_only_in_distinct_verified_tenants(tmp_path: Path) -> None:
    mixed, report, _ = population(tmp_path, count=3)
    rows = report["cycles"]
    local_ids = [effect for row in rows for effect in row["manufacturing"]["original_effect_ids"]]
    assert len(local_ids) == 18 and len(set(local_ids)) == 14
    assert len({row["manufacturing"]["tenant_id"] for row in rows}) == 3
    assert mixed.financial_summary(report) == {
        "financial_verification": "passed", "successful_cycles": 3,
        "native_posting_effects": 33, "timed_native_posting_effects": 27,
    }


@pytest.mark.parametrize(("owner", "damage"), [("intercompany", "duplicate_original"),
                                               ("manufacturing", "duplicate_original"),
                                               ("manufacturing", "duplicate_timed")])
def test_scoped_population_refuses_duplicates_even_if_owner_label_is_passed(tmp_path: Path, owner: str, damage: str) -> None:
    mixed, report, _ = population(tmp_path, count=3)
    # Exercise the composition's own population guard independently of owner refusal.
    getattr(mixed, owner).require_financial_completion = lambda _: None
    row = report["cycles"][1][owner]
    if owner == "intercompany":
        row["native_effects"][0]["effect_id"] = row["native_effects"][1]["effect_id"]
    elif damage == "duplicate_original":
        row["original_effect_ids"][0] = row["original_effect_ids"][1]
    else:
        row["timed_manufacturing_effect_ids"][0] = row["timed_manufacturing_effect_ids"][1]
    with pytest.raises(ValueError, match="disjoint original/timed"):
        mixed.require_financial_completion(report)
