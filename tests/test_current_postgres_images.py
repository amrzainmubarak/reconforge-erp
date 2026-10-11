import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / ".github/scripts/validate_current_postgres_images.py"))
POLICY = str(VALIDATOR["POLICY"])


def test_current_postgres_policy_preserves_historical_evidence_and_binds_live_defaults() -> None:
    assert VALIDATOR["validate"](ROOT)["accepted"] is True


@pytest.mark.parametrize("mutation", ["policy_image", "undeclared", "historical", "ci_image", "native_image"])
def test_current_postgres_policy_rejects_pin_and_source_drift(tmp_path: Path, mutation: str) -> None:
    paths = [
        POLICY, "docs/security/supply-chain-policy.v1.json", ".github/workflows/ci.yml",
        ".github/scripts/verify_commercial_collections.py",
        ".github/scripts/verify_erp_expansion_browser.py",
        ".github/scripts/benchmark_enterprise_finance.py",
    ]
    for relative in paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    if mutation in {"policy_image", "undeclared"}:
        path = tmp_path / POLICY
        document = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "policy_image":
            document["current_images"]["native_acceptance"] = "postgres:latest"
        else:
            document["ignore_failure"] = True
        path.write_text(json.dumps(document), encoding="utf-8")
    else:
        relative = {
            "historical": "docs/security/supply-chain-policy.v1.json",
            "ci_image": ".github/workflows/ci.yml",
            "native_image": ".github/scripts/verify_commercial_collections.py",
        }[mutation]
        path = tmp_path / relative
        text = path.read_text(encoding="utf-8")
        if mutation == "historical":
            text = text.replace("reconforge-supply-chain", "changed-policy")
        else:
            text = text.replace(str(VALIDATOR["IMAGE_16"] if mutation == "ci_image" else VALIDATOR["IMAGE_17"]), "postgres:latest")
        path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        VALIDATOR["validate"](tmp_path)
