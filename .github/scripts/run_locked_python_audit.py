#!/usr/bin/env python3
"""Run the fail-closed Python dependency audit from the universal lock."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class LockedPythonAuditError(RuntimeError):
    """Raised when the locked audit cannot be executed safely."""


_UV_VERSION = re.compile(r"^uv (?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")


def _load_policy(project_root: Path) -> dict[str, Any]:
    policy_path = project_root / "docs" / "security" / "supply-chain-policy.v1.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockedPythonAuditError("supply-chain policy is unavailable or malformed") from exc
    if not isinstance(policy, dict):
        raise LockedPythonAuditError("supply-chain policy root must be an object")
    return policy


def _policy_runtime(policy: dict[str, Any], python_version: str) -> tuple[str, str]:
    try:
        resolution = policy["python_resolution"]
        audits = policy["dependency_audits"]
        required_uv = resolution["manager_version"]
        supported_python = resolution["supported_python"]
        locked_extra = audits["python"]["locked_extra"]
    except (KeyError, TypeError) as exc:
        raise LockedPythonAuditError("supply-chain policy is missing the Python audit contract") from exc
    if not isinstance(required_uv, str) or not isinstance(locked_extra, str):
        raise LockedPythonAuditError("supply-chain policy Python audit values are malformed")
    if not isinstance(supported_python, list) or python_version not in supported_python:
        raise LockedPythonAuditError(f"Python {python_version} is outside the policy-supported audit matrix")
    return required_uv, locked_extra


def _parse_uv_version(output: str) -> str:
    match = _UV_VERSION.match(output.strip())
    if match is None:
        raise LockedPythonAuditError("uv version output is malformed")
    return match.group("version")


def _scanner_command(
    *,
    execution_mode: str,
    python_version: str,
    locked_extra: str,
    requirements_path: Path,
    report_path: Path,
) -> list[str]:
    if execution_mode == "isolated":
        prefix = [
            "uv",
            "run",
            "--isolated",
            "--locked",
            "--extra",
            locked_extra,
            "--no-editable",
            "--python",
            python_version,
        ]
    elif execution_mode == "current":
        prefix = ["uv", "run", "--no-sync"]
    else:
        raise LockedPythonAuditError(f"unsupported audit execution mode: {execution_mode}")
    return [
        *prefix,
        "pip-audit",
        "--require-hashes",
        "--disable-pip",
        "--cache-dir",
        str(report_path.parent / "cache"),
        "--requirement",
        str(requirements_path),
        "--format",
        "json",
        "--output",
        str(report_path),
    ]


def _run(
    command: list[str],
    *,
    project_root: Path,
    timeout_seconds: int,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - every executable and argument is a closed local value
            command,
            cwd=project_root,
            check=False,
            capture_output=capture_output,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise LockedPythonAuditError(f"required executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LockedPythonAuditError(f"audit command exceeded the {timeout_seconds}-second ceiling") from exc


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise LockedPythonAuditError(f"{label} failed with exit code {result.returncode}")


def run_locked_audit(
    *,
    project_root: Path,
    python_version: str,
    execution_mode: str,
    timeout_seconds: int,
) -> int:
    root = project_root.resolve()
    validator = root / ".github" / "scripts" / "validate_supply_chain_policy.py"
    if timeout_seconds < 1:
        raise LockedPythonAuditError("timeout must be a positive integer")

    policy = _load_policy(root)
    required_uv, locked_extra = _policy_runtime(policy, python_version)

    uv_version = _run(
        ["uv", "--version"],
        project_root=root,
        timeout_seconds=timeout_seconds,
        capture_output=True,
    )
    _require_success(uv_version, "uv version check")
    actual_uv = _parse_uv_version(uv_version.stdout)
    if actual_uv != required_uv:
        raise LockedPythonAuditError(f"uv {actual_uv} does not match policy-required uv {required_uv}")

    policy_check = _run(
        [sys.executable, str(validator), "--project-root", str(root)],
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    _require_success(policy_check, "supply-chain policy validation")

    lock_check = _run(
        ["uv", "lock", "--check"],
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    _require_success(lock_check, "universal lock validation")

    with tempfile.TemporaryDirectory(prefix="reconforge-locked-audit-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        requirements_path = temporary_root / "all-extras.txt"
        report_path = temporary_root / "pip-audit.json"
        export = _run(
            [
                "uv",
                "export",
                "--locked",
                "--all-extras",
                "--no-emit-project",
                "--format",
                "requirements.txt",
                "--quiet",
                "--output-file",
                str(requirements_path),
            ],
            project_root=root,
            timeout_seconds=timeout_seconds,
        )
        _require_success(export, "hash-locked requirements export")

        scanner = _run(
            _scanner_command(
                execution_mode=execution_mode,
                python_version=python_version,
                locked_extra=locked_extra,
                requirements_path=requirements_path,
                report_path=report_path,
            ),
            project_root=root,
            timeout_seconds=timeout_seconds,
        )
        enforcement = _run(
            [
                sys.executable,
                str(validator),
                "--project-root",
                str(root),
                "--pip-audit-report",
                str(report_path),
                "--pip-audit-exit-code",
                str(scanner.returncode),
            ],
            project_root=root,
            timeout_seconds=timeout_seconds,
        )
        if enforcement.returncode != 0:
            return enforcement.returncode

    print(
        json.dumps(
            {
                "execution_mode": execution_mode,
                "python": python_version,
                "status": "locked-python-audit-passed",
                "uv": required_uv,
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--python-version", default="3.12")
    parser.add_argument("--execution-mode", choices=("isolated", "current"), default="isolated")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return run_locked_audit(
            project_root=args.project_root,
            python_version=args.python_version,
            execution_mode=args.execution_mode,
            timeout_seconds=args.timeout_seconds,
        )
    except LockedPythonAuditError as exc:
        print(f"locked-python-audit-error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
