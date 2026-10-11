"""Pure ME adapter contract/adversaries; no HTTP server, container or runtime load."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_manufacturing_cycle_oracle import oracle, proof_fixture

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/benchmark_manufacturing_api.py"
spec = importlib.util.spec_from_file_location("manufacturing_api_driver", SCRIPT)
assert spec and spec.loader
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def public_order(proof: dict[str, Any]) -> dict[str, Any]:
    rows = proof["populations"]
    order = rows["manufacturing_execution_orders"][0]
    return {**order["payload"], **{key: order[key] for key in ("phase", "source_digest", "issue_plan", "issue_digest", "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor")},
            "completions": [{**child["payload"], **{key: child[key] for key in ("phase", "source_digest", "reviewer_id", "receipt_effect", "scrap_effect_id")}} for child in sorted(rows["manufacturing_execution_completions"], key=lambda row: row["id"])], "wip_minor": 0}


class SyntheticClient:
    def __init__(self, proof: dict[str, Any], *, corrupted_public: bool = False) -> None:
        self.proof, self.corrupted_public, self.output = proof, corrupted_public, 0
        self.calls: list[tuple[str, str]] = []

    def login(self, tenant: str, username: str, password: str, *, entity_id: str | None = None) -> dict[str, str]:
        assert tenant == self.proof["tenant_id"] and entity_id == "entity"
        self.calls.extend((("/auth/login", username), ("/auth/step-up", username)))
        return {"actor": username}

    def request(self, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, headers["actor"]))
        rows = self.proof["populations"]
        if body is None:
            result = public_order(self.proof)
            if self.corrupted_public:
                result["completions"][0]["phase"] = 999
            return {"order": result}
        if "/boms" in path:
            return {"bom": {"id": rows["manufacturing_execution_boms"][0]["id"], "source_digest": rows["manufacturing_execution_boms"][0]["source_digest"]}}
        if path.endswith("/completions"):
            child = rows["manufacturing_execution_completions"][self.output]
            self.output += 1
            return {"completion": {"id": child["id"], "source_digest": child["source_digest"]}}
        if "/completions/" in path:
            child = next(child for child in rows["manufacturing_execution_completions"] if child["id"] in path)
            return {"completion": {"id": child["id"], "source_digest": child["source_digest"]}}
        return {"order": {"id": rows["manufacturing_execution_orders"][0]["id"], "source_digest": rows["manufacturing_execution_orders"][0]["source_digest"]}}


def cycle(tmp_path: Path, *, corrupted_public: bool = False) -> tuple[dict[str, Any], SyntheticClient]:
    proof = proof_fixture()
    client = SyntheticClient(proof, corrupted_public=corrupted_public)
    result = driver.execute_cycle(client, SimpleNamespace(tenant="synthetic", password="never-exported"), 0, tmp_path / "cycle", oracle, lambda runtime: copy.deepcopy(proof))
    return result, client


def test_actual_callback_actions_are_full_three_human_cycle_and_separate_preseeded_effects(tmp_path: Path) -> None:
    result, client = cycle(tmp_path)
    assert len(client.calls) == 22
    assert all(actor == "browser-checker" for path, actor in client.calls if path.endswith(("/review", "/approve")))
    assert all(actor == "browser-poster" for path, actor in client.calls if path.endswith(("/post", "/cancel")))
    assert result["financial_verification"] == "passed" and result["posting_effects"] == 6
    assert len(result["preseeded_input_effect_ids"]) == 2 and len(result["timed_manufacturing_effect_ids"]) == 4
    assert result["performance_accepted"] is False
    assert (tmp_path / "cycle/manufacturing-proof.json").is_file() and (tmp_path / "cycle/independent-oracle.json").is_file()
    driver.require_financial_completion({"configuration": {"cycles": 1}, "cycles": [result]})


def test_public_child_population_must_equal_native_source_proof(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="projection"):
        cycle(tmp_path, corrupted_public=True)


@pytest.mark.parametrize("mutation", ["missing_cycle", "reused_population", "timed_preseed", "wrong_cost", "same_tenant", "missing_proof", "missing_search", "invalid_time"])
def test_incomplete_financial_acceptance_is_refused(tmp_path: Path, mutation: str) -> None:
    result, _ = cycle(tmp_path)
    second = copy.deepcopy(result)
    second.update(index=1, tenant_id="fresh", source_id="fresh-source")
    for key in ("original_effect_ids", "preseeded_input_effect_ids", "timed_manufacturing_effect_ids"):
        second[key] = ["fresh-" + value for value in second[key]]
    report = {"configuration": {"cycles": 2}, "cycles": [result, second]}
    driver.require_financial_completion(report)
    if mutation == "missing_cycle":
        report["cycles"].pop()
    elif mutation == "reused_population":
        second["original_effect_ids"] = result["original_effect_ids"]
    elif mutation == "timed_preseed":
        second["timed_manufacturing_effect_ids"][0] = second["preseeded_input_effect_ids"][0]
    elif mutation == "wrong_cost":
        second["finished_cost_minor"] = "2611"
    elif mutation == "same_tenant":
        second["tenant_id"] = result["tenant_id"]
    elif mutation == "missing_proof":
        second["original_proof_sha256"] = None
    elif mutation == "missing_search":
        second["receipt_identity_candidates"].pop()
    else:
        second["seconds"] = float("nan")
    with pytest.raises(ValueError):
        driver.require_financial_completion(report)


def test_monies_are_never_implicitly_coerced_from_float_or_noncanonical_text() -> None:
    assert driver.raw_projection({"cost_minor": "9000000000000000000"})["cost_minor"] == 9_000_000_000_000_000_000
    for value in ("01", "1.0", "1e2", "-1", "١", "9000000000000000001"):
        with pytest.raises(ValueError):
            driver.raw_projection({"cost_minor": value})


def test_adapter_declares_original_oracle_tuple_and_runtime_secrets() -> None:
    scenario = driver.ManufacturingScenario()
    assert scenario.oracle_paths == (scenario.oracle_path,) and scenario.expected_requests_per_cycle == 22
    assert scenario.redaction_secrets(SimpleNamespace(password="private")) == ["private"]
