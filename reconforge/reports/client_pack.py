"""Client handoff pack generation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2, rmtree
from typing import Any

from reconforge import __version__
from reconforge.io.writers import json_default


@dataclass(frozen=True)
class ClientPackOptions:
    """Sharing controls for generated client handoff packs."""

    redact_names: bool = False
    redact_amounts: bool = False
    exclude_raw_records: bool = False
    summary_only: bool = False
    exclude_evidence: bool = False
    include_manifest_checksums: bool = False

    @property
    def redaction_requested(self) -> bool:
        return self.redact_names or self.redact_amounts


@dataclass(frozen=True)
class ClientPackArtifacts:
    """Generated client handoff pack paths."""

    output_dir: Path
    included_files: list[Path]
    missing_optional_files: list[str]
    excluded_files: list[str]
    manifest_path: Path
    summary_path: Path
    next_steps_path: Path
    privacy_note_path: Path


OPTIONAL_ARTIFACTS = [
    ("executive_report.html", "Executive HTML report"),
    ("management_pack.xlsx", "Excel management pack"),
    ("review_register.xlsx", "Exception review register"),
    ("dashboard.html", "Static dashboard"),
    ("summary.md", "Markdown summary"),
    ("evidence/index.html", "Evidence binder index"),
    ("evidence/evidence_register.xlsx", "Evidence register"),
    ("evidence/evidence_index.json", "Evidence JSON index"),
    ("evidence/evidence_manifest.json", "Evidence integrity manifest"),
]
TEXT_SUFFIXES = {".csv", ".html", ".htm", ".json", ".md", ".txt", ".yml", ".yaml"}
RAW_RECORD_NAMES = {"source_records.csv", "match_candidates.csv", "audit_trail.json", "triggered_rules.yml"}
NAME_KEY_HINTS = {
    "customer",
    "supplier",
    "employee",
    "engineer",
    "reviewer",
    "created_by",
    "received_by",
    "equipment",
    "serial",
    "technician",
    "owner",
}
AMOUNT_KEY_HINTS = {
    "amount",
    "cost",
    "price",
    "debit",
    "credit",
    "value",
    "total",
    "balance",
    "standard_cost",
    "unit_cost",
}
MONEY_PATTERN = re.compile(
    r"(?<![\w.-])(?:(?:USD|EUR|GBP|AED|SAR|EGP)\s*[-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?(?:\d{1,3}(?:,\d{3})+|\d+\.\d{2}))(?![\w.-])",
)
LABELED_NAME_PATTERN = re.compile(
    r"\b(Customer|Supplier|Employee|Engineer|Reviewer|Equipment|Serial|Created by|Received by)\s*[:=]\s*([^<\n,;]+?)(?=\s+(?:USD|EUR|GBP|AED|SAR|EGP)\b|\s+[-+]?\d|[<\n,;]|$)",
    re.IGNORECASE,
)


def _is_hidden_or_system(path: Path) -> bool:
    return any(part.startswith(".") or part in {"__pycache__"} for part in path.parts)


def _prepare_output_dir(source_root: Path, output_path: Path | str) -> Path:
    output_dir = Path(output_path)
    if output_dir.resolve() == source_root.resolve():
        raise ValueError("Client pack output directory must be different from the source output folder.")
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in output_dir.iterdir():
        if _is_hidden_or_system(Path(child.name)):
            continue
        if child.is_dir():
            rmtree(child)
        else:
            child.unlink()
    return output_dir


def _key_matches(key: str, hints: set[str]) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(hint in normalized for hint in hints)


def _bucket_amount(value: object) -> str:
    try:
        amount = abs(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return "[AMOUNT_REDACTED]"
    if amount == 0:
        return "0"
    if amount < 100:
        return "0-99"
    if amount < 1000:
        return "100-999"
    if amount < 10000:
        return "1,000-9,999"
    if amount < 100000:
        return "10,000-99,999"
    return "100,000+"


def _redact_value(key: str, value: Any, options: ClientPackOptions) -> Any:
    if options.redact_names and _key_matches(key, NAME_KEY_HINTS):
        return "[REDACTED]"
    if options.redact_amounts and _key_matches(key, AMOUNT_KEY_HINTS):
        return _bucket_amount(value)
    return value


def _redact_json_object(value: Any, options: ClientPackOptions, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: _redact_json_object(_redact_value(str(item_key), item_value, options), options, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_json_object(item, options, key) for item in value]
    return _redact_value(key, value, options)


def _redact_text(text: str, options: ClientPackOptions) -> str:
    output = text
    if options.redact_names:
        output = LABELED_NAME_PATTERN.sub(lambda match: f"{match.group(1)}: [REDACTED]", output)
    if options.redact_amounts:
        output = MONEY_PATTERN.sub("[AMOUNT_REDACTED]", output)
    return output


def _redact_csv_file(source: Path, target: Path, options: ClientPackOptions) -> None:
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            target.write_text(_redact_text(source.read_text(encoding="utf-8", errors="replace"), options), encoding="utf-8")
            return
        rows = []
        for row in reader:
            rows.append({key: _redact_value(key, value, options) for key, value in row.items()})
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _redact_json_file(source: Path, target: Path, options: ClientPackOptions) -> None:
    text = source.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        target.write_text(_redact_text(text, options), encoding="utf-8")
        return
    with target.open("w", encoding="utf-8") as handle:
        json.dump(_redact_json_object(payload, options), handle, indent=2, default=json_default)


def _copy_with_controls(source: Path, target: Path, options: ClientPackOptions) -> Path | None:
    if options.redaction_requested and source.suffix.lower() not in TEXT_SUFFIXES:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if not options.redaction_requested:
        copy2(source, target)
        return target
    suffix = source.suffix.lower()
    if suffix == ".csv":
        _redact_csv_file(source, target, options)
    elif suffix == ".json":
        _redact_json_file(source, target, options)
    else:
        target.write_text(_redact_text(source.read_text(encoding="utf-8", errors="replace"), options), encoding="utf-8")
    return target


def _should_exclude(relative: Path, options: ClientPackOptions) -> str | None:
    if options.summary_only and relative.as_posix() != "summary.md":
        return "excluded by --summary-only"
    if options.exclude_evidence and relative.parts and relative.parts[0] == "evidence":
        return "excluded by --exclude-evidence"
    if options.exclude_raw_records and relative.name in RAW_RECORD_NAMES:
        return "excluded by --exclude-raw-records"
    return None


def _copy_optional_file(
    source_root: Path,
    output_root: Path,
    relative_name: str,
    options: ClientPackOptions,
    target_relative_name: str | None = None,
) -> tuple[Path | None, str | None]:
    relative = Path(relative_name)
    excluded_reason = _should_exclude(relative, options)
    if excluded_reason is not None:
        return None, f"{relative.as_posix()} ({excluded_reason})"
    source = source_root / relative_name
    if not source.exists() or not source.is_file() or _is_hidden_or_system(Path(relative_name)):
        return None, None
    target = output_root / (target_relative_name or relative_name)
    copied = _copy_with_controls(source, target, options)
    if copied is None:
        return None, f"{relative.as_posix()} (excluded because redaction is not supported for this file type)"
    return copied, None


def _copy_evidence_folder(source_root: Path, output_root: Path, options: ClientPackOptions) -> tuple[list[Path], list[str]]:
    if options.summary_only or options.exclude_evidence:
        return [], ["evidence/ (excluded by --summary-only)" if options.summary_only else "evidence/ (excluded by --exclude-evidence)"]
    evidence_root = source_root / "evidence"
    if not evidence_root.exists() or not evidence_root.is_dir():
        return [], []
    copied: list[Path] = []
    excluded: list[str] = []
    for source in sorted(evidence_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if _is_hidden_or_system(relative):
            continue
        excluded_reason = _should_exclude(relative, options)
        if excluded_reason is not None:
            excluded.append(f"{relative.as_posix()} ({excluded_reason})")
            continue
        target = output_root / relative
        copied_path = _copy_with_controls(source, target, options)
        if copied_path is None:
            excluded.append(f"{relative.as_posix()} (excluded because redaction is not supported for this file type)")
            continue
        copied.append(copied_path)
    return copied, excluded


def _write_pack_text(output_dir: Path, input_path: Path, included: list[Path], missing: list[str], excluded: list[str], options: ClientPackOptions) -> tuple[Path, Path, Path]:
    summary_path = output_dir / "handoff_summary.md"
    summary_path.write_text(
        "\n".join(
            [
                "# ReconForge Client Handoff Summary",
                "",
                f"Source output folder: `{input_path}`",
                "",
                "Included artifacts:",
                *[f"- `{path.relative_to(output_dir).as_posix()}`" for path in included],
                "",
                "Missing optional artifacts:",
                *([f"- `{name}`" for name in missing] if missing else ["- none"]),
                "",
                "Excluded artifacts:",
                *([f"- `{name}`" for name in excluded] if excluded else ["- none"]),
                "",
                "Sharing controls:",
                f"- redact_names: `{options.redact_names}`",
                f"- redact_amounts: `{options.redact_amounts}`",
                f"- exclude_raw_records: `{options.exclude_raw_records}`",
                f"- summary_only: `{options.summary_only}`",
                f"- exclude_evidence: `{options.exclude_evidence}`",
                f"- include_manifest_checksums: `{options.include_manifest_checksums}`",
                "",
                "Use this pack to review generated reports, exception review status, evidence status, and next actions with finance, audit, ERP, and operations stakeholders.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    next_steps_path = output_dir / "next_steps.md"
    next_steps_path.write_text(
        "\n".join(
            [
                "# Recommended Next Steps",
                "",
                "1. Review high and critical exceptions first.",
                "2. Assign each exception to a reviewer and local review status.",
                "3. Document accepted risks with a reason and owner.",
                "4. Escalate unresolved posting, WIP, or evidence gaps before close or audit sign-off.",
                "5. Rerun ReconForge after source corrections or updated ERP exports.",
                "6. Regenerate this pack after review-state or source-data changes.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    privacy_note_path = output_dir / "data_privacy_note.md"
    privacy_note_path.write_text(
        "\n".join(
            [
                "# Data Privacy Note",
                "",
                "This handoff pack was generated locally from ReconForge outputs. Core ReconForge workflows do not require cloud upload, SaaS authentication, or an external database.",
                "",
                "Before sharing this folder outside the company or engagement team, review every included file for ERP exports, source records, customer names, supplier names, employee names, equipment identifiers, and monetary values.",
                "",
                "If redaction options were used, they were applied only to files copied into this client pack. The original ReconForge output folder was not modified. Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.",
                "",
                "Evidence folders may contain generated source-record extracts intended for audit review. Treat them as sensitive unless the client or engagement owner confirms they can be shared.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path, next_steps_path, privacy_note_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(output_dir: Path, input_path: Path, included: list[Path], missing: list[str], excluded: list[str], options: ClientPackOptions) -> Path:
    manifest_path = output_dir / "files_manifest.json"
    payload = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tool_version": __version__,
        "source_output_folder": str(input_path),
        "local_first_note": "Generated from local ReconForge outputs; review before external sharing.",
        "privacy_note": "Client packs may contain sensitive generated report content. Review before sharing outside the authorized team.",
        "redaction_settings": {
            "redact_names": options.redact_names,
            "redact_amounts": options.redact_amounts,
            "exclude_raw_records": options.exclude_raw_records,
            "summary_only": options.summary_only,
            "exclude_evidence": options.exclude_evidence,
            "include_manifest_checksums": options.include_manifest_checksums,
        },
        "included_files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                **({"sha256": _sha256(path)} if options.include_manifest_checksums else {}),
            }
            for path in sorted(set(included))
            if path.exists() and path.is_file()
        ],
        "missing_optional_files": missing,
        "excluded_files": excluded,
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    return manifest_path


def generate_client_pack(
    input_path: Path | str,
    output_path: Path | str,
    *,
    redact_names: bool = False,
    redact_amounts: bool = False,
    exclude_raw_records: bool = False,
    summary_only: bool = False,
    exclude_evidence: bool = False,
    include_manifest_checksums: bool = False,
) -> ClientPackArtifacts:
    """Create a local client handoff folder from generated ReconForge outputs."""

    source_root = Path(input_path)
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Generated output directory does not exist: {source_root}")
    options = ClientPackOptions(
        redact_names=redact_names,
        redact_amounts=redact_amounts,
        exclude_raw_records=exclude_raw_records,
        summary_only=summary_only,
        exclude_evidence=exclude_evidence,
        include_manifest_checksums=include_manifest_checksums,
    )
    output_dir = _prepare_output_dir(source_root, output_path)
    included: list[Path] = []
    missing: list[str] = []
    excluded: list[str] = []
    for relative_name, _description in OPTIONAL_ARTIFACTS:
        target_relative_name = "source_summary.md" if relative_name == "summary.md" else None
        copied, excluded_reason = _copy_optional_file(source_root, output_dir, relative_name, options, target_relative_name)
        if copied is None:
            if excluded_reason is None:
                missing.append(relative_name)
            else:
                excluded.append(excluded_reason)
        else:
            included.append(copied)
    evidence_files, evidence_excluded = _copy_evidence_folder(source_root, output_dir, options)
    for path in evidence_files:
        if path not in included:
            included.append(path)
    excluded.extend(evidence_excluded)

    summary_path, next_steps_path, privacy_note_path = _write_pack_text(output_dir, source_root, included, missing, excluded, options)
    included.extend([summary_path, next_steps_path, privacy_note_path])
    manifest_path = _write_manifest(output_dir, source_root, included, missing, excluded, options)
    included.append(manifest_path)
    return ClientPackArtifacts(
        output_dir=output_dir,
        included_files=sorted(set(included)),
        missing_optional_files=missing,
        excluded_files=excluded,
        manifest_path=manifest_path,
        summary_path=summary_path,
        next_steps_path=next_steps_path,
        privacy_note_path=privacy_note_path,
    )
