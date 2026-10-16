"""Fixed monetary Stock lifecycle composed over native Stock, AR and FX owners.

Commercial quantities/prices remain in transaction currency. FIFO valuation and
its journal remain in functional currency. The 149 native closure owns their
immutable one-to-one recognition bridge and the ordered monetary history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, NoReturn
from uuid import uuid4

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload, text
from reconforge.domain.monetary_customer_returns import (
    ComponentCut,
    CostCut,
    MonetaryComponent,
    MonetaryConsumption,
    MonetaryEvent,
    MonetaryHistory,
    MonetaryMovement,
    MonetaryPosition,
    MonetaryReturnSource,
    prepare_monetary_event,
    replay_monetary_history,
)
from reconforge.domain.monetary_stock_revaluation import monetary_revaluation_equation
from reconforge.domain.operational_fx_revaluation import reversal_equation
from reconforge.domain.operational_fx_tax import (
    ForeignInvoicePreparation,
    HistoricalRate,
    TaxComponent,
    exact_minor,
    invoice_equation,
)
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.infrastructure.postgres_stock_sales import (
    OPERATION_PERMISSIONS as LEGACY_PERMISSIONS,
)
from reconforge.infrastructure.postgres_stock_sales import (
    READ,
    PostgresStockSalesRepository,
)
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import quantity_to_scaled
from reconforge.platform.receivables import ReceivableInvoiceLineInput
from reconforge.utils.money import CurrencyRegistryContext

SOURCE_SCHEMA = "stock-sales-monetary-order-v2"
FX_SOURCE_SCHEMA = "operational-fx-stock-source-v2"
OPERATION_PERMISSIONS = {key: frozenset(value) for key, value in LEGACY_PERMISSIONS.items()}
OPERATION_PERMISSIONS["prepare-collection"] |= {"receivables.manage"}
OPERATION_PERMISSIONS["review-collection"] |= {"receivables.approve"}
VALUATION_PERMISSIONS = {
    "read": READ,
    "prepare": READ | {"finance_core.manage", "receivables.manage"},
    "prepare_reversal": READ | {"finance_core.manage", "receivables.manage", "finance_core.reverse"},
    "review": READ | {"finance_core.validate", "receivables.approve"},
    "post": READ | {"finance_core.post", "receivables.manage"},
}


def _fail(code: str, message: str) -> NoReturn:
    raise FinancePostingError("stock_monetary_" + code, message)


def _full_policy(compact: Mapping[str, Any]) -> dict[str, Any]:
    return {"currency_code": compact["currency_code"], "currency_precision": compact["precision"],
        "currency_rounding_policy": compact["rounding_policy"], "currency_registry_version": compact["registry_version"],
        "currency_registry_digest": compact["registry_digest"]}


def book_carrying(origin: Mapping[str, Any]) -> int:
    """Authorize the actual exposed book balance, including an active closing."""
    try:
        balance = origin["ar_balance"]
        value = balance["functional_outstanding_minor"]
    except (KeyError, TypeError) as exc:
        raise FinancePostingError("stock_monetary_evidence_invalid", "The exact native book carrying projection is required.") from exc
    if (type(balance) is not dict or type(value) is not str or len(value) > 19 or not value.isascii() or not value.isdecimal()
            or (len(value) > 1 and value[0] == "0")):
        _fail("evidence_invalid", "The book carrying projection requires canonical exact minor text.")
    return exact_minor(int(value), "actual functional book carrying", zero=True)


def native_child_command(kind: str, command: str) -> str:
    """Bound internal owner keys while retaining the exact public command."""
    text(command, "command_id", maximum=140)
    return "M7:" + kind + ":" + digest_payload({"command_id": command})


class PostgresMonetaryStockSalesRepository(PostgresStockSalesRepository):
    _source_schema = SOURCE_SCHEMA

    def __init__(self, connection: Any, tenant_id: str, *, workspace_id: str, organization_id: str,
                 legal_entity_id: str, organization_code: str, entity_code: str) -> None:
        super().__init__(connection, tenant_id, workspace_id=workspace_id, organization_id=organization_id,
            legal_entity_id=legal_entity_id, organization_code=organization_code, entity_code=entity_code)
        self.fx = _StockFxOwner(self)

    def _authority_locks(self, actor: PostingActor, operation: str, *, permissions: frozenset[str] | None = None) -> None:
        selected = OPERATION_PERMISSIONS.get(operation, READ) if permissions is None else permissions
        super()._authority_locks(actor, operation, permissions=selected)

    def _permission_union_allowed(self, operation: str, permissions: frozenset[str]) -> bool:
        # Valuation phases share the existing current-authority lock path, but
        # only this fixed owner declares the additional reversal permission.
        if operation == "read":
            declared = {*VALUATION_PERMISSIONS.values(),
                VALUATION_PERMISSIONS["review"] | {"finance_core.reverse"},
                VALUATION_PERMISSIONS["post"] | {"finance_core.reverse"}}
            return permissions in declared
        return (operation in OPERATION_PERMISSIONS and permissions == OPERATION_PERMISSIONS[operation]
                and super()._permission_union_allowed(operation, permissions))

    def _origin(self, identifier: str) -> dict[str, Any] | None:
        values = records(self.connection.execute("""SELECT * FROM reconforge.stock_sales_monetary_origins
            WHERE tenant_id=%s AND stock_order_id=%s""", (self.tenant_id, identifier)))
        return values[0] if values else None

    def _parents(self, row: Mapping[str, Any], *, share: bool = False) -> None:
        customer_sql = ("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR SHARE" if share else
                        "SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE")
        invoice_sql = ("SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR SHARE" if share else
                       "SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE")
        self.connection.execute(customer_sql,
                                (self.tenant_id, row["customer_id"]))
        if row["invoice_id"] is not None:
            self.connection.execute(invoice_sql,
                                    (self.tenant_id, row["invoice_id"]))
        self._order(str(row["id"]), lock=not share, read_lock=share)

    def _actor(self, actor: PostingActor, operation: str, row: Mapping[str, Any] | None = None) -> None:
        self._authority_locks(actor, operation)
        if row is not None:
            source = row.get("source", row)
            policies: tuple[tuple[Mapping[str, Any], int, int], ...] = ((source["monetary_policy"], source["total_minor"],
                         max(source["total_minor"], source["unit_price_minor"], source["net_unit_price_minor"])),)
            origin = self._origin(str(row["id"])) if "id" in row else None
            if origin is not None:
                payload = origin["payload"]
                foreign = payload["equation"]["foreign_gross_minor"]
                local = max(payload["equation"]["functional_gross_minor"], book_carrying(origin))
                policies = ((source["monetary_policy"], foreign, max(foreign, policies[0][2])),
                            (source["functional_policy"], local, local))
            issue = row.get("issue_plan")
            if issue is not None:
                policies += ((source["functional_policy"], issue["total_cost_minor"], issue["total_cost_minor"]),)
            for permission in sorted(OPERATION_PERMISSIONS.get(operation, READ)):
                for policy, effect, exposed in policies:
                    amount = exposed if permission in READ else effect
                    if type(amount) is not int or amount < 0:
                        _fail("evidence_invalid", "Captured monetary exposure must be an exact nonnegative integer.")
                    # A zero L COGS exposure is admitted only for the native
                    # restituted issue contract, never substituted with F money.
                    zero = amount == 0 and issue is not None and issue.get("cost_admission_policy") == "partial-return-restituted-v1"
                    self.ops._actor(actor, permission, {**self.scope, "amount_minor": amount,
                        "currency_precision": policy["precision"]}, mutation=operation != "read", allow_zero_amount=zero)
        if operation != "read":
            self.connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (actor.user_id,))

    def _issue_money(self, row: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
        return row["source"]["functional_policy"]["currency_code"], row["source"]["functional_policy"]

    def _restituted_cost(self, row: Mapping[str, Any], allocations: list[dict[str, Any]]) -> Any:
        return self._one("SELECT reconforge.monetary_stock_zero_cost(%s,%s,%s,%s,%s,%s::jsonb) value",
            (self.tenant_id, row["workspace_id"], row["organization_id"], row["legal_entity_id"], row["item_id"], canonical_json(allocations)))["value"]

    def _issue_authority(self, row: Mapping[str, Any], total: int, cost_snapshot: Any, actor: PostingActor) -> None:
        if type(total) is not int or total < 0 or (total == 0 and cost_snapshot is None):
            _fail("evidence_invalid", "Zero functional issue cost requires its actual owned restitution evidence.")
        issue: dict[str, Any] = {"total_cost_minor": total}
        if cost_snapshot is not None:
            issue["cost_admission_policy"] = "partial-return-restituted-v1"
        self._actor(actor, "prepare-issue", {**row, "issue_plan": issue})

    def _request(self, identifier: str, operation: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        return {**super()._request(identifier, operation, parameters, actor), "protocol_version": 2}

    def _view(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.monetary_stock_public(%s,%s) value", (self.tenant_id, identifier))["value"]

    def _close(self, identifier: str) -> None:
        self.connection.execute("SELECT reconforge.monetary_stock_close(%s,%s)", (self.tenant_id, identifier))

    def create(self, request: StockOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        raw = request.payload()
        identifier = platform_id("STSALE", self.scope["workspace_id"], raw["number"])
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._authority_locks(actor, "create")
            command = self._request(identifier, "create", raw, actor)
            replay = self._replay(command_id, command)
            if replay is not None:
                self._actor(actor, "create", self._order(identifier, read_lock=True))
                return replay
            store = FinancePolicyStore(self.connection, tenant_id=self.tenant_id)
            store.lock_binding(self.scope["workspace_id"])
            masters = self._one("""SELECT i.id item_id,i.uom_id,u.decimal_places quantity_precision,l.id location_id,
                customer.id customer_id,entity.currency_code functional_currency,currency.minor_units functional_precision
                FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
                JOIN reconforge.inventory_locations l ON l.tenant_id=i.tenant_id AND l.location_code=%s AND l.active AND NOT l.allow_negative
                JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id AND w.warehouse_code=%s AND w.active
                JOIN reconforge.legal_entities entity ON entity.tenant_id=w.tenant_id AND entity.id=w.legal_entity_id AND entity.active
                JOIN reconforge.currencies currency ON currency.tenant_id=entity.tenant_id AND currency.code=entity.currency_code AND currency.active
                JOIN reconforge.ar_customers customer ON customer.tenant_id=entity.tenant_id AND customer.legal_entity_id=entity.id
                AND customer.customer_code=%s AND customer.status='Active' AND customer.currency_code=%s
                WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.item_code=%s AND i.active AND i.item_type IN('Stock','Consumable')
                AND i.tracking_mode='None' AND i.inventory_account_id IS NOT NULL AND u.active
                AND(i.organization_id IS NULL OR i.organization_id=%s) AND w.organization_id=%s AND w.legal_entity_id=%s
                AND customer.workspace_id=i.workspace_id AND customer.organization_id=w.organization_id""",
                (raw["location_code"], raw["warehouse_code"], raw["customer_code"], raw["currency_code"], self.tenant_id,
                 self.scope["workspace_id"], raw["item_code"], self.scope["organization_id"], self.scope["organization_id"], self.scope["legal_entity_id"]))
            self.connection.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (self.tenant_id, masters["customer_id"]))
            customer = self.ar.get_customer(masters["customer_id"])
            transaction, context = store.entry({"currency_code": customer["currency_code"], **{
                key: customer[key] for key in ("currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")}})
            functional, functional_context = store.capture(workspace_id=self.scope["workspace_id"], currency_code=masters["functional_currency"],
                minor_units=masters["functional_precision"], actor_label=actor.username)
            if context.registry_manifest.digest != functional_context.registry_manifest.digest:
                _fail("currency_invalid", "Both original currencies require the same captured registry context.")
            payload = {**raw, "schema_version": SOURCE_SCHEMA, "monetary_policy": {
                "currency_code": transaction.currency_code, "precision": transaction.precision, "rounding_policy": transaction.rounding_policy,
                "registry_version": transaction.registry_version, "registry_digest": transaction.registry_digest},
                "functional_policy": {"currency_code": functional.currency_code, "precision": functional.precision,
                    "rounding_policy": functional.rounding_policy, "registry_version": functional.registry_version,
                    "registry_digest": functional.registry_digest},
                "quantity_scaled": quantity_to_scaled(raw["quantity"], masters["quantity_precision"], "Stock order quantity")}
            self._actor(actor, "create", payload)
            self.connection.execute("""INSERT INTO reconforge.stock_sales_orders
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,item_id,uom_id,location_id,number,
                currency_code,quantity_scaled,quantity_precision,total_minor,source,source_digest,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"],
                 masters["customer_id"], masters["item_id"], masters["uom_id"], masters["location_id"], raw["number"], raw["currency_code"],
                 payload["quantity_scaled"], masters["quantity_precision"], raw["total_minor"], canonical_json(payload), digest_payload(payload), actor.user_id))
            return self._remember(self._order(identifier), command_id, command, "Create net-exclusive monetary product order", actor)

    def _next_status(self, row: Mapping[str, Any], operation: str) -> str:
        if type(row["row_version"]) is not int or not 1 <= row["row_version"] < 1024:
            _fail("history_full", "The finite Stock command history is exhausted.")
        if row["status"] in {"Invoiced", "Paid"} and operation == "prepare-collection":
            return "CollectionPrepared"
        return super()._next_status(row, operation)

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str, reason: str,
            parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._authority_locks(actor, operation)
            row = self._order(identifier)
            self._actor(actor, operation, row)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(row["workspace_id"])
            self._parents(row)
            return super().act(identifier, operation, expected_version=expected_version, command_id=command_id,
                               reason=reason, parameters=parameters, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "read")
            row = self._order(identifier)
            self._actor(actor, "read", row)
            self._parents(row, share=True)
            # Keep the full source proof effect-free. The shared _close stays
            # live for commands, retained command replay and native writes.
            self.connection.execute("SELECT reconforge.monetary_stock_source_close(%s,%s)", (self.tenant_id, identifier))
            self._actor(actor, "read", row)
            return self._view(identifier)

    def options(self, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            result = super().options(actor=actor)
            result["accounts"] = records(self.connection.execute("""SELECT a.account_code,a.name,a.account_type,a.chart_id
                FROM reconforge.finance_accounts a JOIN reconforge.finance_charts c ON c.tenant_id=a.tenant_id AND c.id=a.chart_id
                WHERE a.tenant_id=%s AND a.workspace_id=%s AND c.organization_code IN('',%s) AND a.active AND c.active
                AND a.allow_posting AND a.allow_manual_posting AND a.account_type IN('Asset','Income','Expense','Liability')
                ORDER BY a.account_code COLLATE "C",a.id LIMIT 200""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_code"])))
            return result

    def _revenue(self, row: Mapping[str, Any], operation: str, parameters: Mapping[str, Any], actor: PostingActor,
                 command: str, reason: str) -> dict[str, Any]:
        if operation == "prepare-invoice":
            return self.fx.prepare_stock_invoice(row, parameters, command, reason, actor)
        if operation == "prepare-collection":
            return self.fx.prepare_stock_collection(row, parameters, command, reason, actor)
        plan_id = row["collection_plan_id"] if operation in {"review-collection", "collect"} else row["invoice_plan_id"]
        plan = self.fx._peek("plan", plan_id)
        if operation in {"review-invoice", "review-collection"}:
            self.fx.review(plan_id, expected_plan_digest=plan["plan_digest"], reason=reason,
                           command_id=native_child_command("stock-review", command), actor=actor)
            return {}
        result = self.fx.post(plan_id, expected_plan_digest=plan["plan_digest"], reason=reason,
                              command_id=native_child_command("stock-post", command), actor=actor)
        if operation == "invoice":
            return {}
        balance = self._one("SELECT reconforge.monetary_stock_balance(%s,%s) value", (self.tenant_id, row["id"]))["value"]
        return {"receipt_id": result["receipt_id"], "status": "Paid" if balance["transaction_outstanding_minor"] == "0" else "Invoiced"}

    def _history(self, identifier: str) -> MonetaryHistory:
        value = self._one("SELECT reconforge.monetary_stock_history(%s,%s) value", (self.tenant_id, identifier))["value"]
        try:
            source_value = dict(value["source"])
            source_value["transaction_policy"] = FinanceCurrencyPolicy(**source_value["transaction_policy"])
            source_value["functional_policy"] = FinanceCurrencyPolicy(**source_value["functional_policy"])
            source_value["registry_context"] = CurrencyRegistryContext.from_snapshot(source_value.pop("registry_snapshot"))
            source_value["components"] = tuple(MonetaryComponent(**part) for part in source_value["components"])
            source_value["consumptions"] = tuple(MonetaryConsumption(**part) for part in source_value["consumptions"])
            source = MonetaryReturnSource(**source_value)
            events = []
            for row in value["events"]:
                item = dict(row)
                for key in ("before", "after"):
                    state: dict[str, Any] = {field: tuple(values) if type(values) is list else values for field, values in item[key].items()}
                    item[key] = MonetaryPosition(**state)
                item["monetary"] = MonetaryMovement(**item["monetary"])
                item["components"] = tuple(ComponentCut(**part) for part in item["components"])
                item["portions"] = tuple(CostCut(**part) for part in item["portions"])
                item["settlement_rate"] = HistoricalRate(**item["settlement_rate"]) if item["settlement_rate"] is not None else None
                events.append(MonetaryEvent(**item))
            return MonetaryHistory(source, tuple(events))
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancePostingError("stock_monetary_evidence_invalid", "The native ordered monetary source refused.") from exc

    def _valuation_authority(self, identifier: str, actor: PostingActor, operation: str) -> dict[str, Any]:
        self._authority_locks(actor, "read", permissions=frozenset(VALUATION_PERMISSIONS[operation]))
        row = self._order(identifier)
        self._actor(actor, "read", row)
        if operation != "read":
            self.connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (actor.user_id,))
        origin = self._origin(identifier)
        if origin is None:
            _fail("state_conflict", "A governed original foreign recognition is required before a closing valuation.")
        return origin

    def _valuation_public(self, identifier: str, plan_id: str) -> dict[str, Any]:
        origin = self._origin(identifier)
        if origin is None:
            _fail("not_found", "The exact monetary Stock origin is absent.")
        native = self._one("""SELECT plan.payload,plan.phase,review.reviewer_actor_id,link.posted_actor_id,link.posting_effect_id
            FROM reconforge.operational_fx_plans plan LEFT JOIN reconforge.operational_fx_reviews review
            ON(review.tenant_id,review.plan_id)=(plan.tenant_id,plan.id) LEFT JOIN reconforge.operational_fx_links link
            ON(link.tenant_id,link.plan_id)=(plan.tenant_id,plan.id)
            WHERE plan.tenant_id=%s AND plan.id=%s AND plan.source_id=%s AND plan.kind IN('revalue','reverse_revaluation')""",
            (self.tenant_id, plan_id, origin["fx_source_id"]))
        plan = native["payload"]
        original = plan if plan["kind"] == "revalue" else self.fx._peek("plan", plan["equation"]["original_revaluation_id"])
        equation = original["equation"]
        delta = equation["unrealized_fx_minor"]
        source = self.fx._peek("source", origin["fx_source_id"])
        return {"schema_version": "stock-monetary-valuation-v1", "id": plan_id, "source_order_id": identifier,
            "fx_source_id": source["id"], **{key: origin[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "fx_source_digest": source["source_digest"], "origin_digest": origin["source_digest"], "kind": plan["kind"],
            "status": ("Prepared", "Reviewed", "Posted")[native["phase"]], "phase": native["phase"], "plan_digest": plan["plan_digest"],
            **{key: plan[key] for key in ("period_id", "posting_date", "reason")},
            "transaction_policy": source["foreign_policy"], "functional_policy": source["functional_policy"],
            "monetary": {"transaction_outstanding_minor": str(equation["foreign_outstanding_minor"]),
                "functional_historical_outstanding_minor": str(equation["historical_outstanding_minor"]),
                "functional_valued_outstanding_minor": str(equation["valued_outstanding_minor"]),
                "functional_unrealized_gain_minor": str(max(delta, 0)), "functional_unrealized_loss_minor": str(max(-delta, 0)),
                "functional_turnover_minor": str(equation["amount_minor"])},
            "closing_rate": equation["closing_rate"], "unrealized_gain_account_code": equation["unrealized_gain_account_code"],
            "unrealized_loss_account_code": equation["unrealized_loss_account_code"],
            "original_id": original["id"] if plan["kind"] == "reverse_revaluation" else None,
            "entry_id": plan["entry_id"], "validation_digest": plan["validation_digest"], "posting_effect_id": native["posting_effect_id"],
            "preparer_actor_id": plan["preparer_actor_id"], "reviewer_actor_id": native["reviewer_actor_id"], "posted_actor_id": native["posted_actor_id"]}

    def prepare_valuation(self, identifier: str, *, closing_rate: HistoricalRate, unrealized_gain_account_code: str,
                          unrealized_loss_account_code: str, period_id: str, posting_date: str, reason: str,
                          command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.ops._transaction():
            origin = self._valuation_authority(identifier, actor, "prepare")
            result = self.fx.prepare_revaluation(origin["fx_source_id"], closing_rate=closing_rate,
                unrealized_gain_account_code=unrealized_gain_account_code, unrealized_loss_account_code=unrealized_loss_account_code,
                period_id=period_id, posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)
            return self._valuation_public(identifier, result["id"])

    def prepare_valuation_reversal(self, identifier: str, *, original_revaluation_id: str, period_id: str,
                                   posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.ops._transaction():
            origin = self._valuation_authority(identifier, actor, "prepare_reversal")
            result = self.fx.prepare_revaluation_reversal(origin["fx_source_id"], original_revaluation_id=original_revaluation_id,
                period_id=period_id, posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)
            return self._valuation_public(identifier, result["id"])

    def get_valuation(self, identifier: str, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.ops._transaction():
            origin = self._valuation_authority(identifier, actor, "read")
            self._parents(self._order(identifier), share=True)
            self.connection.execute("SELECT id FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s AND source_id=%s FOR SHARE",
                                    (self.tenant_id, plan_id, origin["fx_source_id"]))
            plan = self.fx._peek("plan", plan_id)
            if plan["source_id"] != origin["fx_source_id"] or plan["kind"] not in {"revalue", "reverse_revaluation"}:
                _fail("not_found", "The closing valuation belongs to another monetary source.")
            self.fx._authorize(actor, "finance_core.read", self.fx._peek("source", origin["fx_source_id"]), plan, mutation=False)
            self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, plan_id))
            return self._valuation_public(identifier, plan_id)

    def _valuation_phase(self, identifier: str, plan_id: str, operation: str, *, expected_plan_digest: str,
                         reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.ops._transaction():
            origin = self._valuation_authority(identifier, actor, operation)
            plan = self.fx._peek("plan", plan_id)
            if plan["source_id"] != origin["fx_source_id"] or plan["kind"] not in {"revalue", "reverse_revaluation"}:
                _fail("not_found", "The exact closing plan must belong to this fixed monetary source.")
            if plan["kind"] == "reverse_revaluation":
                self._authority_locks(actor, "read", permissions=frozenset(VALUATION_PERMISSIONS[operation] | {"finance_core.reverse"}))
            getattr(self.fx, operation)(plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)
            return self._valuation_public(identifier, plan_id)

    def review_valuation(self, identifier: str, plan_id: str, *, expected_plan_digest: str, reason: str,
                         command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._valuation_phase(identifier, plan_id, "review", expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post_valuation(self, identifier: str, plan_id: str, *, expected_plan_digest: str, reason: str,
                       command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._valuation_phase(identifier, plan_id, "post", expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)


class _StockFxOwner(PostgresOperationalFxTaxRepository):
    """Reuse FX's native tables/FinancePosting under the fixed Stock parent."""

    _source_schema = FX_SOURCE_SCHEMA

    def __init__(self, stock: PostgresMonetaryStockSalesRepository) -> None:
        super().__init__(stock.connection, stock.tenant_id)
        self.stock = stock

    def _peek(self, table: str, identifier: str) -> dict[str, Any]:
        value = super()._peek(table, identifier)
        source = value if table == "source" else super()._peek("source", value["source_id"])
        if source.get("schema_version") != FX_SOURCE_SCHEMA:
            _fail("protocol_conflict", "The monetary Stock owner cannot admit a legacy FX source.")
        self.stock._order(source["stock_order_id"])
        return value

    def _source(self, source_id: str) -> dict[str, Any]:
        value = self._peek("source", source_id)
        row = self.stock._order(value["stock_order_id"])
        self.stock._parents({**row, "invoice_id": value["invoice_id"]})
        source = records(self.connection.execute("SELECT payload FROM reconforge.operational_fx_sources WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                                (self.tenant_id, source_id)))[0]["payload"]
        if source != value:
            _fail("source_changed", "The immutable monetary source changed during its parent wait.")
        return dict(source)

    def _authorize(self, actor: PostingActor, permission: str, source: Mapping[str, Any],
                   plan: Mapping[str, Any] | None = None, *, mutation: bool = True) -> None:
        valuation = plan
        if plan is not None and plan["kind"] == "reverse_revaluation":
            valuation = self._peek("plan", plan["equation"]["original_revaluation_id"])
            if valuation["kind"] != "revalue" or valuation["source_id"] != source["id"]:
                _fail("evidence_invalid", "The inverse requires its exact original same-source monetary valuation.")
        if valuation is not None and valuation["kind"] == "revalue" and valuation["equation"]["valued_outstanding_minor"] == 0:
            if source.get("schema_version") != FX_SOURCE_SCHEMA or plan is None:
                _fail("evidence_invalid", "Zero closing functional carrying requires the fixed monetary source.")
            super()._authorize(actor, permission, source, mutation=mutation)
            amount = max(exact_minor(plan["amount_minor"], "native valuation journal turnover"),
                         exact_minor(valuation["amount_minor"], "original valuation turnover"),
                         exact_minor(valuation["equation"]["historical_outstanding_minor"], "original monetary carrying", zero=True),
                         exact_minor(valuation["equation"]["valued_outstanding_minor"], "closing monetary carrying", zero=True))
            context = {**{key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                       "amount_minor": amount, "currency_precision": source["functional_policy"]["currency_precision"]}
            self.owner._actor(actor, permission, context, mutation=mutation)
            if mutation and plan["kind"] == "reverse_revaluation":
                self.owner._actor(actor, "finance_core.reverse", context, mutation=True)
            return
        # The existing owner checks each F/L gross and AR context independently.
        # Its positive-plan path is reused verbatim whenever a real L journal exists.
        if plan is None or type(plan["amount_minor"]) is not int or plan["amount_minor"] != 0:
            super()._authorize(actor, permission, source, plan, mutation=mutation)
            return
        if (source.get("schema_version") != FX_SOURCE_SCHEMA or plan["kind"] != "settle"
                or plan["equation"]["monetary_event"]["monetary"]["functional_turnover_minor"] != 0
                or plan["equation"]["lines"] != []):
            _fail("evidence_invalid", "Only an exact zero-turnover monetary collection may omit its functional journal.")
        super()._authorize(actor, permission, source, mutation=mutation)
        self.owner._actor(actor, permission, {**{key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "amount_minor": 0, "currency_precision": source["functional_policy"]["currency_precision"]}, mutation=mutation, allow_zero_amount=True)

    def _state(self, source: Mapping[str, Any]) -> dict[str, Any]:
        state = self.stock._one("SELECT reconforge.monetary_stock_fx_state(%s,%s) value",
                                (self.tenant_id, source["stock_order_id"]))["value"]
        return dict(state)

    def _prepare_valuation(self, source_id: str, *, request: dict[str, Any], command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "finance_core.manage", source)
            digest, replay = self._command(source, "prepare", command_id, actor, request)
            self._period(request["period_id"])
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(source["workspace_id"])
            source = self._source(source_id)
            if replay is not None:
                self._authorize(actor, "finance_core.manage", source, replay)
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            state = self._state(source)
            if not state["recognized"] or state["sequence"] > 200 or request["posting_date"] < state["last_posting_date"]:
                _fail("state_conflict", "A closing valuation requires posted recognition, bounded native history and monotonic accounting dates.")
            origin = self.stock._origin(source["stock_order_id"])
            if origin is None or self.connection.execute("""SELECT 1 FROM reconforge.customer_partial_return_monetary_plans
                WHERE tenant_id=%s AND origin_id=%s AND phase IN(0,1)""", (self.tenant_id, origin["id"])).fetchone():
                _fail("state_conflict", "Complete the pending merchandise correction before valuing its receivable.")
            reversal = None
            if request["kind"] == "revalue":
                if state["active_revaluation_plan_id"] is not None:
                    _fail("state_conflict", "Reverse the exact active native valuation before preparing another.")
                equation = monetary_revaluation_equation(self.stock._history(source["stock_order_id"]), source,
                    closing_rate=HistoricalRate(**request["closing_rate"]), posting_date=request["posting_date"],
                    unrealized_gain_account_code=request["unrealized_gain_account_code"], unrealized_loss_account_code=request["unrealized_loss_account_code"])
            else:
                if request["kind"] != "reverse_revaluation" or state["active_revaluation_plan_id"] != request["original_revaluation_id"]:
                    _fail("state_conflict", "The inverse must close the exact still-active original monetary valuation.")
                original = self._view(request["original_revaluation_id"])
                self._authorize(actor, "finance_core.reverse", source, original)
                equation = reversal_equation(original)
                reversal = original["posting_effect_id"]
            return self._prepare(source, kind=request["kind"], equation=equation, period_id=request["period_id"],
                posting_date=request["posting_date"], reason=request["reason"], sequence=state["sequence"], request=request,
                command_id=command_id, digest=digest, actor=actor, reverses_posting_id=reversal)

    def _admit_journal_presence(self, source: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
        if plan.get("entry_id") is not None:
            return
        if (source.get("schema_version") != FX_SOURCE_SCHEMA or plan.get("schema_version") != "operational-fx-stock-plan-v2"
                or plan.get("kind") != "settle" or plan.get("source_id") != source.get("id")
                or type(plan.get("amount_minor")) is not int or plan["amount_minor"] != 0
                or plan.get("snapshot") is not None or plan.get("validation_digest") is not None):
            _fail("evidence_invalid", "Absent functional journals require the exact fixed monetary collection owner.")
        try:
            equation = plan["equation"]
            if type(equation) is not dict:
                _fail("evidence_invalid", "A closed native collection equation object is required.")
            retained = equation["monetary_event"]
            if type(retained) is not dict or type(retained.get("monetary")) is not dict:
                _fail("evidence_invalid", "A closed original collection event and monetary object are required.")
            if set(equation) != {"foreign_minor", "monetary_event", "lines"} or equation["lines"] != []:
                _fail("evidence_invalid", "A zero-turnover collection cannot retain financial journal lines.")
            if (type(equation["foreign_minor"]) is not int or equation["foreign_minor"] <= 0
                    or type(retained["sequence"]) is not int or retained["kind"] != "Collection"
                    or retained["amount_minor"] != equation["foreign_minor"]
                    or any(type(value) is not int or value != 0 for key, value in retained["monetary"].items() if key.startswith("functional_"))):
                _fail("evidence_invalid", "Zero functional posting retains positive exact transaction cash and every zero functional leg.")
            origin = self.stock._origin(source["stock_order_id"])
            if origin is None or origin["fx_source_id"] != source["id"] or origin["invoice_id"] != source["invoice_id"]:
                _fail("evidence_invalid", "The complete current immutable Stock/AR/FX source must own this zero collection.")
            history = self.stock._history(source["stock_order_id"])
            replay_monetary_history(history)
            sequence = retained["sequence"]
            if 1 <= sequence <= len(history.events):
                expected = history.events[sequence - 1]
                if self.connection.execute("""SELECT 1 FROM reconforge.customer_partial_return_monetary_history
                    WHERE tenant_id=%s AND origin_id=%s AND sequence=%s AND stock_fx_plan_id=%s""",
                    (self.tenant_id, origin["id"], sequence, plan["id"])).fetchone() is None:
                    _fail("evidence_invalid", "A retained zero collection belongs only to its exact original native history member.")
            else:
                if self._state(source)["active_revaluation_plan_id"] is not None:
                    _fail("state_conflict", "Reverse the active closing valuation before a new historical collection.")
                rate = retained["settlement_rate"]
                expected = prepare_monetary_event(history, "Collection", posting_date=plan["posting_date"],
                    amount_minor=equation["foreign_minor"], settlement_rate=HistoricalRate(**rate) if rate is not None else None)
            if canonical_json(asdict(expected)) != canonical_json(retained) or expected.monetary.functional_turnover_minor != 0:
                _fail("evidence_invalid", "The complete zero collection witness must match its exact active or retained monetary prefix.")
        except FinancePostingError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancePostingError("stock_monetary_evidence_invalid", "The zero functional collection evidence refused.") from exc

    def _prepare(self, source: Mapping[str, Any], *, kind: str, equation: dict[str, Any], period_id: str,
                 posting_date: str, reason: str, sequence: int, request: Mapping[str, Any],
                 command_id: str, digest: str, actor: PostingActor, reverses_posting_id: str | None = None) -> dict[str, Any]:
        if equation["lines"]:
            result = super()._prepare(source, kind=kind, equation=equation, period_id=period_id, posting_date=posting_date,
                reason=reason, sequence=sequence, request=request, command_id=command_id, digest=digest, actor=actor,
                reverses_posting_id=reverses_posting_id)
            if self.stock._origin(source["stock_order_id"]) is not None:
                self.connection.execute("SELECT reconforge.monetary_stock_refresh_balance(%s,%s)", (self.tenant_id, source["stock_order_id"]))
            return result
        scope = {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
        if (kind != "settle" or reverses_posting_id is not None
                or self.connection.execute("SELECT 1 FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND source_id=%s AND phase<2",
                    (self.tenant_id, source["id"])).fetchone()):
            _fail("state_conflict", "Only the next owned zero-turnover collection may omit its functional journal.")
        self._authorize(actor, "finance_core.manage", source, {**scope, "kind": kind, "amount_minor": 0, "equation": equation})
        plan = {"schema_version": "operational-fx-stock-plan-v2", "id": "FX1-" + uuid4().hex,
            "source_id": source["id"], **scope, "kind": kind, "sequence": sequence, "period_id": period_id,
            "posting_date": posting_date, "reason": reason, "currency_code": source["functional_policy"]["currency_code"],
            "currency_precision": source["functional_policy"]["currency_precision"], "source_digest": source["source_digest"],
            "entry_id": None, "equation": equation, "amount_minor": 0, "snapshot": None,
            "preparer_actor_id": actor.user_id, "command_request": dict(request)}
        plan.update(plan_digest=digest_payload(plan), validation_digest=None)
        audit, outbox = self.owner._event(plan, "operational_fx_prepared", actor, {"plan_digest": plan["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.operational_fx_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_id,entry_id,sequence,kind,phase,payload,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,NULL,%s,%s,0,%s::jsonb,%s,%s)""", (self.tenant_id, plan["id"], *scope.values(),
            source["id"], sequence, kind, canonical_json(plan), audit, outbox))
        result = self._remember(plan, "prepare", command_id, actor, digest, request)
        self.connection.execute("SELECT reconforge.monetary_stock_refresh_balance(%s,%s)", (self.tenant_id, source["stock_order_id"]))
        return result

    def _receipt_number(self, plan: Mapping[str, Any]) -> str:
        return "FX1-" + str(plan["command_request"]["receipt_number"])

    def _after_posted(self, source: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
        if plan["kind"] == "settle":
            self.connection.execute("SELECT reconforge.monetary_stock_append_collection(%s,%s,%s,%s::jsonb)",
                (self.tenant_id, source["stock_order_id"], plan["id"], canonical_json(plan["equation"]["monetary_event"])))
        self.connection.execute("SELECT reconforge.monetary_stock_refresh_balance(%s,%s)", (self.tenant_id, source["stock_order_id"]))

    def prepare_stock_collection(self, row: Mapping[str, Any], parameters: Mapping[str, Any], command: str,
                                 reason: str, actor: PostingActor) -> dict[str, Any]:
        if set(parameters) != {"receipt_number", "receipt_date", "period_id", "amount_minor", "settlement_rate"}:
            _fail("request_invalid", "Collection preparation requires the exact transaction-currency request.")
        receipt_number = text(parameters["receipt_number"], "receipt number", maximum=60)
        if receipt_number != parameters["receipt_number"]:
            _fail("request_invalid", "Retain the exact canonical native receipt number.")
        origin = self.stock._origin(row["id"])
        if origin is None:
            _fail("source_missing", "The original governed recognition must exist first.")
        source = self._source(origin["fx_source_id"])
        state = self._state(source)
        if not state["recognized"] or state["active_revaluation_plan_id"] is not None or state["sequence"] > 200:
            _fail("state_conflict", "Collection requires recognized original authority and no active closing valuation.")
        if self.connection.execute("SELECT 1 FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s AND origin_id=%s AND phase IN(0,1)",
                                    (self.tenant_id, origin["id"])).fetchone():
            _fail("state_conflict", "Complete the pending merchandise correction before preparing cash.")
        observed = parameters["settlement_rate"]
        rate = HistoricalRate(**observed) if observed is not None else None
        event = prepare_monetary_event(self.stock._history(row["id"]), "Collection", posting_date=parameters["receipt_date"],
                                      amount_minor=parameters["amount_minor"], settlement_rate=rate)
        monetary = event.monetary
        roles = source["request"]
        lines = []
        for account, debit, credit in (
            (roles["cash_account_code"], monetary.functional_cash_minor, 0),
            (roles["receivable_account_code"], 0, monetary.functional_receivable_released_minor),
            (roles["gain_account_code"], 0, monetary.functional_fx_gain_minor),
            (roles["loss_account_code"], monetary.functional_fx_loss_minor, 0),
        ):
            if debit or credit:
                lines.append({"account_code": account, "debit_minor": debit, "credit_minor": credit})
        equation = {"foreign_minor": parameters["amount_minor"], "monetary_event": asdict(event), "lines": lines}
        request = {"kind": "settle", "source_id": source["id"], **dict(parameters), "reason": reason}
        child_command = native_child_command("stock-cash", command)
        digest, replay = self._command(source, "prepare", child_command, actor, request)
        if replay is not None:
            _fail("command_conflict", "Stock command replay must own its exact saved collection acknowledgement.")
        plan = self._prepare(source, kind="settle", equation=equation, period_id=parameters["period_id"],
            posting_date=parameters["receipt_date"], reason=reason, sequence=state["sequence"], request=request,
            command_id=child_command, digest=digest, actor=actor)
        return {"collection_plan_id": plan["id"], "collection_parameters": dict(parameters)}

    def prepare_stock_invoice(self, row: Mapping[str, Any], parameters: Mapping[str, Any], command: str,
                              reason: str, actor: PostingActor) -> dict[str, Any]:
        allowed = {"invoice_number", "invoice_date", "due_date", "journal_code", "period_id", "receivable_account_code",
                   "revenue_account_code", "cash_account_code", "refund_liability_account_code", "gain_account_code", "loss_account_code",
                   "country_code", "transaction_class", "taxes", "original_rate"}
        if set(parameters) != allowed or type(parameters["taxes"]) is not list:
            _fail("request_invalid", "Invoice preparation requires the exact captured monetary declaration.")
        quoted, functional = row["source"]["monetary_policy"], row["source"]["functional_policy"]
        _, context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(_full_policy(quoted))
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(_full_policy(functional))
        rate_value = parameters["original_rate"]
        request = ForeignInvoicePreparation(**self.stock.scope, customer_code=row["source"]["customer_code"],
            invoice_number=parameters["invoice_number"], posting_date=parameters["invoice_date"], due_date=parameters["due_date"],
            period_id=parameters["period_id"], journal_code=parameters["journal_code"], foreign_currency_code=row["currency_code"],
            net_minor=row["total_minor"], original_rate=HistoricalRate(**rate_value) if rate_value is not None else None,
            country_code=parameters["country_code"], transaction_class=parameters["transaction_class"],
            taxes=tuple(TaxComponent(**part) for part in parameters["taxes"]), receivable_account_code=parameters["receivable_account_code"],
            revenue_account_code=parameters["revenue_account_code"], cash_account_code=parameters["cash_account_code"],
            gain_account_code=parameters["gain_account_code"], loss_account_code=parameters["loss_account_code"], reason=reason)
        equation = invoice_equation(request, functional["currency_code"], context, allow_currency_identity=True)
        args = request.payload(allow_currency_identity=True)
        source = {"schema_version": FX_SOURCE_SCHEMA, "id": "FX-" + uuid4().hex, **self.stock.scope,
            **equation, "preparer_actor_id": actor.user_id, "stock_order_id": row["id"], "stock_source_digest": row["source_digest"]}
        # Codes belong in request, while source scope has the same exact three
        # native IDs as FX1; codes are not copied as extra financial source fields.
        source.pop("organization_code")
        source.pop("entity_code")
        self._authorize(actor, "finance_core.manage", source)
        refund = text(parameters["refund_liability_account_code"], "refund liability account")
        if refund in {value for key, value in args.items() if key.endswith("_account_code")} or refund in {part.account_code for part in request.taxes}:
            _fail("account_invalid", "The refund liability role must be distinct from original accounting roles.")
        invoice = self.ar.create_invoice(invoice_number="FX1-" + request.invoice_number, customer_code=request.customer_code,
            invoice_date=request.posting_date, due_date=request.due_date, currency_code=request.foreign_currency_code,
            tax_minor=equation["foreign_tax_minor"], lines=[ReceivableInvoiceLineInput(description=row["source"]["description"],
                quantity=row["source"]["quantity"], unit_price_minor=row["source"]["net_unit_price_minor"],
                tax_minor=equation["foreign_tax_minor"], line_total_minor=row["total_minor"])], workspace=row["workspace_id"],
            organization_code=self.stock.scope["organization_code"], entity_code=self.stock.scope["entity_code"],
            idempotency_key=native_child_command("stock-invoice", command), actor_label=actor.username)
        invoice = self.ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
        source["invoice_id"] = invoice["id"]
        source["source_digest"] = digest_payload(source)
        self.connection.execute("""INSERT INTO reconforge.operational_fx_sources
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,invoice_id,payload) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, source["id"], row["workspace_id"], row["organization_id"], row["legal_entity_id"], invoice["id"], canonical_json(source)))
        fx_request = {"kind": "recognize", **args}
        child_command = native_child_command("stock-invoice", command)
        digest, replay = self._command(source, "prepare", child_command, actor, fx_request)
        if replay is not None:
            _fail("command_conflict", "An atomic new origin cannot reuse a detached FX command.")
        plan = self._prepare(source, kind="recognize", equation={"lines": equation["lines"]}, period_id=request.period_id,
            posting_date=request.posting_date, reason=reason, sequence=0, request=fx_request,
            command_id=child_command, digest=digest, actor=actor)
        # Native birth captures immutable original consumption order, account
        # classifications and reviewed snapshots, binding the actual AR quantity.
        self.connection.execute("SELECT reconforge.monetary_stock_origin_birth(%s,%s,%s,%s,%s::jsonb)",
            (self.tenant_id, row["id"], source["id"], plan["id"], canonical_json({"refund_liability_account_code": refund})))
        return {"invoice_id": invoice["id"], "invoice_plan_id": plan["id"], "invoice_parameters": dict(parameters)}
