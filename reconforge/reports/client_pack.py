"""Client handoff pack generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2

from reconforge.io.writers import ensure_output_dir, json_default


@dataclass(frozen=True)
class ClientPackArtifacts:
    """Generated client handoff pack paths."""

    output_dir: Path
    included_files: list[Path]
    missing_optional_files: list[str]
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
]


def _is_hidden_or_system(path: Path) -> bool:
    return any(part.startswith(".") or part in {"__pycache__"} for part in path.parts)


def _copy_optional_file(source_root: Path, output_root: Path, relative_name: str) -> Path | None:
    source = source_root / relative_name
    if not source.exists() or not source.is_file() or _is_hidden_or_system(Path(relative_name)):
        return None
    target = output_root / relative_name
    target.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, target)
    return target


def _copy_evidence_folder(source_root: Path, output_root: Path) -> list[Path]:
    evidence_root = source_root / "evidence"
    if not evidence_root.exists() or not evidence_root.is_dir():
        return []
    copied: list[Path] = []
    for source in sorted(evidence_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if _is_hidden_or_system(relative):
            continue
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)
        copied.append(target)
    return copied


def _write_pack_text(output_dir: Path, input_path: Path, included: list[Path], missing: list[str]) -> tuple[Path, Path, Path]:
    summary_path = output_dir / "summary.md"
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
                "Evidence folders may contain generated source-record extracts intended for audit review. Treat them as sensitive unless the client or engagement owner confirms they can be shared.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path, next_steps_path, privacy_note_path


def _write_manifest(output_dir: Path, input_path: Path, included: list[Path], missing: list[str]) -> Path:
    manifest_path = output_dir / "files_manifest.json"
    payload = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source_output_folder": str(input_path),
        "local_first_note": "Generated from local ReconForge outputs; review before external sharing.",
        "included_files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(set(included))
            if path.exists() and path.is_file()
        ],
        "missing_optional_files": missing,
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    return manifest_path


def generate_client_pack(input_path: Path | str, output_path: Path | str) -> ClientPackArtifacts:
    """Create a local client handoff folder from generated ReconForge outputs."""

    source_root = Path(input_path)
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Generated output directory does not exist: {source_root}")
    output_dir = ensure_output_dir(output_path)
    included: list[Path] = []
    missing: list[str] = []
    for relative_name, _description in OPTIONAL_ARTIFACTS:
        copied = _copy_optional_file(source_root, output_dir, relative_name)
        if copied is None:
            missing.append(relative_name)
        else:
            included.append(copied)
    evidence_files = _copy_evidence_folder(source_root, output_dir)
    for path in evidence_files:
        if path not in included:
            included.append(path)

    summary_path, next_steps_path, privacy_note_path = _write_pack_text(output_dir, source_root, included, missing)
    included.extend([summary_path, next_steps_path, privacy_note_path])
    manifest_path = _write_manifest(output_dir, source_root, included, missing)
    included.append(manifest_path)
    return ClientPackArtifacts(
        output_dir=output_dir,
        included_files=sorted(set(included)),
        missing_optional_files=missing,
        manifest_path=manifest_path,
        summary_path=summary_path,
        next_steps_path=next_steps_path,
        privacy_note_path=privacy_note_path,
    )
