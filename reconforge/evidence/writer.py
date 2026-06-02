"""Writers for audit evidence folders."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from reconforge.evidence.models import EvidenceArtifact, EvidenceCase
from reconforge.evidence.templates import action_markdown, review_form_markdown, summary_markdown
from reconforge.io.writers import json_default


def write_evidence_case(case: EvidenceCase, output_dir: Path | str) -> EvidenceArtifact:
    """Write a complete evidence folder for one case."""

    folder = Path(output_dir) / case.exception_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.md").write_text(summary_markdown(case), encoding="utf-8")
    (folder / "recommended_action.md").write_text(action_markdown(case), encoding="utf-8")
    (folder / "review_form.md").write_text(review_form_markdown(case), encoding="utf-8")
    pd.DataFrame([case.source_record]).to_csv(folder / "source_records.csv", index=False)
    pd.DataFrame(case.match_candidates).to_csv(folder / "match_candidates.csv", index=False)
    with (folder / "triggered_rules.yml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump({"rules": case.triggered_rules}, handle, sort_keys=False)
    with (folder / "audit_trail.json").open("w", encoding="utf-8") as handle:
        json.dump(case.model_dump(mode="json"), handle, indent=2, default=json_default)
    return EvidenceArtifact(exception_id=case.exception_id, folder=folder)
