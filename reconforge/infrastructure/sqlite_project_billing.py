"""SQLite persistence adapter for Professional Services Project Billing and Costing."""

from __future__ import annotations

import sqlite3

from reconforge.domain.project_milestone_billing import (
    MilestoneBillingInvoice,
    ProjectBillingError,
    ProjectFinancialPosture,
    ProjectMilestone,
    ProjectWBSTask,
    ResourceRateCard,
    calculate_financial_posture,
)

CREATE_PROJECT_BILLING_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS project_wbs_tasks (
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_task_id TEXT,
    planned_hours INTEGER NOT NULL DEFAULT 0,
    budget_cost_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    PRIMARY KEY (workspace_id, task_id)
);

CREATE TABLE IF NOT EXISTS project_resource_rate_cards (
    workspace_id TEXT NOT NULL,
    rate_card_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hourly_cost_rate_minor INTEGER NOT NULL,
    hourly_bill_rate_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (workspace_id, project_id, resource_role)
);

CREATE TABLE IF NOT EXISTS project_milestones (
    workspace_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    contract_line_id TEXT NOT NULL,
    title TEXT NOT NULL,
    milestone_amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_by TEXT,
    verified_at TEXT,
    PRIMARY KEY (workspace_id, milestone_id)
);

CREATE TABLE IF NOT EXISTS project_milestone_invoices (
    workspace_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    milestone_id TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    billed_amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    gl_debit_account TEXT NOT NULL,
    gl_credit_account TEXT NOT NULL,
    finance_entry_id TEXT,
    PRIMARY KEY (workspace_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS project_time_logs (
    workspace_id TEXT NOT NULL,
    log_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    resource_role TEXT NOT NULL,
    hours_worked INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    actual_cost_minor INTEGER NOT NULL,
    billable_amount_minor INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, log_id)
);
"""


class SqliteProjectBillingRepository:
    """Thread-safe SQLite storage for WBS tasks, rate cards, milestones, invoices, and time logs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_PROJECT_BILLING_TABLES_SQL)
        self._conn.commit()

    def save_task(self, task: ProjectWBSTask) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO project_wbs_tasks (
                    workspace_id, task_id, project_id, task_code, name,
                    parent_task_id, planned_hours, budget_cost_minor, currency, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, task_id) DO UPDATE SET
                    name = excluded.name,
                    planned_hours = excluded.planned_hours,
                    budget_cost_minor = excluded.budget_cost_minor,
                    status = excluded.status
                """,
                (
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

    def list_tasks(self, workspace_id: str, project_id: str) -> list[ProjectWBSTask]:
        cursor = self._conn.execute(
            """
            SELECT workspace_id, task_id, project_id, task_code, name,
                   parent_task_id, planned_hours, budget_cost_minor, currency, status
            FROM project_wbs_tasks
            WHERE workspace_id = ? AND project_id = ?
            ORDER BY task_code ASC
            """,
            (workspace_id, project_id),
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
                budget_cost_minor=r[7],
                currency=r[8],
                status=r[9],
            )
            for r in cursor.fetchall()
        ]

    def save_rate_card(self, card: ResourceRateCard) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO project_resource_rate_cards (
                    workspace_id, rate_card_id, project_id, resource_role,
                    hourly_cost_rate_minor, hourly_bill_rate_minor, currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, project_id, resource_role) DO UPDATE SET
                    hourly_cost_rate_minor = excluded.hourly_cost_rate_minor,
                    hourly_bill_rate_minor = excluded.hourly_bill_rate_minor,
                    currency = excluded.currency
                """,
                (
                    card.workspace_id,
                    card.rate_card_id,
                    card.project_id,
                    card.resource_role,
                    card.hourly_cost_rate_minor,
                    card.hourly_bill_rate_minor,
                    card.currency,
                ),
            )

    def get_rate_card(self, workspace_id: str, project_id: str, role: str) -> ResourceRateCard | None:
        cursor = self._conn.execute(
            """
            SELECT workspace_id, rate_card_id, project_id, resource_role,
                   hourly_cost_rate_minor, hourly_bill_rate_minor, currency
            FROM project_resource_rate_cards
            WHERE workspace_id = ? AND project_id = ? AND resource_role = ?
            """,
            (workspace_id, project_id, role),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ResourceRateCard(
            workspace_id=row[0],
            rate_card_id=row[1],
            project_id=row[2],
            resource_role=row[3],
            hourly_cost_rate_minor=row[4],
            hourly_bill_rate_minor=row[5],
            currency=row[6],
        )

    def save_milestone(self, m: ProjectMilestone) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO project_milestones (
                    workspace_id, milestone_id, project_id, contract_line_id,
                    title, milestone_amount_minor, currency, due_date, status,
                    verified_by, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, milestone_id) DO UPDATE SET
                    title = excluded.title,
                    milestone_amount_minor = excluded.milestone_amount_minor,
                    due_date = excluded.due_date,
                    status = excluded.status,
                    verified_by = excluded.verified_by,
                    verified_at = excluded.verified_at
                """,
                (
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
        cursor = self._conn.execute(
            """
            SELECT workspace_id, milestone_id, project_id, contract_line_id,
                   title, milestone_amount_minor, currency, due_date, status,
                   verified_by, verified_at
            FROM project_milestones
            WHERE workspace_id = ? AND milestone_id = ?
            """,
            (workspace_id, milestone_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ProjectMilestone(
            workspace_id=row[0],
            milestone_id=row[1],
            project_id=row[2],
            contract_line_id=row[3],
            title=row[4],
            milestone_amount_minor=row[5],
            currency=row[6],
            due_date=row[7],
            status=row[8],
            verified_by=row[9],
            verified_at=row[10],
        )

    def save_milestone_invoice(
        self,
        milestone: ProjectMilestone,
        invoice: MilestoneBillingInvoice,
    ) -> None:
        with self._conn:
            self.save_milestone(milestone)
            self._conn.execute(
                """
                INSERT INTO project_milestone_invoices (
                    workspace_id, invoice_id, project_id, milestone_id,
                    customer_code, billed_amount_minor, currency, issued_at,
                    gl_debit_account, gl_credit_account
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, invoice_id) DO NOTHING
                """,
                (
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
                ),
            )

    def log_time(
        self,
        workspace_id: str,
        log_id: str,
        project_id: str,
        task_id: str,
        role: str,
        hours: int,
        date: str,
    ) -> tuple[int, int]:
        rate_card = self.get_rate_card(workspace_id, project_id, role)
        if not rate_card:
            raise ProjectBillingError(
                code="rate_card_missing",
                message=f"No rate card found for project {project_id} and role {role}",
            )
        actual_cost = hours * rate_card.hourly_cost_rate_minor
        billable_amount = hours * rate_card.hourly_bill_rate_minor

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO project_time_logs (
                    workspace_id, log_id, project_id, task_id, resource_role,
                    hours_worked, log_date, actual_cost_minor, billable_amount_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, log_id) DO UPDATE SET
                    hours_worked = excluded.hours_worked,
                    actual_cost_minor = excluded.actual_cost_minor,
                    billable_amount_minor = excluded.billable_amount_minor
                """,
                (workspace_id, log_id, project_id, task_id, role, hours, date, actual_cost, billable_amount),
            )

        return actual_cost, billable_amount

    def get_financial_posture(
        self,
        workspace_id: str,
        project_id: str,
        currency: str,
    ) -> ProjectFinancialPosture:
        # Sum budget from tasks
        budget_cur = self._conn.execute(
            "SELECT COALESCE(SUM(budget_cost_minor), 0) FROM project_wbs_tasks WHERE workspace_id = ? AND project_id = ?",
            (workspace_id, project_id),
        )
        budget = budget_cur.fetchone()[0]

        # Sum actual cost from time logs
        cost_cur = self._conn.execute(
            "SELECT COALESCE(SUM(actual_cost_minor), 0) FROM project_time_logs WHERE workspace_id = ? AND project_id = ?",
            (workspace_id, project_id),
        )
        actual_cost = cost_cur.fetchone()[0]

        # Sum billed from milestone invoices
        billed_cur = self._conn.execute(
            "SELECT COALESCE(SUM(billed_amount_minor), 0) FROM project_milestone_invoices WHERE workspace_id = ? AND project_id = ?",
            (workspace_id, project_id),
        )
        total_billed = billed_cur.fetchone()[0]

        return calculate_financial_posture(
            project_id=project_id,
            currency=currency,
            budget_cost_minor=budget,
            actual_cost_minor=actual_cost,
            total_billed_minor=total_billed,
        )
