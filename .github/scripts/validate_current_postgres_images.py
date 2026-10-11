"""Check current PostgreSQL pins without rewriting source-bound historical evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

import yaml

POLICY = "docs/security/postgres-current-images.wave5.v1.json"
IMAGE_16 = "postgres:16.15-alpine@sha256:1a66d744c1b459e13b05a8fca341da84cb63383e99ce262210efee5a319d4551"
IMAGE_17 = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3"
LEGACY_DIGEST = "8629e9c6d2f57eaf74da0dc20d54293241a97ce8c7fc6b5d10e2926048cf4992"


def validate(root: Path) -> dict[str, object]:
    policy = json.loads((root / POLICY).read_text(encoding="utf-8"))
    if set(policy) != {
        "schema_version", "policy_id", "reviewed_at", "current_images",
        "retained_policy_source_sha256", "scope", "official_references",
    }:
        raise ValueError("current PostgreSQL policy has undeclared or missing fields")
    if (
        policy["schema_version"] != 1
        or policy["policy_id"] != "reconforge-current-postgres-wave5"
        or policy["reviewed_at"] != "2026-10-11"
        or policy["current_images"] != {"server_boundaries": IMAGE_16, "native_acceptance": IMAGE_17}
        or policy["retained_policy_source_sha256"] != LEGACY_DIGEST
    ):
        raise ValueError("current PostgreSQL identity or reviewed image pins drifted")
    if (
        not isinstance(policy["scope"], str)
        or "not current security acceptance" not in policy["scope"]
        or policy["official_references"] != [
            "https://www.postgresql.org/support/versioning/",
            "https://www.postgresql.org/docs/17/release-17-11.html",
            "https://www.postgresql.org/support/security/17/",
        ]
    ):
        raise ValueError("current PostgreSQL review scope or official references drifted")
    original = (root / "docs/security/supply-chain-policy.v1.json").read_text(encoding="utf-8")
    digest = hashlib.sha256(original.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    if digest != LEGACY_DIGEST:
        raise ValueError("historical supply-chain policy source fingerprint changed")
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    if workflow["jobs"]["server-boundaries"]["services"]["postgres"]["image"] != IMAGE_16:
        raise ValueError("current server-boundary PostgreSQL image drifted")
    for relative in (
        ".github/scripts/verify_commercial_collections.py",
        ".github/scripts/verify_erp_expansion_browser.py",
        ".github/scripts/benchmark_enterprise_finance.py",
        ".github/scripts/benchmark_native_api_runtime.py",
    ):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        definitions = [
            ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "IMAGE" for target in node.targets)
        ]
        if definitions != [IMAGE_17]:
            raise ValueError(f"current native PostgreSQL image drifted in {relative}")
    return {"accepted": True, "current_images": policy["current_images"], "historical_policy_source_unchanged": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
