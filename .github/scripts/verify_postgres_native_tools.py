"""Fail-closed validation for the PostgreSQL native client toolchain."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # nosec B404 - the argv is static and shell execution is disabled
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

_POSTGRES_VERSION = re.compile(r"\bPostgreSQL\)?\s+(\d+)(?:\.\d+)?\b")
_REQUIRED_TOOLS = ("pg_dump", "pg_restore", "createdb", "dropdb", "psql")
_TOOL_TIMEOUT_SECONDS = 30
_KNOWN_WINDOWS_TOOL_SUFFIXES = (".exe", ".cmd", ".bat")


class NativeToolchainError(RuntimeError):
    """Raised when the native PostgreSQL toolchain cannot be trusted."""


def _command_output(argv: Sequence[str]) -> str:
    """Run one version/configuration probe without exposing process details."""

    try:
        completed = subprocess.run(  # nosec B603 - argv is constructed from fixed tool names
            tuple(argv),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeToolchainError("PostgreSQL native tool probe could not execute safely.") from exc
    if completed.returncode != 0:
        raise NativeToolchainError("PostgreSQL native tool probe failed.")
    return (completed.stdout or "").strip()


def _major_version(output: str, *, label: str) -> int:
    match = _POSTGRES_VERSION.search(output)
    if match is None:
        raise NativeToolchainError(f"{label} did not report a PostgreSQL major version.")
    return int(match.group(1))


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _tool_candidate_suffixes() -> tuple[str, ...]:
    # Keep the Windows suffixes available on every host.  Besides making the
    # resolver tolerant of cross-platform package layouts, this lets the
    # validator exercise a Windows-style toolchain in Linux CI using synthetic
    # fixtures without weakening the executable and version checks below.
    suffixes: list[str] = ["", *_KNOWN_WINDOWS_TOOL_SUFFIXES]
    # Canonicalize and de-duplicate deterministically.
    seen: set[str] = set()
    normalized: list[str] = []
    for suffix in suffixes:
        suffix = suffix.lower()
        if suffix in seen:
            continue
        seen.add(suffix)
        normalized.append(suffix)
    if "" not in normalized:
        normalized.insert(0, "")
    return tuple(normalized)


def _resolve_tool_path(bindir: Path, tool: str) -> Path:
    for suffix in _tool_candidate_suffixes():
        candidate = bindir / f"{tool}{suffix}"
        if _is_executable(candidate):
            return candidate
    raise NativeToolchainError(f"Required PostgreSQL executable is missing: {tool}.")


def _is_same_tool_resolved(path_entry: str | None, expected_path: Path) -> bool:
    if not path_entry:
        return False
    try:
        resolved_entry = Path(path_entry).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    try:
        expected = expected_path.resolve(strict=True)
        if os.name == "nt":
            return os.path.normcase(str(resolved_entry)) == os.path.normcase(str(expected))
        return resolved_entry == expected
    except (OSError, RuntimeError):
        return False


def _is_same_tool_via_suffix(path_entry: str | None, expected_path: Path) -> bool:
    """Treat symlink-based dispatch as valid when it points exactly to the expected tool."""

    if not path_entry:
        return False
    try:
        entry_path = Path(path_entry).resolve()
        if entry_path == expected_path:
            return True
        if not _is_executable(entry_path):
            return False
        expected_name = expected_path.name
        entry_stat = entry_path.stat()
        expected_stat = expected_path.stat()
        return (
            os.path.normcase(entry_path.name) == os.path.normcase(expected_name)
            and entry_path != expected_path
            and entry_stat.st_dev == expected_stat.st_dev
            and entry_stat.st_ino == expected_stat.st_ino
        )
    except (OSError, RuntimeError):
        return False


def _canonical_probe_path(path_entry: str) -> Path:
    """Recover the filesystem's canonical filename casing on Windows.

    ``shutil.which`` may return a differently-cased spelling of an executable
    path. The path is semantically valid on Windows, but injected probe
    functions and audit logs need the actual directory entry.
    """

    candidate = Path(path_entry)
    if os.name != "nt":
        return candidate
    try:
        parent = candidate.parent.resolve(strict=True)
        for child in parent.iterdir():
            if child.name.casefold() == candidate.name.casefold():
                return child
    except (OSError, RuntimeError):
        pass
    return candidate


def validate_native_tools(
    *,
    expected_major: int,
    which: Callable[[str], str | None] = shutil.which,
    probe: Callable[[Sequence[str]], str] = _command_output,
) -> Path:
    """Validate every required executable and return the versioned bindir."""

    if isinstance(expected_major, bool) or not isinstance(expected_major, int) or expected_major < 1:
        raise NativeToolchainError("Expected PostgreSQL major must be a positive integer.")

    pg_config = which("pg_config")
    if not pg_config:
        raise NativeToolchainError("pg_config is not available on PATH.")
    pg_config_probe_path = _canonical_probe_path(pg_config)
    if _major_version(probe((str(pg_config_probe_path), "--version")), label="pg_config") != expected_major:
        raise NativeToolchainError("pg_config major version does not match the PostgreSQL service.")

    raw_bindir = probe((str(pg_config_probe_path), "--bindir"))
    bindir = Path(raw_bindir).expanduser()
    if not bindir.is_absolute() or not bindir.is_dir():
        raise NativeToolchainError("pg_config returned an invalid PostgreSQL tool bindir.")
    resolved_bindir = bindir.resolve()

    for tool in _REQUIRED_TOOLS:
        expected_path = _resolve_tool_path(resolved_bindir, tool)
        if not _is_executable(expected_path):
            raise NativeToolchainError(f"Required PostgreSQL executable is missing: {tool}.")
        if _major_version(probe((str(expected_path), "--version")), label=tool) != expected_major:
            raise NativeToolchainError(f"PostgreSQL executable has an unexpected major version: {tool}.")
        path_entry = which(tool)
        if not (
            _is_same_tool_resolved(path_entry, expected_path) or _is_same_tool_via_suffix(path_entry, expected_path)
        ):
            raise NativeToolchainError(f"PATH does not resolve {tool} to the versioned PostgreSQL bindir.")

    return resolved_bindir


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-major", type=int, required=True)
    parser.add_argument("--print-bindir", action="store_true")
    args = parser.parse_args(argv)
    try:
        bindir = validate_native_tools(expected_major=args.expected_major)
    except NativeToolchainError as exc:
        print(f"native PostgreSQL toolchain validation failed: {exc}", file=sys.stderr)
        return 1
    if args.print_bindir:
        print(bindir)
    else:
        print(f"validated PostgreSQL {args.expected_major} native tools in {bindir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
