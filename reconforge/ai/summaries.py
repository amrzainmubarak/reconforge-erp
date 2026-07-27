"""Summary helpers for exception explanation commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reconforge.ai.offline import offline_exception_explanation
from reconforge.io.generated import GeneratedArtifactError, read_generated_json_value_document
from reconforge.io.structured import StructuredDocumentPolicy

EXCEPTION_EXPLANATION_JSON_PROFILE = "exception-explanation-json-ingress-v1"
EXCEPTION_EXPLANATION_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=16 * 1024 * 1024,
    max_nodes=500_000,
    max_depth=32,
    max_collection_items=100_000,
    max_scalar_characters=1_000_000,
    max_yaml_aliases=1,
)


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
    try:
        payload = read_generated_json_value_document(
            path,
            policy=EXCEPTION_EXPLANATION_JSON_POLICY,
            profile_id=EXCEPTION_EXPLANATION_JSON_PROFILE,
            mode="display",
        ).payload
    except GeneratedArtifactError as exc:
        raise ValueError("Exception JSON failed safety validation.") from exc
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
    raise ValueError("No exceptions found in input JSON.")
