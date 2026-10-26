"""PostgreSQL tenant/workspace-scoped persistence for CRM Opportunities, Quotations, Contracts, and Subscriptions with FORCE RLS."""

from __future__ import annotations

from typing import Any, cast

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
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import current_server_principal

POSTGRES_CRM_CONTRACTS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.crm_opportunities (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL,
    estimated_close_date TEXT NOT NULL,
    currency TEXT NOT NULL,
    projected_amount_minor BIGINT NOT NULL,
    win_probability_bps INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, opportunity_id)
);
ALTER TABLE reconforge.crm_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_opportunities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_opportunities;
CREATE POLICY tenant_scope ON reconforge.crm_opportunities
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_quotations (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, quote_id)
);
ALTER TABLE reconforge.crm_quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotations;
CREATE POLICY tenant_scope ON reconforge.crm_quotations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));


CREATE TABLE IF NOT EXISTS reconforge.crm_quotation_authorities (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    identity_contract TEXT NOT NULL CHECK(identity_contract='canonical-user-v1'),
    PRIMARY KEY(tenant_id,workspace_id,quote_id),
    FOREIGN KEY(tenant_id,workspace_id,quote_id) REFERENCES reconforge.crm_quotations(tenant_id,workspace_id,quote_id),
    FOREIGN KEY(tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
ALTER TABLE reconforge.crm_quotation_authorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotation_authorities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotation_authorities;
CREATE POLICY tenant_scope ON reconforge.crm_quotation_authorities
    USING (tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true));
CREATE OR REPLACE FUNCTION reconforge.reject_crm_authority_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Quotation authority is immutable'; END;
$$;
DROP TRIGGER IF EXISTS crm_authority_immutable ON reconforge.crm_quotation_authorities;
CREATE TRIGGER crm_authority_immutable BEFORE UPDATE OR DELETE ON reconforge.crm_quotation_authorities
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_crm_authority_mutation();

CREATE TABLE IF NOT EXISTS reconforge.crm_quotation_lines (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_minor BIGINT NOT NULL,
    discount_bps INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, workspace_id, quote_id, line_number)
);
ALTER TABLE reconforge.crm_quotation_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotation_lines FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotation_lines;
CREATE POLICY tenant_scope ON reconforge.crm_quotation_lines
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_contracts (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    billing_frequency TEXT NOT NULL,
    total_contract_value_minor BIGINT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, contract_id)
);
ALTER TABLE reconforge.crm_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_contracts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_contracts;
CREATE POLICY tenant_scope ON reconforge.crm_contracts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_subscription_plans (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    billing_interval TEXT NOT NULL,
    unit_price_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, plan_id)
);
ALTER TABLE reconforge.crm_subscription_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscription_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscription_plans;
CREATE POLICY tenant_scope ON reconforge.crm_subscription_plans
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.crm_subscriptions (
    tenant_id TEXT NOT NULL,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, subscription_id)
);
ALTER TABLE reconforge.crm_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_subscriptions;
CREATE POLICY tenant_scope ON reconforge.crm_subscriptions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresCRMContractsRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for CRM opportunities, quotes, contracts, and subscriptions."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        ensure_repository_tenant_scope(self.connection, self.tenant_id)

    # --- Opportunities ---

    def save_opportunity(self, opp: Opportunity) -> None:
        with self.connection.transaction():
            self._scope()
            self.connection.execute(
                """
                INSERT INTO reconforge.crm_opportunities (
                    tenant_id, workspace_id, opportunity_id, organization_id, customer_id,
                    title, stage, estimated_close_date, currency,
                    projected_amount_minor, win_probability_bps
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, opportunity_id) DO UPDATE SET
                    stage = excluded.stage,
                    estimated_close_date = excluded.estimated_close_date,
                    projected_amount_minor = excluded.projected_amount_minor,
                    win_probability_bps = excluded.win_probability_bps
                """,
                (
                    self.tenant_id,
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
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT opportunity_id, workspace_id, organization_id, customer_id,
                   title, stage, estimated_close_date, currency,
                   projected_amount_minor, win_probability_bps
            FROM reconforge.crm_opportunities
            WHERE workspace_id = %s AND opportunity_id = %s
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
            projected_amount_minor=int(row[8]),
            win_probability_bps=int(row[9]),
        )

    def list_opportunities(self, workspace_id: str) -> list[Opportunity]:
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT opportunity_id, workspace_id, organization_id, customer_id,
                   title, stage, estimated_close_date, currency,
                   projected_amount_minor, win_probability_bps
            FROM reconforge.crm_opportunities
            WHERE workspace_id = %s
            ORDER BY opportunity_id
            """,
            (workspace_id,),
        )
        return [
            Opportunity(
                opportunity_id=row[0],
                workspace_id=row[1],
                organization_id=row[2],
                customer_id=row[3],
                title=row[4],
                stage=cast(OpportunityStage, row[5]),
                estimated_close_date=row[6],
                currency=row[7],
                projected_amount_minor=int(row[8]),
                win_probability_bps=int(row[9]),
            )
            for row in cursor.fetchall()
        ]

    # --- Quotations ---

    def quotation_author_id(self, workspace_id: str, quote_id: str) -> str | None:
        self._scope()
        row = self.connection.execute(
            "SELECT user_id FROM reconforge.crm_quotation_authorities WHERE tenant_id=%s AND workspace_id=%s AND quote_id=%s AND identity_contract='canonical-user-v1'",
            (self.tenant_id, workspace_id, quote_id),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def save_quotation(self, quote: CustomerQuotation, *, author_user_id: str | None = None) -> None:
        principal = current_server_principal()
        if author_user_id is not None and (author_user_id != quote.submitter_user_id or (principal is not None and author_user_id != principal.user.id)):
            raise FinancePostingError("crm_quotation_author_denied", "Quotation authorship must be the authenticated immutable identity.")
        with self.connection.transaction():
            self._scope()
            cursor = self.connection.execute(
                """
                INSERT INTO reconforge.crm_quotations (
                    tenant_id, workspace_id, quote_id, opportunity_id, customer_id,
                    currency, valid_until, submitter_user_id, status,
                    approved_by_user_id, approval_role
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, quote_id) DO UPDATE SET
                    status = excluded.status,
                    approved_by_user_id = excluded.approved_by_user_id,
                    approval_role = excluded.approval_role
                WHERE %s
                RETURNING quote_id
                """,
                (
                    self.tenant_id,
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
                    author_user_id is None,
                ),
            )
            if cursor.fetchone() is None:
                raise FinancePostingError("crm_quotation_exists", "Quotation creation cannot replace an existing source.")
            if author_user_id is not None:
                self.connection.execute(
                    "INSERT INTO reconforge.crm_quotation_authorities(tenant_id,workspace_id,quote_id,user_id,identity_contract) VALUES(%s,%s,%s,%s,'canonical-user-v1')",
                    (self.tenant_id, quote.workspace_id, quote.quote_id, author_user_id),
                )
            for line in quote.lines:
                self.connection.execute(
                    """
                    INSERT INTO reconforge.crm_quotation_lines (
                        tenant_id, workspace_id, quote_id, line_number, item_id,
                        description, quantity, unit_price_minor, discount_bps
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, quote_id, line_number) DO UPDATE SET
                        item_id = excluded.item_id,
                        description = excluded.description,
                        quantity = excluded.quantity,
                        unit_price_minor = excluded.unit_price_minor,
                        discount_bps = excluded.discount_bps
                    """,
                    (
                        self.tenant_id,
                        quote.workspace_id,
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
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT quote_id, opportunity_id, workspace_id, customer_id,
                   currency, valid_until, submitter_user_id, status,
                   approved_by_user_id, approval_role
            FROM reconforge.crm_quotations
            WHERE workspace_id = %s AND quote_id = %s
            """,
            (workspace_id, quote_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        line_cursor = self.connection.execute(
            """
            SELECT line_number, item_id, description, quantity, unit_price_minor, discount_bps
            FROM reconforge.crm_quotation_lines
            WHERE workspace_id = %s AND quote_id = %s
            ORDER BY line_number
            """,
            (workspace_id, quote_id),
        )
        lines = tuple(
            QuotationLineItem(
                line_number=lr[0],
                item_id=lr[1],
                description=lr[2],
                quantity=lr[3],
                unit_price_minor=int(lr[4]),
                discount_bps=int(lr[5]),
            )
            for lr in line_cursor.fetchall()
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
        with self.connection.transaction():
            self._scope()
            self.connection.execute(
                """
                INSERT INTO reconforge.crm_contracts (
                    tenant_id, workspace_id, contract_id, quote_id, organization_id,
                    customer_id, currency, start_date, end_date,
                    billing_frequency, total_contract_value_minor, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, contract_id) DO UPDATE SET
                    end_date = excluded.end_date,
                    total_contract_value_minor = excluded.total_contract_value_minor,
                    status = excluded.status
                """,
                (
                    self.tenant_id,
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
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT contract_id, quote_id, workspace_id, organization_id,
                   customer_id, currency, start_date, end_date,
                   billing_frequency, total_contract_value_minor, status
            FROM reconforge.crm_contracts
            WHERE workspace_id = %s AND contract_id = %s
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
            total_contract_value_minor=int(row[9]),
            status=cast(ContractStatus, row[10]),
        )

    # --- Subscription Plans ---

    def save_plan(self, workspace_id: str, plan: SubscriptionPlan) -> None:
        with self.connection.transaction():
            self._scope()
            self.connection.execute(
                """
                INSERT INTO reconforge.crm_subscription_plans (
                    tenant_id, workspace_id, plan_id, name, currency, billing_interval, unit_price_minor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, plan_id) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    billing_interval = excluded.billing_interval,
                    unit_price_minor = excluded.unit_price_minor
                """,
                (
                    self.tenant_id,
                    workspace_id,
                    plan.plan_id,
                    plan.name,
                    plan.currency,
                    plan.billing_interval,
                    plan.unit_price_minor,
                ),
            )

    def get_plan(self, workspace_id: str, plan_id: str) -> SubscriptionPlan | None:
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT plan_id, name, currency, billing_interval, unit_price_minor
            FROM reconforge.crm_subscription_plans
            WHERE workspace_id = %s AND plan_id = %s
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
            unit_price_minor=int(row[4]),
        )

    def list_plans(self, workspace_id: str) -> list[SubscriptionPlan]:
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT plan_id, name, currency, billing_interval, unit_price_minor
            FROM reconforge.crm_subscription_plans
            WHERE workspace_id = %s
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
                unit_price_minor=int(row[4]),
            )
            for row in cursor.fetchall()
        ]

    # --- Subscriptions ---

    def save_subscription(self, workspace_id: str, subscription: Subscription) -> None:
        with self.connection.transaction():
            self._scope()
            self.connection.execute(
                """
                INSERT INTO reconforge.crm_subscriptions (
                    tenant_id, workspace_id, subscription_id, customer_id, contract_id,
                    plan_id, currency, status, current_period_start,
                    current_period_end, auto_renew
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, subscription_id) DO UPDATE SET
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
                    self.tenant_id,
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
        self._scope()
        cursor = self.connection.execute(
            """
            SELECT subscription_id, customer_id, contract_id, plan_id,
                   currency, status, current_period_start, current_period_end, auto_renew
            FROM reconforge.crm_subscriptions
            WHERE workspace_id = %s AND subscription_id = %s
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
        self._scope()
        if customer_id:
            cursor = self.connection.execute(
                """
                SELECT subscription_id, customer_id, contract_id, plan_id,
                       currency, status, current_period_start, current_period_end, auto_renew
                FROM reconforge.crm_subscriptions
                WHERE workspace_id = %s AND customer_id = %s
                ORDER BY subscription_id
                """,
                (workspace_id, customer_id),
            )
        else:
            cursor = self.connection.execute(
                """
                SELECT subscription_id, customer_id, contract_id, plan_id,
                       currency, status, current_period_start, current_period_end, auto_renew
                FROM reconforge.crm_subscriptions
                WHERE workspace_id = %s
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
