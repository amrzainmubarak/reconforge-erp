"""ACID, source-owned partial merchandise credits, refunds and corrections.

The caller supplies the existing scoped PostgreSQL connection and bound human
principal. All writes participate in that transaction. The original sale and
its posted effects are never edited or reused as full-reversal records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, fields
from typing import Any, Literal
from uuid import uuid4

from reconforge.domain.customer_partial_return_commands import (
    CustomerPartialRefundPreparation,
    CustomerPartialReturnPreparation,
    CustomerPartialReversePreparation,
)
from reconforge.domain.customer_partial_return_posting import (
    PartialReturnAccountRoles,
    PartialReturnPostingIntent,
    build_partial_return_posting_contract,
)
from reconforge.domain.customer_partial_return_rounding import (
    ALLOCATION_POLICY,
    RemainingConsumptionPortion,
    RemainingReturnEvent,
    RemainingReturnHistory,
    RemainingReturnValues,
    apply_remaining_return,
    prepare_remaining_return,
    refund_remaining_return,
    remaining_return_balance,
    reverse_remaining_return,
)
from reconforge.domain.customer_partial_return_rounding_posting import build_remaining_posting_contract
from reconforge.domain.customer_partial_returns import (
    ConsumptionPortion,
    OriginalConsumption,
    OriginalPartialReturnSource,
    OriginalPostingEvidence,
    PartialReturnEvent,
    PartialReturnHistory,
    PartialReturnScope,
    _ReturnValues,
    apply_partial_return,
    partial_return_balance,
    prepare_partial_return,
    refund_partial_return,
    reverse_partial_return_event,
)
from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_customer_partial_return_source import map_customer_partial_return_source
from reconforge.infrastructure.postgres_customer_returns import (
    PERMISSIONS,
    READ,
    PostgresCustomerReturnsRepository,
    customer_return_money_context,
)
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import scaled_to_text
from reconforge.utils.money import CurrencyRegistryContext
from reconforge.utils.time import utc_now_text


def _fail(code: str, message: str) -> None:
    raise FinancePostingError("customer_partial_return_" + code, message)


def _source_payload(source: OriginalPartialReturnSource, original: dict[str, Any], collections: list[dict[str, Any]]) -> dict[str, Any]:
    typed = {field.name: getattr(source, field.name) for field in fields(source)
             if field.name not in {"scope", "currency_policy", "registry_context", "original_cogs", "original_revenue", "consumptions"}}
    typed.update(scope=asdict(source.scope), currency_policy=asdict(source.currency_policy),
        original_cogs=asdict(source.original_cogs), original_revenue=asdict(source.original_revenue),
        consumptions=[asdict(row) for row in source.consumptions])
    return {"typed_source": typed, "registry_snapshot": source.registry_context.snapshot(), "original_source": original,
            "original_collections": collections, "fingerprint_payload": source.fingerprint_payload}


def _hydrate_source(payload: Mapping[str, Any]) -> OriginalPartialReturnSource:
    try:
        typed = dict(payload["typed_source"])
        scope = PartialReturnScope(**typed.pop("scope"))
        policy = FinanceCurrencyPolicy(**typed.pop("currency_policy"))
        def evidence(value: dict[str, Any]) -> OriginalPostingEvidence:
            return OriginalPostingEvidence(value["posting_effect_id"], PartialReturnScope(**value["scope"]),
                                            value["snapshot_json"], value["validation_digest"])
        cogs, revenue = evidence(typed.pop("original_cogs")), evidence(typed.pop("original_revenue"))
        consumptions = tuple(OriginalConsumption(**{**row, "scope": PartialReturnScope(**row["scope"])}) for row in typed.pop("consumptions"))
        source = OriginalPartialReturnSource(**typed, scope=scope, currency_policy=policy,
            registry_context=CurrencyRegistryContext.from_snapshot(payload["registry_snapshot"]), original_cogs=cogs,
            original_revenue=revenue, consumptions=consumptions)
        if canonical_json(source.fingerprint_payload) != canonical_json(payload["fingerprint_payload"]):
            _fail("source_invalid", "The original typed source fingerprint basis differs.")
        return source
    except (KeyError, TypeError, ValueError) as exc:
        raise FinancePostingError("customer_partial_return_source_invalid", "Retained original source refused.") from exc


def _hydrate_event(row: dict[str, Any], *, protocol_version: int = 1) -> Any:
    values = row["return_values"]
    if protocol_version == 2:
        if values is not None:
            values = RemainingReturnValues(**{**values, "portions": tuple(RemainingConsumptionPortion(**part) for part in values["portions"])})
        return RemainingReturnEvent(row["kind"], row["sequence"], row["source_fingerprint"], row["previous_history_fingerprint"],
                                   row["amount_minor"], values, row["original_sequence"])
    if values is not None:
        values = _ReturnValues(**{**values, "portions": tuple(ConsumptionPortion(**part) for part in values["portions"])})
    return PartialReturnEvent(row["kind"], row["sequence"], row["source_fingerprint"], row["previous_history_fingerprint"],
                              row["amount_minor"], values, row["original_sequence"])


def _balance(history: Any) -> Any:
    return remaining_return_balance(history) if type(history) is RemainingReturnHistory else partial_return_balance(history)


def _prepare(history: Any, quantity: int) -> Any:
    return prepare_remaining_return(history, quantity) if type(history) is RemainingReturnHistory else prepare_partial_return(history, quantity)


def _refund(history: Any, amount: int) -> Any:
    return refund_remaining_return(history, amount) if type(history) is RemainingReturnHistory else refund_partial_return(history, amount)


def _reverse(history: Any, sequence: int) -> Any:
    return reverse_remaining_return(history, sequence) if type(history) is RemainingReturnHistory else reverse_partial_return_event(history, sequence)


def _apply(history: Any, plan: Any) -> Any:
    return apply_remaining_return(history, plan) if type(history) is RemainingReturnHistory else apply_partial_return(history, plan)


class _CustomerPartialReturnPostingParticipant:
    def __init__(self, owner: PostgresCustomerPartialReturnsRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant: str, entry_id: str) -> bool:
        return self.owner._participant is self and connection is self.owner.connection and tenant == self.owner.tenant_id and entry_id == self.entry_id

    def admits_reversal(self, connection: Any, tenant: str, source_entry: str, effect_id: str, new_number: str) -> bool:
        return (self.owner._participant is self and connection is self.owner.connection and tenant == self.owner.tenant_id
                and (source_entry, effect_id, new_number) == self.owner._reversal_admission)


class PostgresCustomerPartialReturnsRepository:
    def __init__(self, connection: Any, tenant_id: str, *, protocol_version: Literal[1, 2] = 1) -> None:
        if type(protocol_version) is not int or protocol_version not in {1, 2}:
            _fail("protocol_conflict", "A server-fixed partial return protocol is required.")
        self.protocol_version = protocol_version
        self.connection, self.tenant_id = connection, tenant_id
        self.legacy = PostgresCustomerReturnsRepository(connection, tenant_id)
        self.owner = self.legacy.owner
        self._participant: _CustomerPartialReturnPostingParticipant | None = None
        self._reversal_admission: tuple[str, str, str] | None = None

    def _protocol(self, value: Mapping[str, Any], *, mutation: bool) -> None:
        policy = value.get("allocation_policy")
        if "source_payload" in value:
            policy = value["source_payload"].get("allocation_policy")
        version = 1 if policy is None else 2 if policy == ALLOCATION_POLICY else 0
        if not version or (version != self.protocol_version and (mutation or self.protocol_version == 1)):
            _fail("protocol_conflict", "Use the original native source and command protocol without upgrading it.")

    def _one(self, query: str, args: tuple[Any, ...]) -> dict[str, Any]:
        values = records(self.connection.execute(query, args))
        if len(values) != 1:
            _fail("not_found", "One current scoped native source is required.")
        return values[0]

    def _row(self, identifier: str, *, lock: bool = False, read_lock: bool = False) -> dict[str, Any]:
        sql = "SELECT payload,phase FROM reconforge.customer_partial_return_plans WHERE tenant_id=%s AND id=%s"
        sql += " FOR UPDATE" if lock else " FOR SHARE" if read_lock else ""
        row = self._one(sql, (self.tenant_id, text(identifier, "plan_id")))
        result = {**row["payload"], "phase": row["phase"]}
        self._protocol(result, mutation=False)
        return result

    def _source_row(self, source_id: str) -> dict[str, Any]:
        return self._one("SELECT * FROM reconforge.customer_partial_return_sources WHERE tenant_id=%s AND id=%s", (self.tenant_id, source_id))

    def _actor(self, actor: PostingActor, operation: str, context: Mapping[str, Any]) -> None:
        self.legacy._authority_locks(actor, operation, context)
        governed = customer_return_money_context({**context, "operation": "Return"}) if "source_snapshot" in context else dict(context)
        zero_options = {"allow_zero_amount": True} if (
            self.protocol_version == 2 and context.get("schema_version") == "customer-partial-return-v2"
            and context.get("allocation_policy") == ALLOCATION_POLICY
            and context.get("operation") in {"Return", "ReverseReturn"}
            and type(context.get("quantity_scaled")) is int and context["quantity_scaled"] > 0
            and all(type(context.get(key)) is int and context[key] == 0
                    for key in ("amount_minor", "credit_minor", "cogs_restored_minor"))
            # prepare authorizes the validated contract before materializing its
            # empty entries. Persisted lifecycle commands retain that exact [] .
            and context.get("entries", []) == []
        ) else {}
        for permission in sorted(READ):
            self.owner._actor(actor, permission, governed, mutation=operation != "read", **zero_options)
        for permission in sorted(PERMISSIONS.get(operation, READ) - READ):
            self.owner._actor(actor, permission, context, mutation=operation != "read", **zero_options)
        if operation != "read":
            self.connection.execute("SELECT set_config('app.customer_partial_return_actor_id',%s,true)", (actor.user_id,))

    def _governed(self, source: dict[str, Any], scope: Mapping[str, Any]) -> dict[str, Any]:
        return {**scope, "source_snapshot": source, "currency_code": source["invoice"]["currency_code"],
                "currency_precision": source["invoice"]["currency_precision"], "amount_minor": source["stock"]["total_minor"]}

    def _history(self, row: Mapping[str, Any]) -> Any:
        source = _hydrate_source(row["source_payload"])
        events = records(self.connection.execute("SELECT payload FROM reconforge.customer_partial_return_history WHERE tenant_id=%s AND source_id=%s ORDER BY sequence",
                                                (self.tenant_id, row["id"])))
        version = 2 if row["source_payload"].get("allocation_policy") == ALLOCATION_POLICY else 1
        history_type = RemainingReturnHistory if version == 2 else PartialReturnHistory
        history = history_type(source, tuple(_hydrate_event(event["payload"], protocol_version=version) for event in events))
        _balance(history)
        return history

    def _command(self, context: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        request_body: dict[str, Any] = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        if self.protocol_version == 2:
            request_body["protocol_version"] = 2
        digest = digest_payload(request_body)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, context["workspace_id"], "customer-partial-returns", command_id]),))
        rows = records(self.connection.execute("SELECT * FROM reconforge.customer_partial_return_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                              (self.tenant_id, context["workspace_id"], command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            _fail("command_conflict", "Command identifies another exact request or actor.")
        self._protocol(self._row(row["plan_id"]), mutation=True)
        phase = "prepare" if operation.startswith("prepare") else operation
        self._actor(actor, phase, self._row(row["plan_id"]))
        self._actor(actor, phase, self._row(row["plan_id"], read_lock=True))
        self.connection.execute("SELECT reconforge.customer_partial_return_close(%s,%s)", (self.tenant_id, row["plan_id"]))
        return digest, row["response_json"]

    def _view(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.customer_partial_return_public(%s,%s) value", (self.tenant_id, identifier))["value"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(plan["id"])
        request_body: dict[str, Any] = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        if self.protocol_version == 2:
            request_body["protocol_version"] = 2
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_commands
            (tenant_id,workspace_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""", (self.tenant_id, plan["workspace_id"], plan["id"], operation,
            command_id, actor.user_id, digest, canonical_json(request_body), canonical_json(result)))
        return result

    def _native_source(self, source_order_id: str) -> dict[str, Any]:
        row = self._one("SELECT reconforge.customer_partial_return_native_source(%s,%s) value", (self.tenant_id, source_order_id))
        if row["value"] is None:
            _fail("source_invalid", "Complete original native source membership is required.")
        return row["value"]

    def _source_locks(self, source_order_id: str) -> dict[str, Any]:
        source = self._native_source(source_order_id)
        stock = source["stock"]
        self.connection.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, stock["customer_id"]))
        self.connection.execute("SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, stock["invoice_id"]))
        self.connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, source_order_id))
        return self._native_source(source_order_id)

    def _locks(self, plan: Mapping[str, Any]) -> None:
        self.owner.posting._period(plan["period_id"], plan["workspace_id"], plan["posting_date"])
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(plan["workspace_id"])
        self._source_locks(plan["source_order_id"])
        self._row(plan["id"], lock=True)
        if plan["operation"] in {"Return", "ReverseReturn"}:
            source = self._source_row(plan["source_id"])
            stock = source["source_payload"]["original_source"]["stock"]
            for key in sorted({f"{stock['workspace_id']}|{stock['legal_entity_id']}|{stock['location_id']}|{stock['item_id']}|",
                               f"{stock['legal_entity_id']}|{stock['item_id']}|"}):
                self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
            for layer_id in sorted({part["cost_layer_id"] for part in plan["domain_plan"]["portions"]}):
                self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (layer_id,))
                self.connection.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, layer_id))
        for entry in sorted(plan["entries"], key=lambda value: value["entry_id"]):
            self.connection.execute("SELECT id FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, entry["entry_id"]))

    def _roles(self, source: OriginalPartialReturnSource, args: Mapping[str, Any]) -> tuple[PartialReturnAccountRoles, dict[str, Any]]:
        ar, revenue = source.original_revenue.snapshot()["lines"]
        cogs, inventory = source.original_cogs.snapshot()["lines"]
        # Account selection is chart-owned, while journals and dimensions of
        # merchandise effects remain those of the immutable original entries.
        native = self._one("""SELECT l.id liability,l.account_type liability_type,c.id cash,j.id journal
            FROM reconforge.finance_journals j JOIN reconforge.finance_accounts l ON(l.tenant_id,l.chart_id)=(j.tenant_id,j.chart_id)
            JOIN reconforge.finance_accounts c ON(c.tenant_id,c.chart_id)=(j.tenant_id,j.chart_id)
            WHERE j.tenant_id=%s AND j.workspace_id=%s AND j.organization_code=%s AND j.journal_code=%s
            AND l.account_code=%s AND c.account_code=%s AND j.active AND l.active AND l.allow_posting AND c.active AND c.allow_posting
            AND l.account_type='Liability' AND l.normal_balance='Credit' AND c.account_type='Asset' AND c.normal_balance='Debit'
            AND j.currency_code=%s""", (self.tenant_id, args["workspace_id"], args["organization_code"], args["journal_code"],
                                      args["refund_liability_account_code"], args["cash_account_code"], source.currency_policy.currency_code))
        roles = PartialReturnAccountRoles(source.scope, source.fingerprint, source.currency_policy, ar["account_id"], revenue["account_id"],
            inventory["account_id"], cogs["account_id"], native["liability"], native["liability_type"])
        return roles, native

    def _new_source(self, original: dict[str, Any], args: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        mapped = map_customer_partial_return_source(self.connection, self.tenant_id, original)
        source = mapped.source
        roles, accounts = self._roles(source, args)
        collections = mapped.collection_evidence()
        cash_dimensions: dict[str, str] = {}
        for observation in collections:
            cash = observation["posting_effect"]["snapshot_json"]["lines"][0]
            if cash["account_id"] != accounts["cash"]:
                _fail("cash_invalid", "Refund cash must be the exact original collected cash account.")
            cash_dimensions = cash["dimensions"]
        payload = _source_payload(source, mapped.original_source(), collections)
        payload.update(account_roles=roles.payload(), cash_dimensions=cash_dimensions, cash_journal_id=accounts["journal"],
                       journal_code=args["journal_code"], cash_account_code=args["cash_account_code"],
                       refund_liability_account_code=args["refund_liability_account_code"])
        if self.protocol_version == 2:
            payload["allocation_policy"] = ALLOCATION_POLICY
        identifier = "CRS2-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_sources
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_order_id,invoice_id,customer_id,item_id,location_id,uom_id,
             source_fingerprint,source_payload,initial_collected_minor,gross_minor,original_quantity_scaled,quantity_precision,
             original_cogs_effect_id,original_revenue_effect_id,original_valuation_document_id,refund_liability_account_id,cash_account_id,
             created_actor_id,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, identifier, source.scope.workspace_id, source.scope.organization_id, source.scope.legal_entity_id,
             source.source_order_id, source.invoice_id, original["stock"]["customer_id"], source.scope.item_id, source.scope.location_id,
             source.scope.uom_id, source.fingerprint, canonical_json(payload), source.collected_minor, source.gross_minor, source.quantity_scaled,
             source.quantity_precision, source.original_cogs.posting_effect_id, source.original_revenue.posting_effect_id, source.valuation_document_id,
             accounts["liability"], accounts["cash"], actor.user_id, source.currency_policy.currency_code, source.currency_policy.precision,
             source.currency_policy.rounding_policy, source.currency_policy.registry_version, source.currency_policy.registry_digest))
        self.connection.execute("UPDATE reconforge.ar_invoices SET customer_partial_return_source_id=%s WHERE tenant_id=%s AND id=%s",
                                (identifier, self.tenant_id, source.invoice_id))
        return self._source_row(identifier)

    def _draft(self, identifier: str, purpose: str, args: Mapping[str, Any], journal: str, lines: list[dict[str, Any]], actor: PostingActor) -> dict[str, Any]:
        entry_id, now = platform_id("GLE", args["workspace_id"], identifier.upper()), utc_now_text()
        total = sum(line["debit_minor"] for line in lines)
        self.connection.execute("""INSERT INTO reconforge.finance_entries
            (tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,posting_date,description,
             external_reference,source_type,status,currency_code,total_debit_minor,total_credit_minor,created_by,
             currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,preparer_actor_id,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Manual','Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, entry_id, args["workspace_id"], journal, args["organization_code"], args["entity_code"], args["period_id"],
             identifier.upper(), args["posting_date"], args["reason"], args["id"], args["currency_code"], total, total, actor.username,
             args["currency_precision"], args["currency_rounding_policy"], args["currency_registry_version"], args["currency_registry_digest"], actor.user_id, now, now))
        for number, line in enumerate(lines, 1):
            line_id = platform_id("GLL", entry_id, number)
            self.connection.execute("""INSERT INTO reconforge.finance_entry_lines
                (tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, line_id, entry_id, number, line["account_id"], args["reason"], line["debit_minor"], line["credit_minor"], args["currency_code"]))
            for dimension, value in line["dimensions"].items():
                self.connection.execute("INSERT INTO reconforge.finance_entry_line_dimensions(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)",
                                        (self.tenant_id, line_id, dimension, value))
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
        return {"entry_id": entry_id, "purpose": purpose, "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "original_effect_id": None}

    def _save(self, payload: dict[str, Any], actor: PostingActor) -> None:
        payload["preparer_actor_id"] = actor.user_id
        payload["plan_digest"] = digest_payload(payload)
        audit, outbox = self.owner._event(payload, "customer_partial_return_prepared", actor, {"plan_digest": payload["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_plans
            (tenant_id,id,source_id,workspace_id,organization_id,legal_entity_id,source_order_id,invoice_id,original_id,operation,
             amount_minor,quantity_scaled,credit_minor,cogs_restored_minor,receivable_released_minor,refund_entitlement_delta_minor,
             expected_history_version,plan_digest,payload,preparer_actor_id,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
            (self.tenant_id, payload["id"], payload["source_id"], payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"],
             payload["source_order_id"], payload["invoice_id"], payload.get("original_id"), payload["operation"], payload["amount_minor"],
             payload["quantity_scaled"], payload["credit_minor"], payload["cogs_restored_minor"], payload["receivable_released_minor"],
             payload["refund_entitlement_delta_minor"], payload["expected_history_version"], payload["plan_digest"], canonical_json(payload), actor.user_id, audit, outbox))

    def _basis(self, row: Mapping[str, Any], args: Mapping[str, Any], operation: str, identifier: str) -> dict[str, Any]:
        original = row["source_payload"]["original_source"]
        return {**args, **({"allocation_policy": ALLOCATION_POLICY} if self.protocol_version == 2 else {}),
                "schema_version": "customer-partial-return-v2" if self.protocol_version == 2 else "customer-partial-return-v1", "id": identifier, "operation": operation,
                "source_id": row["id"], "source_order_id": row["source_order_id"], "invoice_id": row["invoice_id"],
                **{key: row[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "currency_code", "currency_precision",
                    "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "quantity_precision")},
                "source_snapshot": original, "original_id": None, "request": dict(args)}

    def _available(self, row: Mapping[str, Any], expected: int) -> Any:
        self._protocol(row, mutation=True)
        history = self._history(row)
        if _balance(history).version != expected:
            _fail("state_conflict", "Reload the exact current source history before preparing an effect.")
        if self.connection.execute("SELECT 1 FROM reconforge.customer_partial_return_plans WHERE tenant_id=%s AND source_id=%s AND phase IN(0,1)", (self.tenant_id, row["id"])).fetchone():
            _fail("state_conflict", "Complete or cancel the pending partial source operation first.")
        if self.connection.execute("SELECT 1 FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND source_id=%s AND phase IN(0,1)", (self.tenant_id, row["invoice_id"])).fetchone():
            _fail("state_conflict", "Complete the pending original cash operation first.")
        return history

    def prepare(self, request: CustomerPartialReturnPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            original = self._native_source(request.source_order_id)
            self._actor(actor, "prepare", self._governed(original, args))
            digest, replay = self._command(args, "prepare", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, request.workspace_id, request.posting_date)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(request.workspace_id)
            original = self._source_locks(request.source_order_id)
            if any(original["stock"][key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                _fail("scope_denied", "The original delivery is outside the selected hierarchy.")
            if request.posting_date < original["invoice"]["invoice_date"]:
                _fail("date_invalid", "A correction cannot precede its original invoice.")
            existing = records(self.connection.execute("SELECT * FROM reconforge.customer_partial_return_sources WHERE tenant_id=%s AND source_order_id=%s", (self.tenant_id, request.source_order_id)))
            row = existing[0] if existing else self._new_source(original, args, actor)
            history = self._available(row, request.expected_history_version)
            source = history.source
            roles, _accounts = self._roles(source, args)
            if roles.refund_liability_account_id != row["refund_liability_account_id"] or _accounts["cash"] != row["cash_account_id"]:
                _fail("accounts_changed", "Use the retained source liability and original cash accounts.")
            selected = _prepare(history, request.quantity_scaled)
            builder = build_remaining_posting_contract if self.protocol_version == 2 else build_partial_return_posting_contract
            contract = builder(selected, roles=roles,
                intent=PartialReturnPostingIntent(request.period_id, request.posting_date, request.reason))
            payload = self._basis(row, args, "Return", "CR2-" + uuid4().hex)
            payload.update(quantity_scaled=selected.quantity_scaled, credit_minor=selected.credit_minor, cogs_restored_minor=selected.cogs_restored_minor,
                receivable_released_minor=selected.receivable_released_minor, refund_entitlement_delta_minor=selected.refund_entitlement_delta_minor,
                amount_minor=selected.credit_minor+selected.cogs_restored_minor, domain_plan=selected.payload(), posting_contract=contract.payload(),
                movement_id=platform_id("MOV", request.workspace_id, payload["id"].upper()))
            self._actor(actor, "prepare", payload)
            payload["entries"] = [self._draft(payload["id"] + suffix, template["purpose"], payload, template["journal_id"], template["lines"], actor)
                                  for template in contract.payload()["templates"]
                                  for suffix in ["-R" if template["purpose"] == "RevenueCredit" else "-C"]]
            self._save(payload, actor)
            return self._remember(payload, "prepare", command_id, actor, digest, args)

    def prepare_refund(self, request: CustomerPartialRefundPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            parent = self._row(request.return_id)
            self._protocol(parent, mutation=True)
            self._actor(actor, "prepare", parent)
            digest, replay = self._command(parent, "prepare_refund", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, parent["workspace_id"], request.posting_date)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(parent["workspace_id"])
            self._source_locks(parent["source_order_id"])
            parent = self._row(request.return_id, lock=True)
            if parent["operation"] != "Return" or parent["phase"] != 2 or request.posting_date < parent["posting_date"]:
                _fail("refund_invalid", "Refund needs a posted source credit and a later or equal business date.")
            row = self._source_row(parent["source_id"])
            history = self._available(row, request.expected_history_version)
            _refund(history, request.amount_minor)
            payload = self._basis(row, {**{key: parent[key] for key in ("organization_code", "entity_code", "journal_code")}, **args}, "Refund", "CRF2-" + uuid4().hex)
            payload.update(request=args, original_id=parent["id"], amount_minor=request.amount_minor, quantity_scaled=0, credit_minor=0,
                cogs_restored_minor=0, receivable_released_minor=0, refund_entitlement_delta_minor=0,
                cash_dimensions=row["source_payload"]["cash_dimensions"])
            ar = history.source.original_revenue.snapshot()["lines"][0]
            lines = [{"account_id": row["refund_liability_account_id"], "debit_minor": request.amount_minor, "credit_minor": 0, "dimensions": ar["dimensions"]},
                     {"account_id": row["cash_account_id"], "debit_minor": 0, "credit_minor": request.amount_minor, "dimensions": payload["cash_dimensions"]}]
            self._actor(actor, "prepare", payload)
            payload["entries"] = [self._draft(payload["id"], "Refund", payload, row["source_payload"]["cash_journal_id"], lines, actor)]
            self._save(payload, actor)
            return self._remember(payload, "prepare_refund", command_id, actor, digest, args)

    def prepare_reversal(self, request: CustomerPartialReversePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            parent = self._row(request.original_id)
            self._protocol(parent, mutation=True)
            self._actor(actor, "prepare", parent)
            digest, replay = self._command(parent, "prepare_reversal", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, parent["workspace_id"], request.posting_date)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(parent["workspace_id"])
            self._source_locks(parent["source_order_id"])
            parent = self._row(request.original_id, lock=True)
            if parent["phase"] != 2 or parent["operation"] not in {"Return", "Refund"} or request.posting_date < parent["posting_date"]:
                _fail("reversal_invalid", "Only a posted owned credit or refund can receive a governed correction.")
            row = self._source_row(parent["source_id"])
            history = self._available(row, request.expected_history_version)
            event = self._one("SELECT sequence FROM reconforge.customer_partial_return_history WHERE tenant_id=%s AND source_id=%s AND plan_id=%s", (self.tenant_id, row["id"], parent["id"]))
            _reverse(history, event["sequence"])
            payload = self._basis(row, {**{key: parent[key] for key in ("organization_code", "entity_code", "journal_code")}, **args}, "Reverse" + parent["operation"], ("CR2R-" if parent["operation"] == "Return" else "CRF2R-") + uuid4().hex)
            payload.update(request=args, original_id=parent["id"], original_sequence=event["sequence"],
                           **{key: parent[key] for key in ("amount_minor", "quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor")})
            if parent["operation"] == "Return":
                payload.update(domain_plan=parent["domain_plan"], movement_id=platform_id("MOV", row["workspace_id"], payload["id"].upper()))
                self._reversal_layers(payload)
            entries = []
            for number, part in enumerate(parent["entries"]):
                effect = self._one("SELECT id FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND entry_id=%s", (self.tenant_id, part["entry_id"]))
                new_number = payload["id"].upper() + ("-C" if part["purpose"] == "CostRestoration" else "-R")
                self._participant = _CustomerPartialReturnPostingParticipant(self, part["entry_id"])
                self._reversal_admission = (part["entry_id"], effect["id"], new_number)
                try:
                    inverse = self.owner.posting.prepare_reversal(effect["id"], command_id="CR2:" + command_id + ":" + str(number),
                        entry_number=new_number, period_id=request.period_id, posting_date=request.posting_date, reason=request.reason,
                        actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                    self._reversal_admission = None
                snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, inverse["entry_id"]))
                entries.append({"entry_id": inverse["entry_id"], "purpose": "Reverse" + part["purpose"], "snapshot": snapshot,
                                "validation_digest": validation_digest(snapshot), "original_effect_id": effect["id"]})
            payload["entries"] = entries
            self._save(payload, actor)
            return self._remember(payload, "prepare_reversal", command_id, actor, digest, args)

    def _reversal_layers(self, plan: Mapping[str, Any]) -> None:
        for part in sorted(plan["domain_plan"]["portions"], key=lambda item: item["cost_layer_id"]):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (part["cost_layer_id"],))
            layer = self._one("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, part["cost_layer_id"]))
            if layer["remaining_quantity_scaled"] < part["quantity_scaled"] or layer["remaining_value_minor"] < part["value_minor"]:
                _fail("reversal_dependency", "Restored original cost portions have already been consumed.")
            witness = self._one("""SELECT r.consumption_count_at_restore,
                (SELECT count(*) FROM reconforge.inventory_layer_consumptions x WHERE x.tenant_id=r.tenant_id AND x.cost_layer_id=r.cost_layer_id) current_count
                FROM reconforge.customer_partial_return_restorations r
                WHERE r.tenant_id=%s AND r.plan_id=%s AND r.position=%s AND r.cost_layer_id=%s AND r.direction=1""",
                (self.tenant_id, plan["original_id"], part["position"], part["cost_layer_id"]))
            if witness["consumption_count_at_restore"] != witness["current_count"]:
                _fail("reversal_dependency", "A later native FIFO consumption follows the restored original layer.")

    def _current(self, plan: Mapping[str, Any]) -> Any:
        self._protocol(plan, mutation=True)
        row = self._source_row(plan["source_id"])
        self.connection.execute("SELECT reconforge.customer_partial_return_source_close(%s,%s)", (self.tenant_id, row["id"]))
        history = self._history(row)
        if _balance(history).version != plan["expected_history_version"]:
            _fail("state_conflict", "The governed source history changed after preparation.")
        if plan["operation"] == "Return":
            selected = _prepare(history, plan["quantity_scaled"])
            if canonical_json(selected.payload()) != canonical_json(plan["domain_plan"]):
                _fail("source_changed", "The exact original FIFO or settlement basis changed.")
        elif plan["operation"] == "Refund":
            _refund(history, plan["amount_minor"])
        else:
            _reverse(history, plan["original_sequence"])
            if plan["operation"] == "ReverseReturn":
                self._reversal_layers(plan)
        return history

    def _phase_args(self, plan: Mapping[str, Any], expected: str, reason: str) -> dict[str, Any]:
        if expected != plan["plan_digest"]:
            _fail("state_conflict", "Expected immutable plan digest differs.")
        return {"plan_id": plan["id"], "expected_plan_digest": expected, "reason": text(reason, "reason", maximum=500)}

    def _lifecycle(self, plan: Mapping[str, Any], operation: str, actor: PostingActor, reason: str, effects: list[str] | None = None) -> None:
        metadata = {"plan_digest": plan["plan_digest"], "reason": reason, "effects": effects or []}
        audit, outbox = self.owner._event(plan, "customer_partial_return_" + operation, actor, metadata)
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_events
            (tenant_id,plan_id,operation,actor_id,reason,effects,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            (self.tenant_id, plan["id"], operation, actor.user_id, reason, canonical_json(effects or []), audit, outbox))
        self.connection.execute("UPDATE reconforge.customer_partial_return_plans SET phase=%s WHERE tenant_id=%s AND id=%s",
                                ({"review": 1, "post": 2, "cancel": 3}[operation], self.tenant_id, plan["id"]))

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "review", plan)
            self._protocol(plan, mutation=True)
            args = self._phase_args(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "review", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "review", plan)
            if plan["phase"] != 0 or actor.user_id == plan["preparer_actor_id"]:
                _fail("review_denied", "Review requires an independent human over a Prepared plan.")
            self._current(plan)
            for part in sorted(plan["entries"], key=lambda value: value["entry_id"]):
                self.owner.finance.validate_entry(part["entry_id"], reason=reason, actor_label=actor.username)
            self._lifecycle(plan, "review", actor, reason)
            return self._remember(plan, "review", command_id, actor, digest, args)

    def _history_append(self, row: Mapping[str, Any], plan: Mapping[str, Any], history: Any) -> None:
        if plan["operation"] == "Return":
            result = _apply(history, _prepare(history, plan["quantity_scaled"]))
        elif plan["operation"] == "Refund":
            result = _refund(history, plan["amount_minor"])
        else:
            result = _reverse(history, plan["original_sequence"])
        event = result.events[-1]
        wire = asdict(event)
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_history
            (tenant_id,source_id,sequence,kind,plan_id,amount_minor,quantity_scaled,credit_minor,cogs_minor,payload,previous_digest,event_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            (self.tenant_id, row["id"], event.sequence, event.kind, plan["id"], event.amount_minor, plan["quantity_scaled"], plan["credit_minor"],
             plan["cogs_restored_minor"], canonical_json(wire), event.previous_history_fingerprint, _balance(result).history_fingerprint))

    def _physical(self, plan: Mapping[str, Any], actor: PostingActor, reason: str) -> None:
        row = self._source_row(plan["source_id"])
        stock = row["source_payload"]["original_source"]["stock"]
        location = self._one("""SELECT l.location_code,w.warehouse_code FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w
            ON(w.tenant_id,w.id)=(l.tenant_id,l.warehouse_id) WHERE l.tenant_id=%s AND l.id=%s""", (self.tenant_id, row["location_id"]))
        maker = self._one("SELECT username FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan["preparer_actor_id"]))["username"]
        inventory = PostgresInventoryCoreRepository(self.connection, self.tenant_id)
        return_operation = plan["operation"] == "Return"
        movement = inventory.create_movement(movement_number=plan["id"].upper(), movement_type="Receipt" if return_operation else "Delivery",
            organization_code=plan["organization_code"], entity_code=plan["entity_code"], period_id=plan["period_id"], movement_date=plan["posting_date"],
            description=plan["reason"], source_reference=plan["id"], source_type="Generated", workspace=plan["workspace_id"], actor_label=maker,
            lines=[{"item_code": stock["source"]["item_code"], "quantity": scaled_to_text(plan["quantity_scaled"], row["quantity_precision"]),
                    "to_location" if return_operation else "from_location": location["warehouse_code"] + "/" + location["location_code"]}])
        if movement["id"] != plan["movement_id"]:
            _fail("evidence_invalid", "The native original-scope movement identity differs.")
        inventory.post_movement(movement["id"], reason=reason, actor_label=actor.username)

    def _restorations(self, plan: Mapping[str, Any], effects: list[str]) -> None:
        row = self._source_row(plan["source_id"])
        direction = 1 if plan["operation"] == "Return" else -1
        cost_effects = [effect for entry, effect in zip(plan["entries"], effects, strict=True)
                        if entry["purpose"] in {"CostRestoration", "ReverseCostRestoration"}]
        correction_effect = cost_effects[0] if cost_effects else None
        for part in plan["domain_plan"]["portions"]:
            self.connection.execute("""INSERT INTO reconforge.customer_partial_return_restorations
                (tenant_id,source_id,plan_id,position,original_consumption_id,original_valuation_line_id,cost_layer_id,offset_quantity_scaled,
                 quantity_scaled,value_minor,direction,physical_movement_id,original_cogs_effect_id,correction_effect_id,original_restoration_plan_id,consumption_count_at_restore)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                 (SELECT count(*) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s AND cost_layer_id=%s))""",
                (self.tenant_id, row["id"], plan["id"], part["position"], part["original_consumption_id"], part["original_valuation_line_id"],
                 part["cost_layer_id"], part["offset_quantity_scaled"], part["quantity_scaled"], part["value_minor"], direction,
                 plan["movement_id"], row["original_cogs_effect_id"], correction_effect, None if direction == 1 else plan["original_id"], self.tenant_id, part["cost_layer_id"]))
            if plan.get("allocation_policy") == ALLOCATION_POLICY:
                self.connection.execute("""INSERT INTO reconforge.customer_partial_return_allocation_witnesses
                    (tenant_id,plan_id,position,before_quantity_scaled,before_value_minor) VALUES(%s,%s,%s,%s,%s)""",
                    (self.tenant_id, plan["id"], part["position"], part["before_quantity_scaled"], part["before_value_minor"]))
            self.connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+%s,
                remaining_value_minor=remaining_value_minor+%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                (direction*part["quantity_scaled"], direction*part["value_minor"], self.tenant_id, part["cost_layer_id"]))

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "post", plan)
            self._protocol(plan, mutation=True)
            args = self._phase_args(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "post", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "post", plan)
            reviewer = self._one("SELECT actor_id FROM reconforge.customer_partial_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'", (self.tenant_id, plan_id))["actor_id"]
            if plan["phase"] != 1 or actor.user_id in {plan["preparer_actor_id"], reviewer}:
                _fail("post_denied", "Posting requires a third independent human and exact review.")
            history = self._current(plan)
            if plan["operation"] in {"Return", "ReverseReturn"}:
                self._physical(plan, actor, reason)
            effects = []
            for index, part in enumerate(plan["entries"]):
                self._participant = _CustomerPartialReturnPostingParticipant(self, part["entry_id"])
                try:
                    effect = self.owner.posting.post(part["entry_id"], command_id="CR2:" + command_id + ":" + str(index),
                        expected_validation_digest=part["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                effects.append(effect["id"])
            if plan["operation"] in {"Return", "ReverseReturn"}:
                self._restorations(plan, effects)
            row = self._source_row(plan["source_id"])
            self._lifecycle(plan, "post", actor, reason, effects)
            self._history_append(row, plan, history)
            self.connection.execute("SELECT reconforge.customer_partial_return_settle_invoice(%s,%s)", (self.tenant_id, row["id"]))
            return self._remember(plan, "post", command_id, actor, digest, args)

    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "cancel", plan)
            self._protocol(plan, mutation=True)
            args = self._phase_args(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "cancel", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "cancel", plan)
            reviewers = records(self.connection.execute("SELECT actor_id FROM reconforge.customer_partial_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'", (self.tenant_id, plan_id)))
            if plan["phase"] not in {0, 1} or actor.user_id in {plan["preparer_actor_id"], *(row["actor_id"] for row in reviewers)}:
                _fail("cancel_denied", "Cancellation requires independent authority and an unposted original plan.")
            for part in sorted(plan["entries"], key=lambda value: value["entry_id"]):
                entry = posting_entry(self.connection, self.tenant_id, part["entry_id"])
                if entry["status"] == "Draft":
                    self.owner.finance.validate_entry(part["entry_id"], reason=reason, actor_label=actor.username)
                self.owner.finance.void_entry(part["entry_id"], reason=reason, actor_label=actor.username)
            self._lifecycle(plan, "cancel", actor, reason)
            return self._remember(plan, "cancel", command_id, actor, digest, args)

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "read", plan)
            plan = self._row(plan_id, read_lock=True)
            self._actor(actor, "read", plan)
            self.connection.execute("SELECT reconforge.customer_partial_return_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def list_plans(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            self._actor(actor, "read", scope)
            rows = records(self.connection.execute("SELECT id FROM reconforge.customer_partial_return_plans WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s "
                    "AND(%s=2 OR NOT(payload ? 'allocation_policy')) ORDER BY id COLLATE \"C\" LIMIT 200",
                                                   (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], self.protocol_version)))
            return {"plans": [self.get(row["id"], actor=actor) for row in rows]}

    def balance(self, source_order_id: str, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            original = self._native_source(source_order_id)
            self._actor(actor, "read", self._governed(original, scope))
            # SHARE source locks retain a coherent view without serializing
            # read-only balances behind all financial writers unnecessarily.
            self.connection.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR SHARE", (self.tenant_id, original["stock"]["customer_id"]))
            self.connection.execute("SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR SHARE", (self.tenant_id, original["invoice"]["id"]))
            self.connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s FOR SHARE", (self.tenant_id, source_order_id))
            original = self._native_source(source_order_id)
            self._actor(actor, "read", self._governed(original, scope))
            rows = records(self.connection.execute("SELECT * FROM reconforge.customer_partial_return_sources WHERE tenant_id=%s AND source_order_id=%s", (self.tenant_id, source_order_id)))
            if rows:
                self._protocol(rows[0], mutation=False)
                self.connection.execute("SELECT reconforge.customer_partial_return_source_close(%s,%s)", (self.tenant_id, rows[0]["id"]))
                return self._one("SELECT reconforge.customer_partial_return_balance(%s,%s) value", (self.tenant_id, rows[0]["id"]))["value"]
            source = map_customer_partial_return_source(self.connection, self.tenant_id, original).source
            balance = _balance(RemainingReturnHistory(source) if self.protocol_version == 2 else PartialReturnHistory(source))
            return {**({"schema_version": "customer-partial-return-balance-v2", "allocation_policy": ALLOCATION_POLICY}
                      if self.protocol_version == 2 else {}), "source_id": None, "source_order_id": source_order_id, **{key: getattr(source.scope, key) for key in ("workspace_id", "organization_id", "legal_entity_id")},
                    "source_fingerprint": source.fingerprint, "history_fingerprint": balance.history_fingerprint, "history_version": 0,
                    "gross_minor": source.gross_minor, "collected_minor": source.collected_minor, "credited_minor": 0,
                    "returned_quantity_scaled": 0, "remaining_quantity_scaled": source.quantity_scaled, "quantity_precision": source.quantity_precision,
                    "refund_entitlement_minor": 0, "refunded_minor": 0, "refund_due_minor": 0, "outstanding_minor": balance.outstanding_minor,
                    "active_plan_id": None, "currency_code": source.currency_policy.currency_code, **source.currency_policy.metadata()}
