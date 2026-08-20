from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "verify_postgres_native_tools.py"
SPEC = importlib.util.spec_from_file_location("verify_postgres_native_tools", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _toolchain(
    tmp_path: Path,
    *,
    tool_suffix: str = "",
    config_suffix: str = "",
) -> tuple[Path, dict[str, str], dict[tuple[str, ...], str]]:
    bindir = tmp_path / "postgres" / "16" / "bin"
    bindir.mkdir(parents=True)
    paths: dict[str, str] = {}
    probes: dict[tuple[str, ...], str] = {}
    pg_config = bindir / f"pg_config{config_suffix}"
    pg_config.touch()
    pg_config.chmod(0o755)
    paths["pg_config"] = str(pg_config)
    probes[(str(pg_config), "--version")] = "PostgreSQL 16.14"
    probes[(str(pg_config), "--bindir")] = str(bindir)
    for tool in MODULE._REQUIRED_TOOLS:
        executable = bindir / f"{tool}{tool_suffix}"
        executable.touch()
        executable.chmod(0o755)
        paths[tool] = str(executable)
        probes[(str(executable), "--version")] = f"{tool} (PostgreSQL) 16.14"
    return bindir, paths, probes


def test_validate_native_tools_binds_every_tool_to_expected_major(tmp_path: Path) -> None:
    bindir, paths, probes = _toolchain(tmp_path)

    def which(name: str) -> str | None:
        return paths.get(name)

    def probe(argv: Sequence[str]) -> str:
        return probes[tuple(argv)]

    assert MODULE.validate_native_tools(expected_major=16, which=which, probe=probe) == bindir.resolve()


def test_validate_native_tools_accepts_windows_style_tool_suffixes(tmp_path: Path) -> None:
    bindir, paths, probes = _toolchain(tmp_path, tool_suffix=".exe", config_suffix=".exe")

    def which(name: str) -> str | None:
        return paths.get(name)

    def probe(argv: Sequence[str]) -> str:
        return probes[tuple(argv)]

    assert MODULE.validate_native_tools(expected_major=16, which=which, probe=probe) == bindir.resolve()


def test_validate_native_tools_rejects_path_tool_drift(tmp_path: Path) -> None:
    bindir, paths, probes = _toolchain(tmp_path)
    wrong = tmp_path / "postgres" / "17" / "bin" / "pg_dump"
    wrong.parent.mkdir(parents=True)
    wrong.touch()
    wrong.chmod(0o755)
    paths["pg_dump"] = str(wrong)

    def which(name: str) -> str | None:
        return paths.get(name)

    def probe(argv: Sequence[str]) -> str:
        return probes[tuple(argv)]

    with pytest.raises(MODULE.NativeToolchainError, match="PATH does not resolve pg_dump"):
        MODULE.validate_native_tools(expected_major=16, which=which, probe=probe)


def test_validate_native_tools_rejects_unexpected_major(tmp_path: Path) -> None:
    _bindir, paths, probes = _toolchain(tmp_path)
    pg_config = paths["pg_config"]
    probes[(pg_config, "--version")] = "PostgreSQL 17.5"

    def which(name: str) -> str | None:
        return paths.get(name)

    def probe(argv: Sequence[str]) -> str:
        return probes[tuple(argv)]

    with pytest.raises(MODULE.NativeToolchainError, match="pg_config major version"):
        MODULE.validate_native_tools(expected_major=16, which=which, probe=probe)


def test_validate_native_tools_ignores_case_for_windows_paths(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Case-insensitive Windows path normalization is Windows-only.")

    bindir, paths, probes = _toolchain(tmp_path, tool_suffix=".exe", config_suffix=".exe")

    def which(name: str) -> str | None:
        return paths[name].upper() if paths[name] else None

    def probe(argv: Sequence[str]) -> str:
        return probes[tuple(argv)]

    assert MODULE.validate_native_tools(expected_major=16, which=which, probe=probe) == bindir.resolve()
