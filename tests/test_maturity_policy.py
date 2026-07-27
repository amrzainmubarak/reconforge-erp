from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from reconforge.modules import ModuleDescriptor, list_modules

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "execution" / "MATURITY_POLICY.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "maturity_policy.schema.json"
CLAIMS_PATH = ROOT / "docs" / "execution" / "CLAIMS_EVIDENCE_MATRIX.md"


def _policy() -> dict[str, Any]:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _claim_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in CLAIMS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 6 or cells[0] == "Claim":
            continue
        rows[cells[0]] = {"maturity": cells[4], "allowed_wording": cells[5]}
    return rows


def _maturity_violations(
    descriptors: tuple[ModuleDescriptor, ...],
    policy: dict[str, Any],
) -> tuple[str, ...]:
    rank = policy["module_maturity_order"]
    ceilings = {item["module_id"]: item["maximum_maturity"] for item in policy["module_ceilings"]}
    return tuple(
        descriptor.module_id
        for descriptor in descriptors
        if descriptor.module_id not in ceilings
        or int(rank[descriptor.maturity]) > int(rank[ceilings[descriptor.module_id]])
    )


def test_maturity_policy_schema_and_claim_references_are_valid() -> None:
    policy = _policy()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(policy)

    claims = _claim_rows()
    referenced_claims = {item["evidence_claim"] for item in policy["module_ceilings"]}
    referenced_claims.add(policy["product_stage"]["evidence_claim"])
    assert referenced_claims <= set(claims)
    assert claims[policy["product_stage"]["evidence_claim"]]["maturity"] == "Alpha"
    assert claims["Millions of transactions / enterprise-ready / bank-grade"]["maturity"] == "Planned/not allowed"


def test_runtime_module_maturity_does_not_exceed_evidence_ceilings() -> None:
    policy = _policy()
    descriptors = list_modules()
    ceilings = [item["module_id"] for item in policy["module_ceilings"]]

    assert ceilings == sorted(ceilings)
    assert set(ceilings) == {descriptor.module_id for descriptor in descriptors}
    assert _maturity_violations(descriptors, policy) == ()


def test_maturity_gate_rejects_a_synthetic_promotion_without_new_evidence() -> None:
    policy = _policy()
    descriptors = list_modules()
    promoted = descriptors[0].model_copy(update={"maturity": "beta"})

    assert _maturity_violations((promoted, *descriptors[1:]), policy) == (promoted.module_id,)


def test_public_surfaces_keep_evidence_bounded_wording() -> None:
    policy = _policy()
    forbidden = tuple(phrase.casefold() for phrase in policy["forbidden_unqualified_phrases"])
    required = tuple(phrase.casefold() for phrase in policy["required_boundary_phrases"])

    for relative_path in policy["public_surfaces"]:
        path = (ROOT / relative_path).resolve()
        assert path.is_relative_to(ROOT.resolve())
        text = path.read_text(encoding="utf-8").casefold()
        assert not [phrase for phrase in forbidden if phrase in text], relative_path
        assert any(phrase in text for phrase in required), relative_path
