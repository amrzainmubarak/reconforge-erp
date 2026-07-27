from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "docs" / "risk-register.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "risk_register.schema.json"
MARKDOWN_PATH = ROOT / "docs" / "risk-register.md"
RATING_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _register() -> dict[str, Any]:
    payload = yaml.safe_load(REGISTER_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _calculated_rating(score: int) -> str:
    if score <= 3:
        return "low"
    if score <= 7:
        return "medium"
    if score <= 11:
        return "high"
    return "critical"


def test_risk_register_schema_ids_and_ratings_are_normalized() -> None:
    register = _register()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(register)

    risks = register["risks"]
    ids = [risk["id"] for risk in risks]
    assert ids == [f"R-{number:03d}" for number in range(1, 19)]
    assert len({risk["title"] for risk in risks}) == len(risks)

    likelihood = register["risk_method"]["likelihood_scale"]
    impact = register["risk_method"]["impact_scale"]
    for risk in risks:
        score = int(likelihood[risk["likelihood"]]) * int(impact[risk["impact"]])
        assert risk["inherent_risk"] == _calculated_rating(score)
        assert RATING_ORDER[risk["residual_risk"]] <= RATING_ORDER[risk["inherent_risk"]]
        assert risk["owner"] != "maintainers"


def test_risk_review_dates_follow_declared_cadence() -> None:
    register = _register()
    last_reviewed = date.fromisoformat(register["last_reviewed"])
    for risk in register["risks"]:
        next_review = date.fromisoformat(risk["next_review"])
        days = (next_review - last_reviewed).days
        assert 0 < days <= int(risk["review_cadence_days"])


def test_risk_evidence_paths_exist_inside_repository() -> None:
    root = ROOT.resolve()
    for risk in _register()["risks"]:
        for reference in risk["evidence"]:
            path = (root / reference).resolve()
            assert path.is_relative_to(root)
            assert path.exists(), f"{risk['id']} evidence path is unavailable: {reference}"


def test_markdown_risk_ids_match_normalized_register() -> None:
    markdown_ids = re.findall(r"^\| (R-[0-9]{3}) \|", MARKDOWN_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    normalized_ids = [risk["id"] for risk in _register()["risks"]]
    assert sorted(markdown_ids) == normalized_ids
    assert len(markdown_ids) == len(set(markdown_ids))
