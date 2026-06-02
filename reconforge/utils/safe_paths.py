"""Safe path resolution for local file-serving routes."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


def safe_resolve_child(
    base_dir: Path | str,
    user_value: str,
    *,
    allowed_suffixes: set[str] | None = None,
) -> Path:
    """Resolve a user-provided child path inside an allowed base directory."""

    base_path = Path(base_dir).resolve()
    raw_value = user_value.strip()
    if not raw_value:
        raise ValueError("Path value is required")

    child = Path(raw_value)
    if child.is_absolute() or PureWindowsPath(raw_value).is_absolute():
        raise ValueError("Absolute paths are not allowed")
    if "\\" in raw_value:
        raise ValueError("Path separators are not allowed")
    if ".." in child.parts:
        raise ValueError("Path traversal is not allowed")

    target = (base_path / child).resolve()
    try:
        target.relative_to(base_path)
    except ValueError as exc:
        raise ValueError("Resolved path is outside the allowed directory") from exc

    if allowed_suffixes is not None:
        normalized_suffixes = {suffix.lower() for suffix in allowed_suffixes}
        if target.suffix.lower() not in normalized_suffixes:
            raise ValueError("File type is not allowed")

    return target
