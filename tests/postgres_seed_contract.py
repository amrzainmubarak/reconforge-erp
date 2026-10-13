"""Exact additive permissions seeded for new tenants at the current schema head.

This is an independent expected contract, not a query of the implementation.
Adding a permission migration requires reviewing this catalog intentionally.
Role grants remain separate: catalog presence never implies authorization.
"""

CURRENT_TENANT_SEEDED_PERMISSIONS = frozenset({
    "manufacturing_execution.read", "manufacturing_execution.manage",
    "manufacturing_execution.approve", "manufacturing_execution.post",
    "intercompany_operations.read", "intercompany_operations.prepare",
    "intercompany_operations.review", "intercompany_operations.post",
    "procurement_sourcing.read", "procurement_sourcing.manage",
    "procurement_sourcing.approve", "procurement_sourcing.award",
    "manufacturing_execution_v2.read", "manufacturing_execution_v2.manage",
    "manufacturing_execution_v2.approve", "manufacturing_execution_v2.post",
    "accrual_deferral.read", "accrual_deferral.prepare", "accrual_deferral.review", "accrual_deferral.post",
    "manufacturing_supply_plan.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.post",
    "project_time_billing.read", "project_time_billing.manage", "project_time_billing.approve_price", "project_time_billing.prepare",
    "project_time_billing.collect", "project_time_billing.review", "project_time_billing.post",
    "intercompany_fx.read", "intercompany_fx.prepare", "intercompany_fx.review", "intercompany_fx.post",
    "people_project_payroll.read", "people_project_payroll.read_sensitive", "people_project_payroll.personnel",
    "people_project_payroll.manage", "people_project_payroll.approve_time", "people_project_payroll.prepare",
    "people_project_payroll.review", "people_project_payroll.post", "people_project_payroll.pay",
    "budget_control.read", "budget_control.manage", "budget_control.approve",
    "exceptions.read", "exceptions.manage", "payables.settle", "payables.reverse",
    "jobs.manage",
    "sales.read", "sales.manage", "sales.approve",
})
