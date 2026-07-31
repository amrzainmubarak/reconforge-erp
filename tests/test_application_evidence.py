from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock

from reconforge.application.evidence import EvidenceRegistryApplicationService, EvidenceVerification


def test_application_delegates_complete_evidence_contract(tmp_path: Path) -> None:
    source = tmp_path / "evidence.txt"
    repository = Mock()
    repository.register.return_value = {"id": "E-1"}
    repository.requirement.return_value = {"id": "R-1"}
    repository.link.return_value = {"id": "L-1"}
    verification = EvidenceVerification("E-1", True, "a" * 64, "a" * 64)
    repository.verify.return_value = verification
    repository.coverage.return_value = {"coverage_pct": 100.0}
    repository.list_evidence.return_value = [{"id": "E-1"}]
    repository.get.return_value = {"id": "E-1"}
    repository.drill_down.return_value = {"evidence_id": "E-1"}
    service = EvidenceRegistryApplicationService(repository)

    assert service.register(
        source, evidence_code="EV-1", workspace="finance", provenance_type="export",
        redaction_status="reviewed", evidence_status="Available", object_type="control",
        object_id="C-1", link_type="support", actor_label="auditor",
        storage_tenant_id="tenant-a", storage_object_name="evidence/one",
        content_type="text/plain",
    ) == {"id": "E-1"}
    assert service.requirement(
        object_type="control", object_id="C-1", requirement_code="REQ-1",
        description="Support", workspace="finance", actor_label="auditor",
    ) == {"id": "R-1"}
    assert service.link(
        "E-1", object_type="control", object_id="C-1", actor_label="auditor"
    ) == {"id": "L-1"}
    assert service.verify("E-1", actor_label="auditor") == verification
    assert service.coverage(workspace="finance", actor_label="auditor") == {"coverage_pct": 100.0}
    assert service.list_evidence(status="Available") == [{"id": "E-1"}]
    assert service.get("E-1") == {"id": "E-1"}
    assert service.drill_down(
        "E-1", direction="up", max_depth=3, include_sensitive=True,
        limit=50, offset=10, actor_label="auditor",
    ) == {"evidence_id": "E-1"}
    repository.drill_down.assert_called_once_with(
        "E-1", direction="up", max_depth=3, include_sensitive=True,
        limit=50, offset=10, actor_label="auditor",
    )


def test_application_module_has_no_database_or_infrastructure_imports() -> None:
    path = Path(__file__).parents[1] / "reconforge" / "application" / "evidence.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {str(node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "sqlite3" not in imports
    assert all(not name.startswith("reconforge.infrastructure") for name in imports)
