from __future__ import annotations

import ast
from pathlib import Path
from string import ascii_letters, digits

from hypothesis import given
from hypothesis import strategies as st

from reconforge.auth.rbac import same_actor

PLATFORM_ROOT = Path("reconforge/platform")

APPROVAL_SURFACES = {
    ("accounts.py", "AccountReconciliationService", "review"),
    ("approvals.py", "ApprovalService", "approve"),
    ("approvals.py", "ApprovalService", "review_certification"),
    ("inventory_planning.py", "InventoryPlanningService", "approve_count_session"),
    ("inventory_valuation.py", "InventoryValuationService", "approve_document"),
    (
        "inventory_valuation_reversal.py",
        "InventoryValuationReversalService",
        "approve_reversal",
    ),
    ("payables.py", "PayablesService", "approve_purchase_order"),
    ("payables.py", "PayablesService", "approve_supplier_invoice"),
    ("receivables.py", "ReceivablesService", "approve_invoice"),
}

GUARD_METHODS = {
    ("accounts.py", "AccountReconciliationService", "review"),
    ("approvals.py", "ApprovalService", "_decide"),
    ("approvals.py", "ApprovalService", "review_certification"),
    ("inventory_planning.py", "InventoryPlanningService", "approve_count_session"),
    ("inventory_valuation.py", "InventoryValuationService", "approve_document"),
    (
        "inventory_valuation_reversal.py",
        "InventoryValuationReversalService",
        "approve_reversal",
    ),
    ("payables.py", "PayablesService", "approve_purchase_order"),
    ("payables.py", "PayablesService", "approve_supplier_invoice"),
    ("receivables.py", "ReceivablesService", "approve_invoice"),
}


def _service_methods() -> dict[tuple[str, str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    methods: dict[tuple[str, str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path in PLATFORM_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Service"):
                continue
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[(path.name, node.name, method.name)] = method
    return methods


def test_approval_and_review_surface_inventory_is_exact_and_every_guard_is_centralized() -> None:
    methods = _service_methods()
    discovered = {key for key in methods if key[2].startswith("approve") or key[2].startswith("review")}

    assert discovered == APPROVAL_SURFACES
    for key in GUARD_METHODS:
        calls = {ast.unparse(call.func) for call in ast.walk(methods[key]) if isinstance(call, ast.Call)}
        assert "same_actor" in calls, key


@given(
    actor=st.text(
        alphabet=ascii_letters + digits + "._@+-",
        min_size=1,
        max_size=20,
    )
)
def test_same_actor_is_case_and_outer_whitespace_invariant(actor: str) -> None:
    assert same_actor(actor, f"  {actor.swapcase()}  ")
    assert not same_actor(actor, "")
    assert not same_actor("", actor)
