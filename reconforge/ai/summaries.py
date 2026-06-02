"""Summary helpers for exception explanation commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reconforge.ai.offline import offline_exception_explanation


def _flatten_payload(payload: Any) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("exceptions", "top_exceptions", "results", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def explain_exception_file(input_path: Path | str, exception_id: str) -> str:
    """Explain an exception from a local JSON file."""

    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = _flatten_payload(payload)
    for record in records:
        identifiers = {
            str(record.get("exception_id", "")),
            str(record.get("rule_id", "")),
            str(record.get("move_id", "")),
            str(record.get("entry_id", "")),
        }
        if exception_id in identifiers:
            return offline_exception_explanation(record)
    if records:
        return offline_exception_explanation(records[0])
    raise ValueError(f"No exceptions found in {path}")
