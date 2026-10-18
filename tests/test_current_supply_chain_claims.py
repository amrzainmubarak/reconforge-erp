from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_supply_chain_validator_and_documentation_agree() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".github" / "scripts" / "validate_supply_chain_policy.py"),
            "--project-root",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(completed.stdout)
    assert report["status"] == "valid"
    assert report["npm_packages"] == 211
    assert report["npm_integrity_gap_entries"] == 0

    current_surfaces = (
        ROOT / "docs" / "execution" / "GAP_MATRIX.md",
        ROOT / "docs" / "security-whitepaper.md",
        ROOT / "docs" / "execution" / "DOCUMENTATION_DRIFT.md",
    )
    for path in current_surfaces:
        text = path.read_text(encoding="utf-8")
        assert "155 entries still lack embedded SRI" not in text
        assert "155 missing npm SRI entries remain open" not in text
