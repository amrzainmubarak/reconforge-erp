"""Download registry helpers for local file-serving routes."""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def is_safe_download_key(value: str) -> bool:
    """Return whether a public download key is safe to use for registry lookup."""

    if not value or value != value.strip():
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    if value.startswith("/") or "\\" in value:
        return False
    if value.startswith("//") or "//" in value:
        return False
    if _WINDOWS_DRIVE_PREFIX.match(value):
        return False
    if ".." in value:
        return False

    parts = value.split("/")
    return all(part and part != "." for part in parts)


def build_download_registry(
    base_dir: Path | str,
    *,
    allowed_suffixes: set[str],
    recursive: bool = False,
) -> dict[str, Path]:
    """Build a public download-key registry from files already present under base_dir."""

    base_path = Path(base_dir).resolve()
    if not base_path.exists() or not base_path.is_dir():
        return {}

    normalized_suffixes = {suffix.lower() for suffix in allowed_suffixes}
    registry: dict[str, Path] = {}
    candidates = base_path.rglob("*") if recursive else base_path.iterdir()

    for candidate in candidates:
        if not candidate.is_file() or candidate.suffix.lower() not in normalized_suffixes:
            continue

        resolved = candidate.resolve()
        try:
            resolved.relative_to(base_path)
        except ValueError:
            continue

        key = candidate.relative_to(base_path).as_posix() if recursive else candidate.name
        if is_safe_download_key(key):
            registry[key] = resolved

    return registry


def get_registered_download(registry: dict[str, Path], key: str) -> Path:
    """Return a registered path for a validated public download key."""

    if not is_safe_download_key(key):
        raise ValueError("Unsafe download key")
    try:
        return registry[key]
    except KeyError as exc:
        raise FileNotFoundError(key) from exc
