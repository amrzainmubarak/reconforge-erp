from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "run_locked_python_audit.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_locked_python_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT_MODULE = _load_module()
LockedPythonAuditError = AUDIT_MODULE.LockedPythonAuditError


def test_uv_version_parser_accepts_pinned_version_with_build_metadata() -> None:
    assert AUDIT_MODULE._parse_uv_version("uv 0.11.32 (3010295ae 2026-07-23)") == "0.11.32"

    with pytest.raises(LockedPythonAuditError, match="malformed"):
        AUDIT_MODULE._parse_uv_version("0.11.32")


def test_policy_runtime_rejects_an_unsupported_python_matrix_cell() -> None:
    policy = AUDIT_MODULE._load_policy(ROOT)

    assert AUDIT_MODULE._policy_runtime(policy, "3.11") == ("0.11.32", "dev")
    assert AUDIT_MODULE._policy_runtime(policy, "3.12") == ("0.11.32", "dev")
    with pytest.raises(LockedPythonAuditError, match="outside"):
        AUDIT_MODULE._policy_runtime(policy, "3.14")


def test_isolated_scanner_uses_the_locked_dev_tool_and_hash_export(tmp_path: Path) -> None:
    command = AUDIT_MODULE._scanner_command(
        execution_mode="isolated",
        python_version="3.12",
        locked_extra="dev",
        requirements_path=tmp_path / "requirements.txt",
        report_path=tmp_path / "report.json",
    )

    assert command[:10] == [
        "uv",
        "run",
        "--isolated",
        "--locked",
        "--extra",
        "dev",
        "--no-editable",
        "--python",
        "3.12",
        "pip-audit",
    ]
    assert command[10:] == [
        "--require-hashes",
        "--disable-pip",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--requirement",
        str(tmp_path / "requirements.txt"),
        "--format",
        "json",
        "--output",
        str(tmp_path / "report.json"),
    ]


def test_current_scanner_never_synchronizes_or_resolves(tmp_path: Path) -> None:
    command = AUDIT_MODULE._scanner_command(
        execution_mode="current",
        python_version="3.11",
        locked_extra="dev",
        requirements_path=tmp_path / "requirements.txt",
        report_path=tmp_path / "report.json",
    )

    assert command[:4] == ["uv", "run", "--no-sync", "pip-audit"]
    assert "--require-hashes" in command
    assert "--disable-pip" in command
    assert command[command.index("--cache-dir") + 1] == str(tmp_path / "cache")


def test_unknown_scanner_mode_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LockedPythonAuditError, match="unsupported"):
        AUDIT_MODULE._scanner_command(
            execution_mode="ambient",
            python_version="3.12",
            locked_extra="dev",
            requirements_path=tmp_path / "requirements.txt",
            report_path=tmp_path / "report.json",
        )


def test_make_security_uses_the_locked_runner_not_an_ambient_audit() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    security = makefile.split("security:\n", maxsplit=1)[1].split("\n\ndemo:", maxsplit=1)[0]

    assert "python .github/scripts/run_locked_python_audit.py --project-root ." in security
    assert "\n\tpip-audit" not in security
