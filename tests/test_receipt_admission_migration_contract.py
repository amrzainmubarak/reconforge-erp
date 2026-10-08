"""The forward database repair is frozen and refuses loss of retained admission."""
import ast
from pathlib import Path


def test_receipt_admission_upgrade_is_frozen_and_preserves_populated_history():
    path = Path(__file__).parents[1] / "alembic/versions/0108_postgres_receipt_admission.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith("reconforge") for module in imports)
    assert assignments["down_revision"] == "0107_pg_job_operations"
    assert "i.item_type IN ('Stock','Consumable')" in assignments["UPGRADE_SQL"]
    assert "BEFORE INSERT OR UPDATE OR DELETE ON reconforge.currency_registry_bindings" in assignments["UPGRADE_SQL"]
    assert "currency_registry_admission_lock" in assignments["UPGRADE_SQL"]
    assert "IF EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans)" in assignments["DOWNGRADE_SQL"]
    assert "RAISE EXCEPTION" in assignments["DOWNGRADE_SQL"]
    assert "AND i.item_type='Stock'" in assignments["PREVIOUS_ADMISSION_SQL"]
