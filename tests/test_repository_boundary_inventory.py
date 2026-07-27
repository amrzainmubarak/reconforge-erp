from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = ROOT / "reconforge" / "platform"
APPLICATION_ROOT = ROOT / "reconforge" / "application"
INVENTORY_PATH = ROOT / "docs" / "execution" / "REPOSITORY_BOUNDARY_INVENTORY.yaml"


def _inventory() -> dict[str, Any]:
    loaded = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _service_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Service")
    }


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_platform_service_inventory_is_exact() -> None:
    inventory = _inventory()
    expected = {
        (entry["file"], entry["service"])
        for entry in inventory["platform_services"]
    }
    discovered = {
        (path.name, service)
        for path in PLATFORM_ROOT.glob("*.py")
        for service in _service_classes(path)
    }
    assert expected == discovered
    assert len(expected) == inventory["summary"]["platform_total"]


def test_inventory_status_matches_source_boundaries() -> None:
    inventory = _inventory()
    allowed = set(inventory["allowed_statuses"])
    counts = {status: 0 for status in allowed}
    for entry in inventory["platform_services"]:
        status = entry["status"]
        assert status in allowed
        counts[status] += 1
        imports = _imports(PLATFORM_ROOT / entry["file"])
        if status in {"direct_sqlite", "partial_repository"}:
            assert "sqlite3" in imports, entry
        if status == "partial_repository":
            assert any(name.endswith("_repository") for name in imports), entry
        if status == "backend_neutral":
            assert "sqlite3" not in imports, entry
            assert not any(name.startswith("reconforge.infrastructure") for name in imports), entry

    summary = inventory["summary"]
    assert counts["direct_sqlite"] == summary["direct_sqlite"]
    assert counts["partial_repository"] == summary["partial_repository"]


def test_backend_neutral_application_inventory_is_exact_and_connection_free() -> None:
    inventory = _inventory()
    expected = {
        (entry["file"], entry["service"])
        for entry in inventory["application_services"]
    }
    discovered = {
        (path.name, service)
        for path in APPLICATION_ROOT.glob("*.py")
        for service in _service_classes(path)
    }
    assert expected == discovered
    for entry in inventory["application_services"]:
        assert entry["status"] == "backend_neutral"
        imports = _imports(APPLICATION_ROOT / entry["file"])
        assert "sqlite3" not in imports
        assert not any(name.startswith("reconforge.infrastructure") for name in imports)

    assert len(expected) == inventory["summary"]["backend_neutral_application"]
