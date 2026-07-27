from __future__ import annotations

from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_backup_restore_matrix_is_closed_unique_and_evidence_bounded() -> None:
    matrix = yaml.safe_load((ROOT / "docs/operations/backup-restore-matrix.v1.yaml").read_text(encoding="utf-8"))
    schema = yaml.safe_load((ROOT / "docs/schemas/backup_restore_matrix.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(matrix)

    cells = matrix["cells"]
    assert len({cell["id"] for cell in cells}) == len(cells)
    assert matrix["overall_status"] == "partial"
    assert {cell["status"] for cell in cells} == {"verified", "planned"}
    assert any(cell["backend"] == "sqlite" and cell["status"] == "verified" for cell in cells)
    assert any(cell["backend"] == "postgresql" and cell["status"] == "verified" for cell in cells)
    assert all(cell["limitations"] for cell in cells)
