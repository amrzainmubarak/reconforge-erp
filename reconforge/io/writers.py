"""Writers for tabular and structured reports."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


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
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
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
