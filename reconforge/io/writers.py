"""Writers for tabular and structured reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class _ExactDecimalToken:
    text: str


def canonical_decimal_text(value: Decimal) -> str:
    """Return a finite Decimal as context-independent plain canonical text."""

    if not value.is_finite():
        raise ValueError("exact JSON decimal values must be finite")
    if value == 0:
        return "0"
    sign, raw_digits, raw_exponent = value.as_tuple()
    exponent = int(raw_exponent)
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    digit_text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = digit_text + ("0" * exponent)
    else:
        point = len(digit_text) + exponent
        text = f"{digit_text[:point]}.{digit_text[point:]}" if point > 0 else f"0.{('0' * -point)}{digit_text}"
    return f"-{text}" if sign else text


def _prepare_exact_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _ExactDecimalToken(canonical_decimal_text(value))
    if isinstance(value, dict):
        return {key: _prepare_exact_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_prepare_exact_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return _prepare_exact_json(json_default(value))


def _contains_marker_prefix(value: Any, prefix: str) -> bool:
    if isinstance(value, str):
        return prefix in value
    if isinstance(value, dict):
        return any(
            (isinstance(key, str) and prefix in key) or _contains_marker_prefix(item, prefix)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_marker_prefix(item, prefix) for item in value)
    return False


def exact_json_dumps(payload: Any, *, indent: int | None = 2) -> str:
    """Serialize Decimal values as exact JSON numbers without a float boundary.

    The standard-library encoder does not accept Decimal. This function first
    replaces Decimals with collision-checked private markers, uses the standard
    encoder for all JSON syntax and escaping, then substitutes only those quoted
    markers with validated canonical number lexemes.
    """

    prepared = _prepare_exact_json(payload)
    marker_prefix = "\x00reconforge:exact-decimal:"
    while _contains_marker_prefix(prepared, marker_prefix):
        marker_prefix += ":"
    replacements: dict[str, str] = {}

    def materialize(value: Any) -> Any:
        if isinstance(value, _ExactDecimalToken):
            marker = f"{marker_prefix}{len(replacements)}"
            replacements[marker] = value.text
            return marker
        if isinstance(value, dict):
            return {key: materialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [materialize(item) for item in value]
        return value

    encoded = json.dumps(materialize(prepared), indent=indent, allow_nan=False)
    for marker, decimal_text in replacements.items():
        encoded = encoded.replace(json.dumps(marker), decimal_text)
    return encoded


def ensure_output_dir(path: Path | str) -> Path:
    """Create an output directory and return it."""

    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def json_default(value: Any) -> str | float | int | None:
    """JSON serializer for pandas and date values."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return str(value)


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records."""

    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (datetime, date, pd.Timestamp)):
                cleaned[str(key)] = value.isoformat()
            elif pd.isna(value):
                cleaned[str(key)] = None
            elif hasattr(value, "item"):
                cleaned[str(key)] = value.item()
            else:
                cleaned[str(key)] = value
        records.append(cleaned)
    return records


def write_csv(frame: pd.DataFrame, output_dir: Path | str, name: str) -> Path:
    """Write a DataFrame as CSV."""

    output_path = ensure_output_dir(output_dir) / f"{name}.csv"
    frame.to_csv(output_path, index=False)
    return output_path


def write_json(payload: dict[str, Any], output_dir: Path | str, name: str) -> Path:
    """Write structured JSON."""

    output_path = ensure_output_dir(output_dir) / f"{name}.json"
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
        handle.write("\n")
    return output_path


def write_frame_json(frame: pd.DataFrame, output_dir: Path | str, name: str) -> Path:
    """Write a DataFrame as JSON records."""

    return write_json({"records": frame_to_records(frame)}, output_dir, name)


def write_report_frames(frames: dict[str, pd.DataFrame], output_dir: Path | str, prefix: str) -> list[Path]:
    """Write a collection of report frames to CSV and JSON files."""

    paths: list[Path] = []
    for name, frame in frames.items():
        safe_name = f"{prefix}_{name}"
        paths.append(write_csv(frame, output_dir, safe_name))
        paths.append(write_frame_json(frame, output_dir, safe_name))
    return paths
