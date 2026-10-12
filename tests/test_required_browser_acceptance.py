"""Wire acceptance must reject missing, skipped and retry-flaky execution."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "required_erp_browser_runner", ROOT / ".github/scripts/verify_erp_expansion_browser.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_required_wire_cycle_accepts_one_complete_nonflaky_execution() -> None:
    RUNNER.require_browser_acceptance({"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0, "duration": 100})


@pytest.mark.parametrize("stats", [
    None, {}, {"expected": 0, "skipped": 1, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 1, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 1, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 1},
    {"expected": True, "skipped": 0, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": False},
    {"expected": 2, "skipped": 0, "unexpected": 0, "flaky": 0},
])
def test_required_wire_cycle_refuses_incomplete_execution(stats: Any) -> None:
    with pytest.raises(RuntimeError, match="browser"):
        RUNNER.require_browser_acceptance(stats)
