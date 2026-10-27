"""Prevent reintroduction of the release's reviewed vulnerable lock versions.

These minimum-version regressions complement live audits; they are not a scanner.
The corresponding advisory IDs and supported profiles are recorded in the release
security evidence. New advisories still require a live fail-closed audit.
"""

import json
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("package", "minimum"), [
    ("pillow", "13.0.0"),
    ("certifi", "2026.10.19"),
    ("filelock", "4.2.1"),
    ("virtualenv", "21.14.10"),
    ("setuptools", "84.1.0"),
    ("opentelemetry-api", "1.45.1"),
    ("opentelemetry-sdk", "1.45.1"),
])
def test_reviewed_python_advisory_fixes_remain_in_the_universal_lock(package: str, minimum: str) -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [entry["version"] for entry in lock["package"] if entry["name"] == package]
    assert versions
    assert all(Version(version) >= Version(minimum) for version in versions)


@pytest.mark.parametrize(("package", "minimum"), [("vite", "8.1.6"), ("undici", "7.30.1")])
def test_reviewed_npm_advisory_fixes_cover_every_locked_copy(package: str, minimum: str) -> None:
    lock = json.loads((ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    versions = [entry["version"] for name, entry in lock["packages"].items()
                if name.endswith("node_modules/" + package)]
    assert versions
    assert all(Version(version) >= Version(minimum) for version in versions)
