"""SQLite persistence repository for CRM Opportunities, Quotations, and Contracts."""

from __future__ import annotations

import sqlite3
from typing import cast

from reconforge.domain.crm_contracts import (
    BillingFrequency,
    ContractStatus,
    CustomerContract,
    CustomerQuotation,
    Opportunity,
    OpportunityStage,
    QuotationLineItem,
    QuoteStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)

CREATE_CRM_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS crm_opportunities (
    workspace_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL,
    estimated_close_date TEXT NOT NULL,
    currency TEXT NOT NULL,
    projected_amount_minor INTEGER NOT NULL,
    win_probability_bps INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS crm_quotations (
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    submitter_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_by_user_id TEXT,
    approval_role TEXT,
    PRIMARY KEY (workspace_id, quote_id)
);

CREATE TABLE IF NOT EXISTS crm_quotation_lines (
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    discount_bps INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (quote_id, line_number)
);

CREATE TABLE IF NOT EXISTS crm_contracts (
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    billing_frequency TEXT NOT NULL,
    total_contract_value_minor INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (workspace_id, contract_id)
);

CREATE TABLE IF NOT EXISTS crm_subscription_plans (
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    billing_interval TEXT NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, plan_id)
);

CREATE TABLE IF NOT EXISTS crm_subscriptions (
    workspace_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    auto_renew INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (workspace_id, subscription_id)
);
"""


class SqliteCRMContractsRepository:
    """Thread-safe SQLite storage for CRM opportunities, quotes, and customer contracts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_CRM_TABLES_SQL)
        self._conn.commit()

    # --- Opportunities ---

    def save_opportunity(self, opp: Opportunity) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crm_opportunities (
                    workspace_id, opportunity_id, organization_id, customer_id,
                    title, stage, estimated_close_date, currency,
                    projected_amount_minor, win_probability_bps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, opportunity_id) DO UPDATE SET
                    stage = excluded.stage,
                    estimated_close_date = excluded.estimated_close_date,
                    projected_amount_minor = excluded.projected_amount_minor,
                    win_probability_bps = excluded.win_probability_bps
                """,
                (
                    opp.workspace_id,
                    opp.opportunity_id,
                    opp.organization_id,
                    opp.customer_id,
                    opp.title,
                    opp.stage,
                    opp.estimated_close_date,
                    opp.currency,
                    opp.projected_amount_minor,
                    opp.win_probability_bps,
                ),
            )

    def get_opportunity(self, workspace_id: str, opportunity_id: str) -> Opportunity | None:
        cursor = self._conn.execute(
            """
            SELECT opportunity_id, workspace_id, organization_id, customer_id,
                   title, stage, estimated_close_date, currency,
                   projected_amount_minor, win_probability_bps
            FROM crm_opportunities
            WHERE workspace_id = ? AND opportunity_id = ?
            """,
            (workspace_id, opportunity_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Opportunity(
            opportunity_id=row[0],
            workspace_id=row[1],
            organization_id=row[2],
            customer_id=row[3],
            title=row[4],
            stage=cast(OpportunityStage, row[5]),
            estimated_close_date=row[6],
            currency=row[7],
            projected_amount_minor=row[8],
            win_probability_bps=row[9],
        )

    # --- Quotations ---

    def save_quotation(self, quote: CustomerQuotation) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crm_quotations (
                    workspace_id, quote_id, opportunity_id, customer_id,
                    currency, valid_until, submitter_user_id, status,
                    approved_by_user_id, approval_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, quote_id) DO UPDATE SET
                    status = excluded.status,
                    approved_by_user_id = excluded.approved_by_user_id,
                    approval_role = excluded.approval_role
                """,
                (
                    quote.workspace_id,
                    quote.quote_id,
                    quote.opportunity_id,
                    quote.customer_id,
                    quote.currency,
                    quote.valid_until,
                    quote.submitter_user_id,
                    quote.status,
                    quote.approved_by_user_id,
                    quote.approval_role,
                ),
            )
            self._conn.execute("DELETE FROM crm_quotation_lines WHERE quote_id = ?", (quote.quote_id,))
            for line in quote.lines:
                self._conn.execute(
                    """
                    INSERT INTO crm_quotation_lines (
                        quote_id, line_number, item_id, description,
                        quantity, unit_price_minor, discount_bps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        quote.quote_id,
                        line.line_number,
                        line.item_id,
                        line.description,
                        line.quantity,
                        line.unit_price_minor,
                        line.discount_bps,
                    ),
                )

    def get_quotation(self, workspace_id: str, quote_id: str) -> CustomerQuotation | None:
        cursor = self._conn.execute(
            """
            SELECT quote_id, opportunity_id, workspace_id, customer_id,
                   currency, valid_until, submitter_user_id, status,
                   approved_by_user_id, approval_role
            FROM crm_quotations
            WHERE workspace_id = ? AND quote_id = ?
            """,
            (workspace_id, quote_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        lines_cursor = self._conn.execute(
            """
            SELECT line_number, item_id, description, quantity, unit_price_minor, discount_bps
            FROM crm_quotation_lines
            WHERE quote_id = ?
            ORDER BY line_number ASC
            """,
            (quote_id,),
        )
        lines = tuple(
            QuotationLineItem(
                line_number=lrow[0],
                item_id=lrow[1],
                description=lrow[2],
                quantity=lrow[3],
                unit_price_minor=lrow[4],
                discount_bps=lrow[5],
            )
            for lrow in lines_cursor.fetchall()
        )

        return CustomerQuotation(
            quote_id=row[0],
            opportunity_id=row[1],
            workspace_id=row[2],
            customer_id=row[3],
            currency=row[4],
            valid_until=row[5],
            submitter_user_id=row[6],
            status=cast(QuoteStatus, row[7]),
            lines=lines,
            approved_by_user_id=row[8],
            approval_role=row[9],
        )

    # --- Contracts ---

    def save_contract(self, contract: CustomerContract) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crm_contracts (
                    workspace_id, contract_id, quote_id, organization_id,
                    customer_id, currency, start_date, end_date,
                    billing_frequency, total_contract_value_minor, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, contract_id) DO UPDATE SET
                    end_date = excluded.end_date,
                    total_contract_value_minor = excluded.total_contract_value_minor,
                    status = excluded.status
                """,
                (
                    contract.workspace_id,
                    contract.contract_id,
                    contract.quote_id,
                    contract.organization_id,
                    contract.customer_id,
                    contract.currency,
                    contract.start_date,
                    contract.end_date,
                    contract.billing_frequency,
                    contract.total_contract_value_minor,
                    contract.status,
                ),
            )

    def get_contract(self, workspace_id: str, contract_id: str) -> CustomerContract | None:
        cursor = self._conn.execute(
            """
            SELECT contract_id, quote_id, workspace_id, organization_id,
                   customer_id, currency, start_date, end_date,
                   billing_frequency, total_contract_value_minor, status
            FROM crm_contracts
            WHERE workspace_id = ? AND contract_id = ?
            """,
            (workspace_id, contract_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return CustomerContract(
            contract_id=row[0],
            quote_id=row[1],
            workspace_id=row[2],
            organization_id=row[3],
            customer_id=row[4],
            currency=row[5],
            start_date=row[6],
            end_date=row[7],
            billing_frequency=cast(BillingFrequency, row[8]),
            total_contract_value_minor=row[9],
            status=cast(ContractStatus, row[10]),
        )

    # --- Subscription Plans ---

    def save_plan(self, workspace_id: str, plan: SubscriptionPlan) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crm_subscription_plans (
                    workspace_id, plan_id, name, currency, billing_interval, unit_price_minor
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, plan_id) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    billing_interval = excluded.billing_interval,
                    unit_price_minor = excluded.unit_price_minor
                """,
                (
                    workspace_id,
                    plan.plan_id,
                    plan.name,
                    plan.currency,
                    plan.billing_interval,
                    plan.unit_price_minor,
                ),
            )

    def get_plan(self, workspace_id: str, plan_id: str) -> SubscriptionPlan | None:
        cursor = self._conn.execute(
            """
            SELECT plan_id, name, currency, billing_interval, unit_price_minor
            FROM crm_subscription_plans
            WHERE workspace_id = ? AND plan_id = ?
            """,
            (workspace_id, plan_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return SubscriptionPlan(
            plan_id=row[0],
            name=row[1],
            currency=row[2],
            billing_interval=cast(BillingFrequency, row[3]),
            unit_price_minor=row[4],
        )

    def list_plans(self, workspace_id: str) -> list[SubscriptionPlan]:
        cursor = self._conn.execute(
            """
            SELECT plan_id, name, currency, billing_interval, unit_price_minor
            FROM crm_subscription_plans
            WHERE workspace_id = ?
            ORDER BY plan_id
            """,
            (workspace_id,),
        )
        return [
            SubscriptionPlan(
                plan_id=row[0],
                name=row[1],
                currency=row[2],
                billing_interval=cast(BillingFrequency, row[3]),
                unit_price_minor=row[4],
            )
            for row in cursor.fetchall()
        ]

    # --- Subscriptions ---

    def save_subscription(self, workspace_id: str, subscription: Subscription) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crm_subscriptions (
                    workspace_id, subscription_id, customer_id, contract_id,
                    plan_id, currency, status, current_period_start,
                    current_period_end, auto_renew
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, subscription_id) DO UPDATE SET
                    customer_id = excluded.customer_id,
                    contract_id = excluded.contract_id,
                    plan_id = excluded.plan_id,
                    currency = excluded.currency,
                    status = excluded.status,
                    current_period_start = excluded.current_period_start,
                    current_period_end = excluded.current_period_end,
                    auto_renew = excluded.auto_renew
                """,
                (
                    workspace_id,
                    subscription.subscription_id,
                    subscription.customer_id,
                    subscription.contract_id,
                    subscription.plan_id,
                    subscription.currency,
                    subscription.status,
                    subscription.current_period_start,
                    subscription.current_period_end,
                    1 if subscription.auto_renew else 0,
                ),
            )

    def get_subscription(self, workspace_id: str, subscription_id: str) -> Subscription | None:
        cursor = self._conn.execute(
            """
            SELECT subscription_id, customer_id, contract_id, plan_id,
                   currency, status, current_period_start, current_period_end, auto_renew
            FROM crm_subscriptions
            WHERE workspace_id = ? AND subscription_id = ?
            """,
            (workspace_id, subscription_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Subscription(
            subscription_id=row[0],
            customer_id=row[1],
            contract_id=row[2],
            plan_id=row[3],
            currency=row[4],
            status=cast(SubscriptionStatus, row[5]),
            current_period_start=row[6],
            current_period_end=row[7],
            auto_renew=bool(row[8]),
        )

    def list_subscriptions(self, workspace_id: str, customer_id: str | None = None) -> list[Subscription]:
        if customer_id:
            cursor = self._conn.execute(
                """
                SELECT subscription_id, customer_id, contract_id, plan_id,
                       currency, status, current_period_start, current_period_end, auto_renew
                FROM crm_subscriptions
                WHERE workspace_id = ? AND customer_id = ?
                ORDER BY subscription_id
                """,
                (workspace_id, customer_id),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT subscription_id, customer_id, contract_id, plan_id,
                       currency, status, current_period_start, current_period_end, auto_renew
                FROM crm_subscriptions
                WHERE workspace_id = ?
                ORDER BY subscription_id
                """,
                (workspace_id,),
            )
        return [
            Subscription(
                subscription_id=row[0],
                customer_id=row[1],
                contract_id=row[2],
                plan_id=row[3],
                currency=row[4],
                status=cast(SubscriptionStatus, row[5]),
                current_period_start=row[6],
                current_period_end=row[7],
                auto_renew=bool(row[8]),
            )
            for row in cursor.fetchall()
        ]
