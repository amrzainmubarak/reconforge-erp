"""Local import and mapping inspection helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from reconforge.io.writers import ensure_output_dir, json_default
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName

SUPPORTED_INPUT_SUFFIXES = {".csv", ".xlsx", ".xls"}


@dataclass(frozen=True)
class HeaderScan:
    """Headers read from one local export file."""

    path: Path
    headers: list[str]
    status: str
    error: str = ""


@dataclass(frozen=True)
class FieldSuggestion:
    """Candidate source column for a canonical target field."""

    target_field: str
    candidate_column: str
    source_file: str
    score: float
    reason: str


@dataclass(frozen=True)
class DatasetInspection:
    """Inspection result for one mapped canonical dataset."""

    dataset: str
    input_file: str
    matched_fields: dict[str, str]
    missing_required_fields: list[str]
    missing_optional_fields: list[str]
    unknown_fields: list[str]
    suggestions: list[FieldSuggestion] = field(default_factory=list)


@dataclass(frozen=True)
class MappingInspectionResult:
    """Full mapping inspection result and generated reports."""

    input_path: Path
    pack_path: Path
    profile_id: str
    files: list[HeaderScan]
    datasets: list[DatasetInspection]
    report_json_path: Path
    report_markdown_path: Path

    @property
    def summary(self) -> dict[str, int]:
        return {
            "files_scanned": len(self.files),
            "files_with_errors": sum(1 for item in self.files if item.status != "ok"),
            "datasets_checked": len(self.datasets),
            "matched_fields": sum(len(item.matched_fields) for item in self.datasets),
            "missing_required_fields": sum(len(item.missing_required_fields) for item in self.datasets),
            "suggestions": sum(len(item.suggestions) for item in self.datasets),
        }


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.strip().lower()) if token}


def _read_headers(path: Path) -> HeaderScan:
    try:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=1)
        else:
            frame = pd.read_excel(path, dtype=str, keep_default_na=False, nrows=1)
    except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return HeaderScan(path=path, headers=[], status="error", error=str(exc))
    return HeaderScan(path=path, headers=[str(column) for column in frame.columns], status="ok")


def scan_input_headers(input_path: Path | str) -> list[HeaderScan]:
    """Read CSV/XLSX headers from a local export folder without reading full data."""

    base = Path(input_path)
    if not base.exists() or not base.is_dir():
        return []
    return [_read_headers(path) for path in sorted(base.iterdir()) if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES]


def _load_mapping(pack_path: Path) -> dict[str, Any]:
    mapping_path = pack_path / "mapping.yml"
    payload = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"mapping.yml must contain an object: {mapping_path}")
    return payload


def _dataset_name(filename: str) -> DatasetName | None:
    try:
        return DatasetName(Path(filename).stem)
    except ValueError:
        return None


def _canonical_scan(filename: str, scans: list[HeaderScan]) -> HeaderScan | None:
    expected_stem = Path(filename).stem
    for scan in scans:
        if scan.path.stem.lower() == expected_stem.lower() and scan.status == "ok":
            return scan
    return None


def _all_header_candidates(scans: list[HeaderScan]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for scan in scans:
        if scan.status != "ok":
            continue
        candidates.extend((scan.path.name, header) for header in scan.headers)
    return candidates


def _match_field(headers: list[str], target_field: str, aliases: object) -> str:
    alias_values = [target_field]
    if isinstance(aliases, list):
        alias_values.extend(str(value) for value in aliases)
    elif isinstance(aliases, str):
        alias_values.append(aliases)
    normalized_aliases = {_normalize(alias) for alias in alias_values}
    for header in headers:
        if _normalize(header) in normalized_aliases:
            return header
    return ""


def _suggestions(
    *,
    target_field: str,
    aliases: object,
    candidates: list[tuple[str, str]],
    limit: int = 3,
) -> list[FieldSuggestion]:
    alias_values = [target_field]
    if isinstance(aliases, list):
        alias_values.extend(str(value) for value in aliases)
    elif isinstance(aliases, str):
        alias_values.append(aliases)

    target_norms = [_normalize(alias) for alias in alias_values if _normalize(alias)]
    target_tokens = set().union(*(_tokenize(alias) for alias in alias_values)) if alias_values else set()
    scored: list[FieldSuggestion] = []
    for source_file, header in candidates:
        header_norm = _normalize(header)
        if not header_norm:
            continue
        ratio = max((SequenceMatcher(None, header_norm, norm).ratio() for norm in target_norms), default=0.0)
        header_tokens = _tokenize(header)
        token_overlap = len(target_tokens & header_tokens) / len(target_tokens | header_tokens) if target_tokens or header_tokens else 0.0
        score = max(ratio, token_overlap)
        if score >= 0.72 or token_overlap >= 0.5:
            reason = "normalized name similarity" if ratio >= token_overlap else "shared field-name tokens"
            scored.append(
                FieldSuggestion(
                    target_field=target_field,
                    candidate_column=header,
                    source_file=source_file,
                    score=round(float(score), 3),
                    reason=reason,
                ),
            )
    scored.sort(key=lambda item: (-item.score, item.source_file, item.candidate_column))
    return scored[:limit]


def _inspect_dataset(filename: str, field_mapping: object, scans: list[HeaderScan]) -> DatasetInspection:
    mapping = field_mapping if isinstance(field_mapping, dict) else {}
    scan = _canonical_scan(filename, scans)
    headers = scan.headers if scan is not None else []
    matched_fields: dict[str, str] = {}
    matched_headers: set[str] = set()
    for target_field, aliases in mapping.items():
        match = _match_field(headers, str(target_field), aliases)
        if match:
            matched_fields[str(target_field)] = match
            matched_headers.add(_normalize(match))

    dataset = _dataset_name(filename)
    required = REQUIRED_COLUMNS.get(dataset, []) if dataset is not None else []
    required_set = set(required)
    mapped_fields = {str(field) for field in mapping}
    missing_required = [field for field in required if field not in matched_fields]
    missing_optional = sorted(field for field in mapped_fields - required_set if field not in matched_fields)
    unknown = [header for header in headers if _normalize(header) not in matched_headers]
    candidates = _all_header_candidates(scans) if scan is None else [(scan.path.name, header) for header in headers]
    suggestions: list[FieldSuggestion] = []
    for field_name in [*missing_required, *missing_optional]:
        suggestions.extend(_suggestions(target_field=field_name, aliases=mapping.get(field_name, []), candidates=candidates))

    return DatasetInspection(
        dataset=filename,
        input_file=scan.path.name if scan is not None else "",
        matched_fields=matched_fields,
        missing_required_fields=missing_required,
        missing_optional_fields=missing_optional,
        unknown_fields=unknown,
        suggestions=suggestions,
    )


def _result_payload(result: MappingInspectionResult) -> dict[str, Any]:
    return {
        "input_path": str(result.input_path),
        "pack_path": str(result.pack_path),
        "profile_id": result.profile_id,
        "summary": result.summary,
        "files": [
            {"file": scan.path.name, "path": str(scan.path), "status": scan.status, "headers": scan.headers, "error": scan.error}
            for scan in result.files
        ],
        "datasets": [
            {
                "dataset": dataset.dataset,
                "input_file": dataset.input_file,
                "matched_fields": dataset.matched_fields,
                "missing_required_fields": dataset.missing_required_fields,
                "missing_optional_fields": dataset.missing_optional_fields,
                "unknown_fields": dataset.unknown_fields,
                "suggestions": [
                    {
                        "target_field": suggestion.target_field,
                        "candidate_column": suggestion.candidate_column,
                        "source_file": suggestion.source_file,
                        "score": suggestion.score,
                        "reason": suggestion.reason,
                    }
                    for suggestion in dataset.suggestions
                ],
            }
            for dataset in result.datasets
        ],
    }


def _write_json_report(result: MappingInspectionResult) -> None:
    with result.report_json_path.open("w", encoding="utf-8") as handle:
        json.dump(_result_payload(result), handle, indent=2, default=json_default)


def _write_markdown_report(result: MappingInspectionResult) -> None:
    lines = [
        "# Mapping Inspection Report",
        "",
        f"- Input folder: `{result.input_path}`",
        f"- Mapping pack: `{result.pack_path}`",
        f"- Profile: `{result.profile_id}`",
        "",
        "## Summary",
        "",
        *[f"- {key.replace('_', ' ').title()}: {value}" for key, value in result.summary.items()],
        "",
        "## Files Scanned",
        "",
    ]
    if result.files:
        for scan in result.files:
            detail = f"{len(scan.headers)} headers" if scan.status == "ok" else f"error: {scan.error}"
            lines.append(f"- `{scan.path.name}`: {scan.status} ({detail})")
    else:
        lines.append("- No CSV/XLSX files found in the input folder.")

    for dataset in result.datasets:
        lines.extend(
            [
                "",
                f"## {dataset.dataset}",
                "",
                f"- Input file: `{dataset.input_file or 'not found'}`",
                f"- Matched fields: {len(dataset.matched_fields)}",
                f"- Missing required fields: {', '.join(dataset.missing_required_fields) if dataset.missing_required_fields else 'none'}",
                f"- Missing optional fields: {', '.join(dataset.missing_optional_fields) if dataset.missing_optional_fields else 'none'}",
                f"- Unknown input fields: {', '.join(dataset.unknown_fields) if dataset.unknown_fields else 'none'}",
            ],
        )
        if dataset.matched_fields:
            lines.extend(["", "Matched field mapping:"])
            lines.extend(f"- `{target}` -> `{source}`" for target, source in sorted(dataset.matched_fields.items()))
        if dataset.suggestions:
            lines.extend(["", "Suggested mappings:"])
            lines.extend(
                f"- `{suggestion.target_field}` -> `{suggestion.candidate_column}` from `{suggestion.source_file}` "
                f"(score {suggestion.score}, {suggestion.reason})"
                for suggestion in dataset.suggestions
            )
    result.report_markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def inspect_mapping_inputs(input_path: Path | str, pack_path: Path | str, output_path: Path | str) -> MappingInspectionResult:
    """Compare local export headers against a mapping profile and write reports."""

    input_dir = Path(input_path)
    pack_dir = Path(pack_path)
    output_dir = ensure_output_dir(output_path)
    mapping = _load_mapping(pack_dir)
    field_mappings = mapping.get("field_mappings", {})
    if not isinstance(field_mappings, dict):
        field_mappings = {}
    scans = scan_input_headers(input_dir)
    result = MappingInspectionResult(
        input_path=input_dir,
        pack_path=pack_dir,
        profile_id=str(mapping.get("profile_id", pack_dir.name)),
        files=scans,
        datasets=[_inspect_dataset(str(filename), field_mapping, scans) for filename, field_mapping in sorted(field_mappings.items())],
        report_json_path=output_dir / "mapping_report.json",
        report_markdown_path=output_dir / "mapping_report.md",
    )
    _write_json_report(result)
    _write_markdown_report(result)
    return result
