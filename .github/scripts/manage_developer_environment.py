#!/usr/bin/env python3
"""Diagnose or create a locked, platform-specific ReconForge development environment."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


class DeveloperEnvironmentError(RuntimeError):
    """Raised when a developer environment cannot be handled safely."""


_UV_VERSION = re.compile(r"^uv (?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")
_PYTHON_VERSION = re.compile(r"^Python (?P<major>[0-9]+)\.(?P<minor>[0-9]+)(?:\.[0-9]+)?(?:\s|$)")


def _default_environment_name(system_platform: str) -> str:
    if system_platform == "win32":
        return ".venv-windows"
    if system_platform == "darwin":
        return ".venv-macos"
    return ".venv-linux"


def _load_policy(project_root: Path) -> dict[str, Any]:
    path = project_root / "docs" / "security" / "supply-chain-policy.v1.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeveloperEnvironmentError("supply-chain policy is unavailable or malformed") from exc
    if not isinstance(value, dict):
        raise DeveloperEnvironmentError("supply-chain policy root must be an object")
    return value


def _policy_runtime(policy: dict[str, Any], python_version: str) -> str:
    try:
        resolution = policy["python_resolution"]
        required_uv = resolution["manager_version"]
        supported_python = resolution["supported_python"]
    except (KeyError, TypeError) as exc:
        raise DeveloperEnvironmentError("supply-chain policy is missing the Python resolution contract") from exc
    if not isinstance(required_uv, str) or not isinstance(supported_python, list):
        raise DeveloperEnvironmentError("supply-chain policy Python resolution values are malformed")
    if python_version not in supported_python:
        raise DeveloperEnvironmentError(f"Python {python_version} is outside the supported matrix")
    return required_uv


def _resolve_environment_path(project_root: Path, environment_path: Path) -> Path:
    root = project_root.resolve(strict=True)
    candidate = environment_path if environment_path.is_absolute() else root / environment_path
    resolved = candidate.resolve(strict=False)
    if resolved.parent != root or not resolved.name.startswith(".venv-"):
        raise DeveloperEnvironmentError("environment path must be a direct project child named .venv-*")
    if _is_reparse_point(candidate):
        raise DeveloperEnvironmentError("environment path must not be a symbolic link or reparse point")
    return resolved


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _interpreter_path(environment_path: Path, platform_name: str) -> Path:
    if platform_name == "nt":
        return environment_path / "Scripts" / "python.exe"
    return environment_path / "bin" / "python"


def _run(
    command: list[str],
    *,
    project_root: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - executable and arguments are closed by this script
            command,
            cwd=project_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise DeveloperEnvironmentError(f"required executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DeveloperEnvironmentError(f"developer environment command exceeded {timeout_seconds} seconds") from exc


def _require_uv(project_root: Path, required_uv: str, timeout_seconds: int) -> None:
    result = _run(["uv", "--version"], project_root=project_root, timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        raise DeveloperEnvironmentError(f"uv version check failed with exit code {result.returncode}")
    match = _UV_VERSION.match(result.stdout.strip())
    if match is None:
        raise DeveloperEnvironmentError("uv version output is malformed")
    actual = match.group("version")
    if actual != required_uv:
        raise DeveloperEnvironmentError(f"uv {actual} does not match policy-required uv {required_uv}")


def _require_current_lock(project_root: Path, timeout_seconds: int) -> None:
    result = _run(["uv", "lock", "--check"], project_root=project_root, timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        raise DeveloperEnvironmentError(f"universal lock validation failed with exit code {result.returncode}")


def _inspect_environment(
    environment_path: Path,
    *,
    python_version: str,
    platform_name: str,
    project_root: Path,
    timeout_seconds: int,
) -> dict[str, str]:
    relative_path = environment_path.relative_to(project_root).as_posix()
    if not environment_path.exists():
        return {
            "code": "DEVENV-ENV-MISSING",
            "detail": "run the non-destructive bootstrap command",
            "path": relative_path,
            "status": "missing",
        }
    if _is_reparse_point(environment_path):
        return {
            "code": "DEVENV-ENV-SYMLINK",
            "detail": "refusing a symbolic-link or reparse-point environment root",
            "path": relative_path,
            "status": "failed",
        }
    interpreter = _interpreter_path(environment_path, platform_name)
    if not interpreter.is_file():
        opposite = _interpreter_path(environment_path, "posix" if platform_name == "nt" else "nt")
        code = "DEVENV-ENV-FOREIGN" if opposite.exists() or (environment_path / "pyvenv.cfg").exists() else "DEVENV-ENV-MALFORMED"
        return {
            "code": code,
            "detail": "expected platform interpreter is absent; the existing directory was not modified",
            "path": relative_path,
            "status": "failed",
        }
    version = _run(
        [str(interpreter), "--version"],
        project_root=project_root,
        timeout_seconds=timeout_seconds,
    )
    combined = (version.stdout or version.stderr).strip()
    match = _PYTHON_VERSION.match(combined)
    if version.returncode != 0 or match is None:
        return {
            "code": "DEVENV-PYTHON-UNUSABLE",
            "detail": "environment interpreter cannot report a valid Python version",
            "path": relative_path,
            "status": "failed",
        }
    actual = f"{match.group('major')}.{match.group('minor')}"
    if actual != python_version:
        return {
            "code": "DEVENV-PYTHON-MISMATCH",
            "detail": f"environment uses Python {actual}; expected {python_version}",
            "path": relative_path,
            "status": "failed",
        }
    return {
        "code": "DEVENV-READY",
        "detail": f"platform interpreter reports Python {actual}",
        "path": relative_path,
        "status": "passed",
    }


def _activation_command(environment_path: Path, platform_name: str, project_root: Path) -> str:
    relative = environment_path.relative_to(project_root).as_posix()
    if platform_name == "nt":
        return f"& ./{relative}/Scripts/Activate.ps1"
    return f"source ./{relative}/bin/activate"


def _sync_command(python_version: str) -> list[str]:
    return [
        "uv",
        "sync",
        "--locked",
        "--all-extras",
        "--no-editable",
        "--python",
        python_version,
    ]


def _base_context(
    project_root: Path,
    environment_path: Path | None,
    python_version: str,
    timeout_seconds: int,
) -> tuple[Path, Path, str]:
    if timeout_seconds < 1:
        raise DeveloperEnvironmentError("timeout must be a positive integer")
    root = project_root.resolve(strict=True)
    requested_path = environment_path or Path(_default_environment_name(sys.platform))
    target = _resolve_environment_path(root, requested_path)
    required_uv = _policy_runtime(_load_policy(root), python_version)
    _require_uv(root, required_uv, timeout_seconds)
    _require_current_lock(root, timeout_seconds)
    return root, target, required_uv


def doctor(
    *,
    project_root: Path,
    environment_path: Path | None,
    python_version: str,
    timeout_seconds: int,
) -> int:
    root, target, required_uv = _base_context(project_root, environment_path, python_version, timeout_seconds)
    check = _inspect_environment(
        target,
        python_version=python_version,
        platform_name=os.name,
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    legacy_check = _inspect_environment(
        root / ".venv",
        python_version=python_version,
        platform_name=os.name,
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    payload = {
        "activation": _activation_command(target, os.name, root),
        "check": check,
        "legacy_project_environment": legacy_check,
        "python": python_version,
        "schema_version": 1,
        "status": "ready" if check["status"] == "passed" else "needs-bootstrap",
        "uv": required_uv,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if check["status"] == "passed" else 1


def bootstrap(
    *,
    project_root: Path,
    environment_path: Path | None,
    python_version: str,
    timeout_seconds: int,
) -> int:
    root, target, required_uv = _base_context(project_root, environment_path, python_version, timeout_seconds)
    before = _inspect_environment(
        target,
        python_version=python_version,
        platform_name=os.name,
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    if before["status"] == "failed":
        raise DeveloperEnvironmentError(f"{before['code']}: existing environment requires manual review")

    process_environment = os.environ.copy()
    process_environment["UV_PROJECT_ENVIRONMENT"] = str(target)
    sync = _run(
        _sync_command(python_version),
        project_root=root,
        timeout_seconds=timeout_seconds,
        environment=process_environment,
    )
    if sync.returncode != 0:
        raise DeveloperEnvironmentError(f"locked environment sync failed with exit code {sync.returncode}")

    product_doctor = _run(
        ["uv", "run", "--no-sync", "python", "-m", "reconforge.cli", "doctor"],
        project_root=root,
        timeout_seconds=timeout_seconds,
        environment=process_environment,
    )
    if product_doctor.returncode != 0:
        raise DeveloperEnvironmentError(f"ReconForge doctor failed with exit code {product_doctor.returncode}")

    after = _inspect_environment(
        target,
        python_version=python_version,
        platform_name=os.name,
        project_root=root,
        timeout_seconds=timeout_seconds,
    )
    if after["status"] != "passed":
        raise DeveloperEnvironmentError(f"{after['code']}: synchronized environment did not validate")
    print(
        json.dumps(
            {
                "activation": _activation_command(target, os.name, root),
                "check": after,
                "legacy_project_environment": _inspect_environment(
                    root / ".venv",
                    python_version=python_version,
                    platform_name=os.name,
                    project_root=root,
                    timeout_seconds=timeout_seconds,
                ),
                "python": python_version,
                "schema_version": 1,
                "status": "bootstrapped",
                "uv": required_uv,
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "bootstrap"):
        child = subparsers.add_parser(command)
        child.add_argument("--project-root", type=Path, default=Path.cwd())
        child.add_argument("--environment-path", type=Path)
        child.add_argument("--python-version", default="3.12")
        child.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main() -> int:
    args = _parser().parse_args()
    function = doctor if args.command == "doctor" else bootstrap
    try:
        return function(
            project_root=args.project_root,
            environment_path=args.environment_path,
            python_version=args.python_version,
            timeout_seconds=args.timeout_seconds,
        )
    except DeveloperEnvironmentError as exc:
        print(f"developer-environment-error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
