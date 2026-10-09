"""Real child-process contracts for mandatory native evidence admission."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("source", "options", "exit_code", "counts"), [
    ("def test_actual_execution():\n    assert 1 + 1 == 2\n", (), 0,
        "collected=1, skipped=0, xfailed=0, xpassed=0, stats_available=1"),
    ("import pytest\n@pytest.mark.skip(reason='native prerequisite')\ndef test_native():\n    assert True\n", (), 1,
        "collected=1, skipped=1, xfailed=0, xpassed=0, stats_available=1"),
    ("import pytest\n@pytest.mark.xfail(reason='unaccepted native prerequisite')\ndef test_native():\n    assert False\n", (), 1,
        "collected=1, skipped=0, xfailed=1, xpassed=0, stats_available=1"),
    ("import pytest\n@pytest.mark.xfail(reason='unexpected native success')\ndef test_native():\n    assert True\n", (), 1,
        "collected=1, skipped=0, xfailed=0, xpassed=1, stats_available=1"),
    ("import pytest\npytest.skip('collection prerequisite', allow_module_level=True)\n", (), 5,
        "collected=0, skipped=1, xfailed=0, xpassed=0, stats_available=1"),
    ("no_test_was_defined = True\n", (), 5,
        "collected=0, skipped=0, xfailed=0, xpassed=0, stats_available=1"),
    ("def test_actual_execution():\n    assert True\n", ("-p", "no:terminal"), 1,
        "collected=1, skipped=0, xfailed=0, xpassed=0, stats_available=0"),
    ("def test_existing_failure():\n    assert False\n", (), 1,
        "collected=1, skipped=0, xfailed=0, xpassed=0, stats_available=1"),
    ("raise ValueError('synthetic collection failure')\n", (), 2,
        "collected=0, skipped=0, xfailed=0, xpassed=0, stats_available=1"),
], ids=["executed-pass", "skipped-test", "xfail", "xpass", "collection-skip", "no-tests",
        "terminal-unavailable", "existing-failure", "existing-collection-error"])
def test_mandatory_native_gate_admits_only_complete_child_evidence(
    tmp_path: Path, source: str, options: tuple[str, ...], exit_code: int, counts: str,
) -> None:
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    case = tmp_path / "test_native_case.py"
    case.write_text(source, encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                   "PYTEST_ADDOPTS": "-p tests.mandatory_native_gate"}
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", str(config), "--confcutdir", str(tmp_path),
        *options, str(case)], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode == exit_code, output
    assert "mandatory native gate: " + counts in output

