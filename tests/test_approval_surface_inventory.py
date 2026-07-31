from __future__ import annotations

import ast
from pathlib import Path
from string import ascii_letters, digits

from hypothesis import given
from hypothesis import strategies as st

from reconforge.auth.rbac import same_actor

PLATFORM_ROOT = Path("reconforge/platform")
SQLITE_APPROVALS = Path("reconforge/infrastructure/sqlite_approvals.py")
SQLITE_ACCOUNTS = Path("reconforge/infrastructure/sqlite_accounts.py")
SQLITE_PAYABLES = Path("reconforge/infrastructure/sqlite_payables.py")
SQLITE_RECEIVABLES = Path("reconforge/infrastructure/sqlite_receivables.py")
SQLITE_INVENTORY_VALUATION = Path("reconforge/infrastructure/sqlite_inventory_valuation.py")
SQLITE_INVENTORY_VALUATION_REVERSAL = Path("reconforge/infrastructure/sqlite_inventory_valuation_reversal.py")
SQLITE_INVENTORY_PLANNING = Path("reconforge/infrastructure/sqlite_inventory_planning.py")

APPROVAL_SURFACES = {
    ("sqlite_accounts.py", "SQLiteAccountReconciliationRepository", "review"),
    ("sqlite_approvals.py", "SQLiteApprovalRepository", "approve"),
    ("sqlite_approvals.py", "SQLiteApprovalRepository", "review_certification"),
    ("sqlite_inventory_planning.py", "SQLiteInventoryPlanningRepositoryAdapter", "approve_count_session"),
    (
        "sqlite_inventory_valuation.py",
        "SQLiteInventoryValuationRepositoryAdapter",
        "approve_document",
    ),
    ("sqlite_inventory_valuation_reversal.py", "SQLiteInventoryValuationReversalRepositoryAdapter", "approve_reversal"),
    ("sqlite_payables.py", "SQLitePayablesRepository", "approve_purchase_order"),
    ("sqlite_payables.py", "SQLitePayablesRepository", "approve_supplier_invoice"),
    ("sqlite_receivables.py", "SQLiteReceivablesRepository", "approve_invoice"),
}

GUARD_METHODS = {
    ("sqlite_accounts.py", "SQLiteAccountReconciliationRepository", "review"),
    ("sqlite_approvals.py", "SQLiteApprovalRepository", "_decide"),
    ("sqlite_approvals.py", "SQLiteApprovalRepository", "review_certification"),
    ("sqlite_inventory_planning.py", "SQLiteInventoryPlanningRepositoryAdapter", "approve_count_session"),
    (
        "sqlite_inventory_valuation.py",
        "SQLiteInventoryValuationRepositoryAdapter",
        "approve_document",
    ),
    ("sqlite_inventory_valuation_reversal.py", "SQLiteInventoryValuationReversalRepositoryAdapter", "approve_reversal"),
    ("sqlite_payables.py", "SQLitePayablesRepository", "approve_purchase_order"),
    ("sqlite_payables.py", "SQLitePayablesRepository", "approve_supplier_invoice"),
    ("sqlite_receivables.py", "SQLiteReceivablesRepository", "approve_invoice"),
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
    tree = ast.parse(SQLITE_APPROVALS.read_text("utf-8"), filename=str(SQLITE_APPROVALS))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteApprovalRepository":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_APPROVALS.name, node.name, method.name)] = method
    tree = ast.parse(SQLITE_ACCOUNTS.read_text("utf-8"), filename=str(SQLITE_ACCOUNTS))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteAccountReconciliationRepository":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_ACCOUNTS.name, node.name, method.name)] = method
    tree = ast.parse(SQLITE_PAYABLES.read_text("utf-8"), filename=str(SQLITE_PAYABLES))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLitePayablesRepository":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_PAYABLES.name, node.name, method.name)] = method
    tree = ast.parse(SQLITE_RECEIVABLES.read_text("utf-8"), filename=str(SQLITE_RECEIVABLES))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteReceivablesRepository":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_RECEIVABLES.name, node.name, method.name)] = method
    tree = ast.parse(
        SQLITE_INVENTORY_VALUATION.read_text("utf-8"),
        filename=str(SQLITE_INVENTORY_VALUATION),
    )
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteInventoryValuationRepositoryAdapter":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_INVENTORY_VALUATION.name, node.name, method.name)] = method
    tree = ast.parse(
        SQLITE_INVENTORY_VALUATION_REVERSAL.read_text("utf-8"),
        filename=str(SQLITE_INVENTORY_VALUATION_REVERSAL),
    )
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteInventoryValuationReversalRepositoryAdapter":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_INVENTORY_VALUATION_REVERSAL.name, node.name, method.name)] = method
    tree = ast.parse(SQLITE_INVENTORY_PLANNING.read_text("utf-8"), filename=str(SQLITE_INVENTORY_PLANNING))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SQLiteInventoryPlanningRepositoryAdapter":
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(SQLITE_INVENTORY_PLANNING.name, node.name, method.name)] = method
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
