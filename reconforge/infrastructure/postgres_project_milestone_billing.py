"""PostgreSQL tenant/workspace-scoped persistence for Project WBS, Milestone Billing, and Rate Cards with FORCE RLS."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.domain.project_milestone_billing import (
    MilestoneBillingInvoice,
    ProjectBillingError,
    ProjectFinancialPosture,
    ProjectMilestone,
    ProjectWBSTask,
    ResourceRateCard,
    calculate_financial_posture,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import PlatformError

POSTGRES_PROJECT_BILLING_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.project_wbs_tasks (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_task_id TEXT,
    planned_hours INTEGER NOT NULL DEFAULT 0,
    budget_cost_minor BIGINT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, task_id)
);
ALTER TABLE reconforge.project_wbs_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_wbs_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_wbs_tasks;
CREATE POLICY tenant_scope ON reconforge.project_wbs_tasks
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_resource_rate_cards (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rate_card_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hourly_cost_rate_minor BIGINT NOT NULL,
    hourly_bill_rate_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, project_id, resource_role)
);
ALTER TABLE reconforge.project_resource_rate_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_resource_rate_cards FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_resource_rate_cards;
CREATE POLICY tenant_scope ON reconforge.project_resource_rate_cards
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_milestones (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    contract_line_id TEXT NOT NULL,
    title TEXT NOT NULL,
    milestone_amount_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_by TEXT,
    verified_at TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, milestone_id)
);
ALTER TABLE reconforge.project_milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestones FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestones;
CREATE POLICY tenant_scope ON reconforge.project_milestones
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_milestone_invoices (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    billed_amount_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    gl_debit_account TEXT NOT NULL,
    gl_credit_account TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, invoice_id)
);
ALTER TABLE reconforge.project_milestone_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_milestone_invoices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_milestone_invoices;
CREATE POLICY tenant_scope ON reconforge.project_milestone_invoices
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.project_time_logs (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    log_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hours_worked INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    actual_cost_minor BIGINT NOT NULL,
    billable_amount_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, log_id)
);
ALTER TABLE reconforge.project_time_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.project_time_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.project_time_logs;
CREATE POLICY tenant_scope ON reconforge.project_time_logs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresProjectMilestoneBillingRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for project WBS, rate cards, and milestone billing."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        ensure_repository_tenant_scope(self.connection, self.tenant_id)

    def save_task(self, task: ProjectWBSTask, *, actor_label: str = "system") -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.project_wbs_tasks (
                        tenant_id, workspace_id, task_id, project_id, task_code, name,
                        parent_task_id, planned_hours, budget_cost_minor, currency, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, task_id) DO UPDATE SET
                        name = excluded.name,
                        planned_hours = excluded.planned_hours,
                        budget_cost_minor = excluded.budget_cost_minor,
                        status = excluded.status
                    """,
                    (
                        self.tenant_id,
                        task.workspace_id,
                        task.task_id,
                        task.project_id,
                        task.task_code,
                        task.name,
                        task.parent_task_id,
                        task.planned_hours,
                        task.budget_cost_minor,
                        task.currency,
                        task.status,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_wbs_task",
                    object_id=task.task_id,
                    action="task_saved",
                    after_hash=hashlib.sha256(f"{task.task_id}:{task.budget_cost_minor}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": task.workspace_id,
                        "project_id": task.project_id,
                        "task_code": task.task_code,
                        "status": task.status,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL save task failed: {exc}") from exc

    def list_tasks(self, workspace_id: str, project_id: str) -> list[ProjectWBSTask]:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workspace_id, task_id, project_id, task_code, name,
                           parent_task_id, planned_hours, budget_cost_minor, currency, status
                    FROM reconforge.project_wbs_tasks
                    WHERE tenant_id = %s AND workspace_id = %s AND project_id = %s
                    ORDER BY task_code ASC
                    """,
                    (self.tenant_id, workspace_id, project_id),
                )
                return [
                    ProjectWBSTask(
                        workspace_id=r[0],
                        task_id=r[1],
                        project_id=r[2],
                        task_code=r[3],
                        name=r[4],
                        parent_task_id=r[5],
                        planned_hours=r[6],
                        budget_cost_minor=int(r[7]),
                        currency=r[8],
                        status=r[9],
                    )
                    for r in cur.fetchall()
                ]
        except Exception as exc:
            raise PlatformError(f"PostgreSQL list tasks failed: {exc}") from exc

    def save_rate_card(self, card: ResourceRateCard, *, actor_label: str = "system") -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.project_resource_rate_cards (
                        tenant_id, workspace_id, rate_card_id, project_id, resource_role,
                        hourly_cost_rate_minor, hourly_bill_rate_minor, currency
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, project_id, resource_role) DO UPDATE SET
                        hourly_cost_rate_minor = excluded.hourly_cost_rate_minor,
                        hourly_bill_rate_minor = excluded.hourly_bill_rate_minor,
                        currency = excluded.currency
                    """,
                    (
                        self.tenant_id,
                        card.workspace_id,
                        card.rate_card_id,
                        card.project_id,
                        card.resource_role,
                        card.hourly_cost_rate_minor,
                        card.hourly_bill_rate_minor,
                        card.currency,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_rate_card",
                    object_id=card.rate_card_id,
                    action="rate_card_saved",
                    after_hash=hashlib.sha256(f"{card.rate_card_id}:{card.hourly_bill_rate_minor}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": card.workspace_id,
                        "project_id": card.project_id,
                        "role": card.resource_role,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL save rate card failed: {exc}") from exc

    def get_rate_card(self, workspace_id: str, project_id: str, role: str) -> ResourceRateCard | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workspace_id, rate_card_id, project_id, resource_role,
                           hourly_cost_rate_minor, hourly_bill_rate_minor, currency
                    FROM reconforge.project_resource_rate_cards
                    WHERE tenant_id = %s AND workspace_id = %s AND project_id = %s AND resource_role = %s
                    """,
                    (self.tenant_id, workspace_id, project_id, role),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return ResourceRateCard(
                    workspace_id=row[0],
                    rate_card_id=row[1],
                    project_id=row[2],
                    resource_role=row[3],
                    hourly_cost_rate_minor=int(row[4]),
                    hourly_bill_rate_minor=int(row[5]),
                    currency=row[6],
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get rate card failed: {exc}") from exc

    def save_milestone(self, m: ProjectMilestone, *, actor_label: str = "system", origin: Mapping[str, str] | None = None) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self._origin("milestone", m.workspace_id, m.milestone_id, origin, before=True)
                self._save_milestone_in_tx(m)
                self._origin("milestone", m.workspace_id, m.milestone_id, origin)
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_milestone",
                    object_id=m.milestone_id,
                    action="milestone_saved",
                    after_hash=hashlib.sha256(f"{m.milestone_id}:{m.status}:{m.milestone_amount_minor}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": m.workspace_id,
                        "project_id": m.project_id,
                        "status": m.status,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL save milestone failed: {exc}") from exc

    def _save_milestone_in_tx(self, m: ProjectMilestone) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.project_milestones (
                tenant_id, workspace_id, milestone_id, project_id, contract_line_id,
                title, milestone_amount_minor, currency, due_date, status,
                verified_by, verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, workspace_id, milestone_id) DO UPDATE SET
                title = excluded.title,
                milestone_amount_minor = excluded.milestone_amount_minor,
                due_date = excluded.due_date,
                status = excluded.status,
                verified_by = excluded.verified_by,
                verified_at = excluded.verified_at
            """,
            (
                self.tenant_id,
                m.workspace_id,
                m.milestone_id,
                m.project_id,
                m.contract_line_id,
                m.title,
                m.milestone_amount_minor,
                m.currency,
                m.due_date,
                m.status,
                m.verified_by,
                m.verified_at,
            ),
        )

    def get_milestone(self, workspace_id: str, milestone_id: str) -> ProjectMilestone | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workspace_id, milestone_id, project_id, contract_line_id,
                           title, milestone_amount_minor, currency, due_date, status,
                           verified_by, verified_at
                    FROM reconforge.project_milestones
                    WHERE tenant_id = %s AND workspace_id = %s AND milestone_id = %s
                    """,
                    (self.tenant_id, workspace_id, milestone_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return ProjectMilestone(
                    workspace_id=row[0],
                    milestone_id=row[1],
                    project_id=row[2],
                    contract_line_id=row[3],
                    title=row[4],
                    milestone_amount_minor=int(row[5]),
                    currency=row[6],
                    due_date=str(row[7]),
                    status=row[8],
                    verified_by=row[9],
                    verified_at=str(row[10]) if row[10] else None,
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get milestone failed: {exc}") from exc

    def save_milestone_invoice(
        self,
        milestone: ProjectMilestone,
        invoice: MilestoneBillingInvoice,
        *,
        finance_entry_id: str | None = None,
        actor_label: str = "system",
        origin: Mapping[str, str] | None = None,
    ) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self._origin("milestone", milestone.workspace_id, milestone.milestone_id, origin, before=True)
                self._origin("invoice", invoice.workspace_id, invoice.invoice_id, origin, before=True)
                self._save_milestone_in_tx(milestone)
                self.connection.execute(
                    """
                    INSERT INTO reconforge.project_milestone_invoices (
                        tenant_id, workspace_id, invoice_id, project_id, milestone_id,
                        customer_code, billed_amount_minor, currency, issued_at,
                        gl_debit_account, gl_credit_account, finance_entry_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, invoice_id) DO UPDATE
                    SET finance_entry_id = COALESCE(EXCLUDED.finance_entry_id, project_milestone_invoices.finance_entry_id)
                    """,
                    (
                        self.tenant_id,
                        invoice.workspace_id,
                        invoice.invoice_id,
                        invoice.project_id,
                        invoice.milestone_id,
                        invoice.customer_code,
                        invoice.billed_amount_minor,
                        invoice.currency,
                        invoice.issued_at,
                        invoice.gl_debit_account,
                        invoice.gl_credit_account,
                        finance_entry_id,
                    ),
                )
                self._origin("milestone", milestone.workspace_id, milestone.milestone_id, origin)
                self._origin("invoice", invoice.workspace_id, invoice.invoice_id, origin)
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_milestone_invoice",
                    object_id=invoice.invoice_id,
                    action="milestone_invoiced",
                    after_hash=hashlib.sha256(f"{invoice.invoice_id}:{invoice.billed_amount_minor}:{finance_entry_id}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": invoice.workspace_id,
                        "project_id": invoice.project_id,
                        "milestone_id": invoice.milestone_id,
                        "amount_minor": invoice.billed_amount_minor,
                        "finance_entry_id": finance_entry_id,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL save milestone invoice failed: {exc}") from exc

    def _origin(self, kind: str, workspace: str, identifier: str, origin: Mapping[str, str] | None,
                *, before: bool = False) -> None:
        if origin is None:
            return
        org, entity = origin["organization_id"], origin["legal_entity_id"]
        row = self.connection.execute("SELECT current_setting('app.organization_id',true),current_setting('app.legal_entity_id',true),current_setting('app.workspace_id',true)").fetchone()
        if not row or tuple(row) != (org, entity, workspace) or not org or not entity:
            raise ProjectBillingError("project_source_scope_denied", "Source origin requires the current authenticated hierarchy.")
        query = ("SELECT organization_id,legal_entity_id FROM reconforge.project_milestones WHERE tenant_id=%s AND workspace_id=%s AND milestone_id=%s FOR UPDATE"
            if kind == "milestone" else
            "SELECT organization_id,legal_entity_id FROM reconforge.project_milestone_invoices WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s FOR UPDATE")
        existing = self.connection.execute(query, (self.tenant_id, workspace, identifier)).fetchone()
        if before:
            if existing is not None and tuple(existing) != (org, entity):
                raise ProjectBillingError("project_source_scope_denied", "Historical or foreign source origin cannot be inferred or replaced.")
            return
        query = ("UPDATE reconforge.project_milestones SET organization_id=%s,legal_entity_id=%s WHERE tenant_id=%s AND workspace_id=%s AND milestone_id=%s AND organization_id IS NULL AND legal_entity_id IS NULL"
            if kind == "milestone" else
            "UPDATE reconforge.project_milestone_invoices SET organization_id=%s,legal_entity_id=%s WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s AND organization_id IS NULL AND legal_entity_id IS NULL")
        self.connection.execute(query, (org, entity, self.tenant_id, workspace, identifier))

    def prepare_financial_invoice(self, milestone_id: str, *, invoice_id: str, customer_code: str, issued_at: str | None,
                                  scope: Mapping[str, str], period_id: str, posting_date: str, journal_code: str,
                                  command_id: str, actor: Any) -> dict[str, Any]:
        from reconforge.domain.project_milestone_billing import generate_milestone_invoice
        from reconforge.infrastructure.postgres_enterprise_finance_bridge import PostgresEnterpriseFinanceBridge

        with self.connection.transaction():
            self._scope()
            workspace = scope["workspace_id"]
            prior = self.connection.execute("SELECT customer_code,issued_at,milestone_id FROM reconforge.project_milestone_invoices WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s FOR UPDATE", (self.tenant_id, workspace, invoice_id)).fetchone()
            if prior is not None:
                effective_issued_at = issued_at if issued_at is not None else prior[1]
                if tuple(prior) != (customer_code, effective_issued_at, milestone_id):
                    raise ProjectBillingError("project_invoice_conflict", "Invoice identity belongs to another exact request.")
            else:
                self.connection.execute("SELECT milestone_id FROM reconforge.project_milestones WHERE tenant_id=%s AND workspace_id=%s AND milestone_id=%s FOR UPDATE", (self.tenant_id, workspace, milestone_id)).fetchone()
                milestone = self.get_milestone(workspace, milestone_id)
                if milestone is None:
                    raise ProjectBillingError("milestone_not_found", "The original milestone was not found.")
                updated, invoice = generate_milestone_invoice(milestone, customer_code=customer_code, invoice_id=invoice_id, issued_at=issued_at if issued_at is not None else utc_now_text())
                self.save_milestone_invoice(updated, invoice, actor_label=actor.username, origin=scope)
            return PostgresEnterpriseFinanceBridge(self.connection, self.tenant_id).prepare("ProjectMilestone", invoice_id,
                scope=scope, period_id=period_id, posting_date=posting_date, journal_code=journal_code,
                command_id=command_id, actor=actor)

    def post_milestone_invoice_to_finance_core(
        self,
        *,
        invoice: MilestoneBillingInvoice,
        organization_code: str,
        entity_code: str,
        period_id: str,
        journal_code: str = "GENERAL",
        finance_core_repo: Any | None = None,
        precision: int = 2,
        actor_label: str = "project-billing",
    ) -> str:
        """Create and link a balanced Finance Core draft; validation and approval remain separate."""
        if finance_core_repo is None:
            raise PlatformError("Finance Core repository is required for canonical milestone posting.")
        try:
            entry_number = f"PMI-{invoice.invoice_id}"
            whole = invoice.billed_amount_minor // (10 ** precision)
            cents = invoice.billed_amount_minor % (10 ** precision)
            amount_str = f"{whole}.{cents:0{precision}d}"
            zero_str = f"0.{'0' * precision}"

            lines = [
                {
                    "account_code": invoice.gl_debit_account,
                    "debit": amount_str,
                    "credit": zero_str,
                    "description": f"Milestone billing AR {invoice.milestone_id}",
                },
                {
                    "account_code": invoice.gl_credit_account,
                    "debit": zero_str,
                    "credit": amount_str,
                    "description": f"Milestone billing Revenue {invoice.milestone_id}",
                },
            ]
            entry = finance_core_repo.create_entry(
                entry_number=entry_number,
                organization_code=organization_code,
                entity_code=entity_code,
                period_id=period_id,
                journal_code=journal_code,
                posting_date=invoice.issued_at.split("T")[0] if "T" in invoice.issued_at else invoice.issued_at,
                description=f"Project milestone invoice {invoice.invoice_id}",
                lines=lines,
                workspace=invoice.workspace_id,
                source_type="Generated",
                actor_label=actor_label,
            )
            entry_id = entry.get("id") if isinstance(entry, Mapping) else None
            if not isinstance(entry_id, str) or not entry_id.strip():
                raise PlatformError("Finance Core did not return a canonical entry identifier.")
            returned_status = entry.get("status")
            entry_status = returned_status if isinstance(returned_status, str) and returned_status in {"Draft", "Validated", "Voided"} else "Unknown"

            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    UPDATE reconforge.project_milestone_invoices
                    SET finance_entry_id = %s
                    WHERE tenant_id = %s AND workspace_id = %s AND invoice_id = %s
                    """,
                    (entry_id, self.tenant_id, invoice.workspace_id, invoice.invoice_id),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_milestone_invoice",
                    object_id=invoice.invoice_id,
                    action="milestone_gl_linked",
                    after_hash=hashlib.sha256(f"{invoice.invoice_id}:{entry_id}:{invoice.billed_amount_minor}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": invoice.workspace_id,
                        "invoice_id": invoice.invoice_id,
                        "finance_entry_id": entry_id,
                        "finance_entry_status": entry_status,
                        "amount_minor": invoice.billed_amount_minor,
                    },
                )
            return entry_id
        except Exception as exc:
            raise PlatformError(f"PostgreSQL post milestone invoice to Finance Core failed: {exc}") from exc

    def log_time(
        self,
        workspace_id: str,
        log_id: str,
        project_id: str,
        task_id: str,
        role: str,
        hours: int,
        date: str,
        *,
        actor_label: str = "system",
    ) -> tuple[int, int]:
        rate_card = self.get_rate_card(workspace_id, project_id, role)
        if not rate_card:
            raise ProjectBillingError(
                code="rate_card_missing",
                message=f"No rate card found for project {project_id} and role {role}",
            )
        actual_cost = hours * rate_card.hourly_cost_rate_minor
        billable_amount = hours * rate_card.hourly_bill_rate_minor

        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.project_time_logs (
                        tenant_id, workspace_id, log_id, project_id, task_id, resource_role,
                        hours_worked, log_date, actual_cost_minor, billable_amount_minor
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, log_id) DO UPDATE SET
                        hours_worked = excluded.hours_worked,
                        actual_cost_minor = excluded.actual_cost_minor,
                        billable_amount_minor = excluded.billable_amount_minor
                    """,
                    (
                        self.tenant_id,
                        workspace_id,
                        log_id,
                        project_id,
                        task_id,
                        role,
                        hours,
                        date,
                        actual_cost,
                        billable_amount,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="project_time_log",
                    object_id=log_id,
                    action="time_logged",
                    after_hash=hashlib.sha256(f"{log_id}:{actual_cost}:{billable_amount}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "hours": hours,
                        "role": role,
                    },
                )
            return actual_cost, billable_amount
        except ProjectBillingError:
            raise
        except Exception as exc:
            raise PlatformError(f"PostgreSQL log time failed: {exc}") from exc

    def get_financial_posture(
        self,
        workspace_id: str,
        project_id: str,
        currency: str,
    ) -> ProjectFinancialPosture:
        try:
            with self.connection.transaction():
                self._scope()
                budget_cur = self.connection.execute(
                    """
                    SELECT COALESCE(SUM(budget_cost_minor), 0)
                    FROM reconforge.project_wbs_tasks
                    WHERE tenant_id = %s AND workspace_id = %s AND project_id = %s
                    """,
                    (self.tenant_id, workspace_id, project_id),
                )
                budget = int(budget_cur.fetchone()[0])

                cost_cur = self.connection.execute(
                    """
                    SELECT COALESCE(SUM(actual_cost_minor), 0)
                    FROM reconforge.project_time_logs
                    WHERE tenant_id = %s AND workspace_id = %s AND project_id = %s
                    """,
                    (self.tenant_id, workspace_id, project_id),
                )
                actual_cost = int(cost_cur.fetchone()[0])

                billed_cur = self.connection.execute(
                    """
                    SELECT COALESCE(SUM(billed_amount_minor), 0)
                    FROM reconforge.project_milestone_invoices
                    WHERE tenant_id = %s AND workspace_id = %s AND project_id = %s
                    """,
                    (self.tenant_id, workspace_id, project_id),
                )
                total_billed = int(billed_cur.fetchone()[0])

                return calculate_financial_posture(
                    project_id=project_id,
                    currency=currency,
                    budget_cost_minor=budget,
                    actual_cost_minor=actual_cost,
                    total_billed_minor=total_billed,
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get financial posture failed: {exc}") from exc


PostgresProjectBillingRepository = PostgresProjectMilestoneBillingRepository

__all__ = [
    "POSTGRES_PROJECT_BILLING_SCHEMA_SQL",
    "PostgresProjectBillingRepository",
    "PostgresProjectMilestoneBillingRepository",
]
