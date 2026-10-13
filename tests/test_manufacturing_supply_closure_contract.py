"""Reviewed native delegation is the only change to complete source closure."""
from reconforge.infrastructure import postgres_manufacturing_supply_closure as closure
from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import UPGRADE_SQL as CORE_UPGRADE_SQL


def test_original_evidence_and_every_other_complete_close_statement_remain_exact() -> None:
    restored = closure.CLOSE_SQL.replace(closure._PER_PLAN_PROCUREMENT, "")
    stock_loop = " FOR c IN SELECT * FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND requirement_id=r.id LOOP"
    restored = restored.replace("\n\n" + stock_loop, "\n" + closure._PER_REQUIREMENT_PROCUREMENT + "\n" + stock_loop, 1)
    restored = restored.replace(closure._CAPACITY_AND_FIFO.split("\n", 1)[0], closure._CAPACITY_AND_FIFO, 1)
    assert restored == closure.ORIGINAL_CLOSE_SQL
    assert "FOR v IN 1..p.row_version LOOP PERFORM reconforge.msp_evidence(t,i,v);END LOOP;" in closure.CLOSE_SQL
    assert "msp_evidence_history" not in closure.UPGRADE_SQL
    assert closure.PURCHASE_SQL.replace(
        "PERFORM reconforge.pp_verify_order(t,i);",
        "PERFORM reconforge.pp_verify_order(t,i);PERFORM reconforge.pc_close(t,i);",
        1,
    ) == closure.ORIGINAL_PURCHASE_SQL


def test_capacity_delegate_retains_exact_fifo_and_all_owned_source_checks() -> None:
    capacity = CORE_UPGRADE_SQL.split("CREATE FUNCTION reconforge.inventory_quantity_check_capacity(", 1)[1].split("END $quantity$;", 1)[0]
    assert capacity.rstrip().endswith("PERFORM reconforge.inventory_quantity_free_fifo(t,w,e,i);")
    assert "Original posted physical quantities cannot be reinterpreted" in capacity
    assert "Posted stock must cover native reservations and exclusive planning quantities" in capacity
    assert closure.CLOSE_SQL.count("PERFORM reconforge.inventory_quantity_check_capacity(") == 1
    assert "PERFORM reconforge.inventory_quantity_free_fifo(" not in closure.CLOSE_SQL


def test_each_distinct_requisition_is_closed_after_every_requirement_is_validated() -> None:
    assert closure.CLOSE_SQL.count("PERFORM reconforge.msp_procurement_close(") == 1
    assert "WHERE tenant_id=t AND plan_id=i LOOP" in closure.CLOSE_SQL
    assert closure.CLOSE_SQL.index(closure._PER_PLAN_PROCUREMENT) > closure.CLOSE_SQL.index("PERFORM reconforge.inventory_quantity_check_capacity(")
    assert "SELECT DISTINCT requisition_id" in closure._PER_PLAN_PROCUREMENT


def test_upgrade_and_populated_inverse_only_replace_the_original_two_invoker_functions() -> None:
    for statements in (closure.UPGRADE_SQL, closure.DOWNGRADE_SQL):
        assert statements.count("CREATE OR REPLACE FUNCTION") == 2
        assert "SECURITY DEFINER" not in statements
        assert "set_config(" not in statements and "CREATE TEMP" not in statements
        assert "GRANT " not in statements and "DISABLE TRIGGER" not in statements
    assert closure.DOWNGRADE_SQL == closure.ORIGINAL_CLOSE_SQL + "\n" + closure.ORIGINAL_PURCHASE_SQL
    assert "native budget commitment delegate" in closure.UPGRADE_SQL
    assert "native exact FIFO delegate" in closure.UPGRADE_SQL
