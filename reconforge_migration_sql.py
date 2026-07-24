"""Helpers for Alembic migration SQL constant loading.

The server-boundary job in CI can fail import resolution for optional package
submodules during Alembic migration discovery. These utilities keep migration
scripts importable even if ``reconforge.infrastructure`` is temporarily
unavailable at import time, by loading schema SQL constants directly from source
files as a deterministic fallback.
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path

_MIGRATION_ROOT = Path(__file__).resolve().parent
_POSTGRES_SCHEMA_CONST = re.compile(
    r"(?m)^"
    r"(?P<name>[A-Z0-9_]+)\s*=\s*\"\"\""
    r"(?P<body>.*?)\"\"\""
)


def load_postgres_schema_sql(module_name: str, constant_name: str) -> str:
    """Load a Postgres DDL SQL constant, preferring runtime import.

    Migration discovery executes revision modules directly and can hit import
    path differences between local and CI environments. In that case, this helper
    falls back to extracting the constant from the known source file.
    """

    try:
        module = import_module(module_name)
        value = getattr(module, constant_name, None)
        if isinstance(value, str):
            return value
    except Exception:
        # If import-time resolution fails in an environment, keep going with
        # a stable file-based fallback.
        pass

    module_path = Path(*module_name.split(".")).with_suffix(".py")
    source_path = _MIGRATION_ROOT / module_path
    if not source_path.exists():
        raise RuntimeError(f"Cannot read migration schema source: {source_path}")

    source = source_path.read_text(encoding="utf-8")
    for match in _POSTGRES_SCHEMA_CONST.finditer(source):
        if match.group("name") == constant_name:
            return match.group("body")

    raise RuntimeError(
        f"Cannot find {constant_name!r} in {source_path.as_posix()}"
    )
