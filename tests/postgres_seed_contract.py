"""Exact additive permissions seeded for new tenants at the current schema head.

This is an independent expected contract, not a query of the implementation.
Adding a permission migration requires reviewing this catalog intentionally.
Role grants remain separate: catalog presence never implies authorization.
"""

CURRENT_TENANT_SEEDED_PERMISSIONS = frozenset({
    "budget_control.read", "budget_control.manage", "budget_control.approve",
    "exceptions.read", "exceptions.manage", "payables.settle", "payables.reverse",
    "jobs.manage",
    "sales.read", "sales.manage", "sales.approve",
})
