"""Governed monetary merchandise corrections over the existing GL and FIFO owners.

The immutable Stock/FX origin and its ordered native history supply every
account, currency and before-value witness. Requests contain operational intent;
they never select a monetary allocation, account or source policy.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, NoReturn
from uuid import uuid4

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.monetary_customer_partial_return_commands import (
    MonetaryPartialRefundPreparation,
    MonetaryPartialReturnPreparation,
    MonetaryPartialReversePreparation,
)
from reconforge.domain.monetary_customer_returns import (
    ALLOCATION_POLICY,
    Kind,
    MonetaryEvent,
    MonetaryHistory,
    prepare_monetary_event,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_customer_returns import PERMISSIONS, READ, PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_monetary_stock_sales import (
    SOURCE_SCHEMA,
    PostgresMonetaryStockSalesRepository,
    book_carrying,
    native_child_command,
)
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import scaled_to_text
from reconforge.utils.time import utc_now_text

PLAN_SCHEMA = "customer-partial-return-monetary-v3"
_PREFIXES = {"Return": "CR3-", "Refund": "CRF3-", "ReverseReturn": "CR3R-", "ReverseRefund": "CRF3R-"}


def _fail(code: str, message: str) -> NoReturn:
    raise FinancePostingError("monetary_return_" + code, message)


def correction_lines(event: MonetaryEvent, origin: Mapping[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Finite correction templates using original native account pins only.

    Inverse journals are prepared from the actual original posting effects,
    rather than from these forward templates. Zero functional legs are omitted.
    """
    if event.kind not in {"Return", "Refund"}:
        _fail("evidence_invalid", "Forward journal templates require their exact forward monetary operation.")
    movement, result = event.monetary, []
    roles = origin["roles"]
    lines: list[dict[str, Any]] = []

    def add(account: str, debit: int = 0, credit: int = 0) -> None:
        if type(debit) is not int or type(credit) is not int or min(debit, credit) < 0 or (debit and credit):
            _fail("evidence_invalid", "Exact single-direction functional journal legs are required.")
        if debit or credit:
            if account not in origin["dimensions"]:
                _fail("evidence_invalid", "Every original accounting role requires an explicit captured dimension set.")
            lines.append({"account_id": account, "debit_minor": debit, "credit_minor": credit,
                          "dimensions": dict(origin["dimensions"][account])})

    if event.kind == "Return":
        for component in event.components:
            add(origin["source"]["components"][component.position]["account_id"], component.functional_minor)
        add(roles["loss_account_id"], movement.functional_alignment_loss_minor)
        add(roles["receivable_account_id"], credit=movement.functional_receivable_released_minor)
        add(roles["refund_liability_account_id"], credit=movement.functional_refund_delta_minor)
        add(roles["gain_account_id"], credit=movement.functional_alignment_gain_minor)
        if lines:
            result.append(("MerchandiseCredit", lines))
        lines = []
        add(roles["inventory_account_id"], movement.functional_cost_minor)
        add(roles["cogs_account_id"], credit=movement.functional_cost_minor)
        if lines:
            result.append(("CostRestoration", lines))
    else:
        add(roles["refund_liability_account_id"], movement.functional_refund_released_minor)
        add(roles["loss_account_id"], movement.functional_fx_loss_minor)
        add(roles["cash_account_id"], credit=movement.functional_cash_minor)
        add(roles["gain_account_id"], credit=movement.functional_fx_gain_minor)
        if lines:
            result.append(("Refund", lines))
    if any(sum(line["debit_minor"] for line in journal) != sum(line["credit_minor"] for line in journal)
           for _, journal in result):
        _fail("evidence_invalid", "The original-component and historical-carrying correction must balance exactly.")
    if sum(sum(line["debit_minor"] for line in journal) for _, journal in result) != movement.functional_turnover_minor:
        _fail("evidence_invalid", "Journal membership must preserve the exact governed functional turnover.")
    return result


class _MonetaryCustomerReturnPostingParticipant:
    def __init__(self, owner: PostgresMonetaryCustomerPartialReturnsRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and connection is self.owner.connection
                and tenant_id == self.owner.tenant_id and entry_id == self.entry_id)

    def admits_reversal(self, connection: Any, tenant_id: str, source_entry: str, effect_id: str, new_number: str) -> bool:
        return (self.owner._participant is self and connection is self.owner.connection and tenant_id == self.owner.tenant_id
                and (source_entry, effect_id, new_number) == self.owner._reversal_admission)


class PostgresMonetaryCustomerPartialReturnsRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.legacy = PostgresCustomerReturnsRepository(connection, tenant_id)
        self.owner = self.legacy.owner
        self._participant: _MonetaryCustomerReturnPostingParticipant | None = None
        self._reversal_admission: tuple[str, str, str] | None = None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.owner._transaction():
                yield
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "55P03":
                raise FinancePostingError(
                    "monetary_return_retryable_conflict",
                    "The monetary command is contended; retry the same command and exact request after the current operation finishes.",
                ) from exc
            raise

    def _one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        values = records(self.connection.execute(query, parameters))
        if len(values) != 1:
            _fail("not_found", "One complete current scoped monetary owner is required.")
        return values[0]

    def _origin(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT * FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=%s AND id=%s",
                         (self.tenant_id, identifier))

    def _plan_authority(self, identifier: str, actor: PostingActor, operation: str) -> None:
        scope = self._one("""SELECT workspace_id,organization_id,legal_entity_id
            FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s AND id=%s""",
            (self.tenant_id, text(identifier, "plan_id")))
        self.legacy._authority_locks(actor, operation, scope)

    def _stock(self, origin: Mapping[str, Any]) -> PostgresMonetaryStockSalesRepository:
        codes = self._one("""SELECT organization.organization_code,entity.entity_code
            FROM reconforge.organizations organization JOIN reconforge.legal_entities entity
            ON(entity.tenant_id,entity.organization_id)=(organization.tenant_id,organization.id)
            WHERE organization.tenant_id=%s AND organization.id=%s AND entity.id=%s""",
            (self.tenant_id, origin["organization_id"], origin["legal_entity_id"]))
        return PostgresMonetaryStockSalesRepository(self.connection, self.tenant_id,
            **{key: origin[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}, **codes)

    def _row(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        sql = "SELECT payload,phase FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s AND id=%s"
        value = self._one(sql + (" FOR UPDATE" if lock else ""), (self.tenant_id, text(identifier, "plan_id")))
        result = {**value["payload"], "phase": value["phase"]}
        if result.get("schema_version") != PLAN_SCHEMA or result.get("allocation_policy") != ALLOCATION_POLICY:
            _fail("protocol_conflict", "The monetary owner admits only its immutable original source protocol.")
        return result

    def _actor(self, actor: PostingActor, operation: str, origin: Mapping[str, Any], event: MonetaryEvent | None = None) -> None:
        self.legacy._authority_locks(actor, operation, origin)
        payload = origin["payload"]
        source = payload["source"]
        foreign = sum(part["transaction_minor"] for part in source["components"])
        local = sum(part["functional_minor"] for part in source["components"])
        original_cost = sum(part["value_minor"] for part in source["consumptions"])
        read_local = max(local, original_cost, book_carrying(origin))
        if event is None:
            exposures = (foreign, max(local, original_cost))
        else:
            movement = event.monetary
            exposures = (max(movement.transaction_credit_minor, movement.transaction_refund_minor), movement.functional_turnover_minor)
        for permission in sorted(PERMISSIONS.get(operation, READ)):
            for index, policy in enumerate((source["transaction_policy"], source["functional_policy"])):
                amount = (foreign if index == 0 else read_local) if permission in READ else exposures[index]
                if type(amount) is not int or amount < 0:
                    _fail("evidence_invalid", "Both captured currency exposures require exact native minor units.")
                self.owner._actor(actor, permission, {**{key: origin[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                    "amount_minor": amount, "currency_precision": policy["precision"]},
                    mutation=operation != "read", allow_zero_amount=amount == 0)
        if operation != "read":
            self.connection.execute("SELECT set_config('app.customer_partial_return_monetary_actor_id',%s,true)", (actor.user_id,))

    def _locks(self, origin: Mapping[str, Any], *, period_id: str | None = None, day: str | None = None) -> MonetaryHistory:
        if period_id is not None:
            if day is None:
                _fail("request_invalid", "An explicit current accounting date is required with its period.")
            self.owner.posting._period(period_id, origin["workspace_id"], day)
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(origin["workspace_id"])
        stock = self._stock(origin)
        row = stock._order(origin["stock_order_id"])
        if row["source"]["schema_version"] != SOURCE_SCHEMA or row["invoice_id"] != origin["invoice_id"]:
            _fail("source_changed", "The current Stock source and native invoice no longer identify this original.")
        stock._parents(row)
        self.connection.execute("SELECT reconforge.monetary_stock_close(%s,%s)", (self.tenant_id, row["id"]))
        return stock._history(row["id"])

    def _read_parents(self, origin: Mapping[str, Any]) -> dict[str, Any]:
        stock = self._stock(origin)
        row = stock._order(origin["stock_order_id"])
        if row["source"]["schema_version"] != SOURCE_SCHEMA or row["invoice_id"] != origin["invoice_id"]:
            _fail("source_changed", "The current Stock source and native invoice no longer identify this original.")
        # Keep all subsequent VOLATILE closure/projection statements on one
        # committed economic prefix, in the same order as monetary writers.
        stock._parents(row, share=True)
        return self._origin(origin["id"])

    def _command(self, context: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command, "command_id", maximum=140)
        body = {"protocol_version": 3, "operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(body)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, context["workspace_id"], "customer-partial-returns", command]),))
        if self.connection.execute("SELECT 1 FROM reconforge.customer_partial_return_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                   (self.tenant_id, context["workspace_id"], command)).fetchone():
            _fail("command_conflict", "This command already belongs to an immutable legacy protocol.")
        values = records(self.connection.execute("SELECT * FROM reconforge.customer_partial_return_monetary_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                                (self.tenant_id, context["workspace_id"], command)))
        if not values:
            return digest, None
        saved = values[0]
        if (saved["operation"], saved["actor_id"], saved["request_digest"]) != (operation, actor.user_id, digest):
            _fail("command_conflict", "The command identifies another actor or exact immutable intent.")
        plan = self._row(saved["plan_id"])
        self._actor(actor, "prepare" if operation.startswith("prepare") else operation, self._origin(plan["source_id"]))
        self.connection.execute("SELECT reconforge.monetary_partial_close(%s,%s)", (self.tenant_id, plan["id"]))
        return digest, saved["response_json"]

    def _view(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.monetary_partial_public(%s,%s) value", (self.tenant_id, identifier))["value"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        value = self._view(plan["id"])
        body = {"protocol_version": 3, "operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_monetary_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["id"], operation, command,
             actor.user_id, digest, canonical_json(body), canonical_json(value)))
        return value

    def _available(self, origin: Mapping[str, Any], history: MonetaryHistory, expected: int) -> None:
        if type(expected) is not int or expected != len(history.events) or expected >= 256:
            _fail("state_conflict", "Reload the exact current bounded monetary history before preparing a command.")
        state = self._stock(origin).fx._state(self._stock(origin).fx._peek("source", origin["fx_source_id"]))
        if state["active_revaluation_plan_id"] is not None:
            _fail("state_conflict", "Reverse the active native closing valuation before a historical source correction.")
        if self.connection.execute("""SELECT 1 FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND source_id=%s AND phase<2
            UNION ALL SELECT 1 FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s AND origin_id=%s AND phase<2""",
            (self.tenant_id, origin["fx_source_id"], self.tenant_id, origin["id"])).fetchone():
            _fail("state_conflict", "Complete or cancel the exact pending monetary source operation first.")

    def _draft(self, plan: Mapping[str, Any], purpose: str, lines: list[dict[str, Any]], actor: PostingActor,
               origin: Mapping[str, Any]) -> dict[str, Any]:
        suffix = {"MerchandiseCredit": "R", "CostRestoration": "C", "Refund": "F"}[purpose]
        number = plan["id"].upper() + "-" + suffix
        entry_id, now = platform_id("GLE", plan["workspace_id"], number), utc_now_text()
        policy = origin["payload"]["functional_policy"]
        total = sum(line["debit_minor"] for line in lines)
        self.connection.execute("""INSERT INTO reconforge.finance_entries
            (tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,posting_date,description,external_reference,
             source_type,status,currency_code,total_debit_minor,total_credit_minor,created_by,currency_precision,currency_rounding_policy,
             currency_registry_version,currency_registry_digest,preparer_actor_id,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Manual','Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, entry_id, plan["workspace_id"], origin["payload"]["journal_id"], plan["organization_code"], plan["entity_code"],
             plan["period_id"], number, plan["posting_date"], plan["reason"], plan["id"], policy["currency_code"], total, total, actor.username,
             policy["currency_precision"], policy["currency_rounding_policy"], policy["currency_registry_version"], policy["currency_registry_digest"], actor.user_id, now, now))
        for ordinal, line in enumerate(lines, 1):
            line_id = platform_id("GLL", entry_id, ordinal)
            self.connection.execute("""INSERT INTO reconforge.finance_entry_lines
                (tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, line_id, entry_id, ordinal, line["account_id"], plan["reason"], line["debit_minor"], line["credit_minor"], policy["currency_code"]))
            for dimension, value in line["dimensions"].items():
                self.connection.execute("INSERT INTO reconforge.finance_entry_line_dimensions(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)",
                                        (self.tenant_id, line_id, dimension, value))
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
        return {"purpose": purpose, "entry_id": entry_id, "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "original_effect_id": None}

    def _event(self, plan: Mapping[str, Any], operation: str, actor: PostingActor, reason: str) -> None:
        audit, outbox = self.owner._event(plan, "customer_partial_return_monetary_" + operation, actor,
                                        {"plan_digest": plan["plan_digest"], "reason": reason})
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_monetary_events
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,actor_id,reason,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"],
            plan["id"], operation, actor.user_id, reason, audit, outbox))

    def _save(self, plan: dict[str, Any], actor: PostingActor) -> None:
        plan["preparer_actor_id"] = actor.user_id
        plan["plan_digest"] = digest_payload(plan)
        self.connection.execute("""INSERT INTO reconforge.customer_partial_return_monetary_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,origin_id,operation,phase,original_id,expected_history_version,payload,plan_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s::jsonb,%s)""", (self.tenant_id, plan["id"], plan["workspace_id"], plan["organization_id"],
            plan["legal_entity_id"], plan["source_id"], plan["operation"], plan["original_id"], plan["expected_history_version"], canonical_json(plan), plan["plan_digest"]))
        for part in plan["entries"]:
            self.connection.execute("""INSERT INTO reconforge.customer_partial_return_monetary_entries
                (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,purpose,entry_id,snapshot,validation_digest,original_effect_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, plan["workspace_id"], plan["organization_id"],
                plan["legal_entity_id"], plan["id"], part["purpose"], part["entry_id"], canonical_json(part["snapshot"]), part["validation_digest"], part["original_effect_id"]))
        self._event(plan, "prepare", actor, plan["reason"])
        self.connection.execute("SELECT reconforge.monetary_stock_refresh_balance(%s,%s)", (self.tenant_id, plan["source_order_id"]))

    def _prepare(self, origin: Mapping[str, Any], args: Mapping[str, Any], operation: Kind, original: Mapping[str, Any] | None,
                 command_id: str, actor: PostingActor) -> dict[str, Any]:
        self._actor(actor, "prepare", origin)
        command_operation = {"Return": "prepare", "Refund": "prepare_refund", "ReverseReturn": "prepare_reversal", "ReverseRefund": "prepare_reversal"}[operation]
        digest, replay = self._command(origin, command_operation, command_id, actor, args)
        if replay is not None:
            return replay
        history = self._locks(origin, period_id=args["period_id"], day=args["posting_date"])
        self._available(origin, history, args["expected_history_version"])
        event = prepare_monetary_event(history, operation, posting_date=args["posting_date"],
            quantity_scaled=args["quantity_scaled"] if operation == "Return" else original["quantity_scaled"] if original and operation == "ReverseReturn" else 0,
            amount_minor=args["amount_minor"] if operation == "Refund" else original["monetary_event"]["amount_minor"] if original and operation == "ReverseRefund" else 0,
            settlement_rate=(HistoricalRate(**args["settlement_rate"]) if args.get("settlement_rate") is not None else None),
            original_sequence=original["monetary_event"]["sequence"] if original and operation.startswith("Reverse") else None)
        self._actor(actor, "prepare", origin, event)
        stock = self._stock(origin)
        plan = {"schema_version": PLAN_SCHEMA, "id": _PREFIXES[operation] + uuid4().hex, **stock.scope,
            "source_id": origin["id"], "source_order_id": origin["stock_order_id"], "invoice_id": origin["invoice_id"],
            "operation": operation, "quantity_scaled": event.quantity_scaled, "quantity_precision": history.source.quantity_precision,
            "period_id": args["period_id"], "posting_date": args["posting_date"], "reason": args["reason"],
            "source_fingerprint": history.source.fingerprint, "history_fingerprint": event.previous_history_fingerprint,
            "expected_history_version": len(history.events), "allocation_policy": ALLOCATION_POLICY,
            "transaction_policy": asdict(history.source.transaction_policy), "functional_policy": asdict(history.source.functional_policy),
            "monetary": asdict(event.monetary), "monetary_event": asdict(event), "entries": [],
            "movement_id": None,
            "original_id": original["id"] if original else None, "request": dict(args)}
        if operation in {"Return", "ReverseReturn"}:
            plan["movement_id"] = platform_id("MOV", origin["workspace_id"], plan["id"].upper())
        if operation.startswith("Reverse"):
            if original is None or original["phase"] != 2 or original["source_id"] != origin["id"]:
                _fail("state_conflict", "Only the exact posted same-source original may be inverted.")
            for part in original["entries"]:
                effect = self._one("SELECT id FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND entry_id=%s", (self.tenant_id, part["entry_id"]))
                purpose = "Reverse" + part["purpose"]
                suffix = {"MerchandiseCredit": "R", "CostRestoration": "C", "Refund": "F"}[part["purpose"]]
                number = plan["id"].upper() + "-" + suffix
                entry_id = platform_id("GLE", origin["workspace_id"], number)
                self._reversal_admission = (part["entry_id"], effect["id"], number)
                self._participant = _MonetaryCustomerReturnPostingParticipant(self, entry_id)
                try:
                    created = self.owner.posting.prepare_reversal(effect["id"], command_id=native_child_command("cr3-inverse-" + suffix, command_id),
                        entry_number=number, period_id=args["period_id"], posting_date=args["posting_date"], reason=args["reason"],
                        actor=actor, _source_owner=self._participant)
                finally:
                    self._reversal_admission, self._participant = None, None
                if created["entry_id"] != entry_id:
                    _fail("evidence_invalid", "The inverse journal must use its exact reserved native identity.")
                snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
                plan["entries"].append({"purpose": purpose, "entry_id": entry_id, "snapshot": snapshot,
                    "validation_digest": validation_digest(snapshot), "original_effect_id": effect["id"]})
        else:
            plan["entries"] = [self._draft(plan, purpose, lines, actor, origin) for purpose, lines in correction_lines(event, origin["payload"])]
        self._save(plan, actor)
        return self._remember(plan, command_operation, command_id, actor, digest, args)

    def prepare(self, request: MonetaryPartialReturnPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            # Scope-only current authority precedes any private origin read.
            self.legacy._authority_locks(actor, "prepare", args)
            origin = self._one("SELECT * FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=%s AND stock_order_id=%s",
                               (self.tenant_id, args["source_order_id"]))
            if any(origin[key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                _fail("scope_denied", "The source belongs to another current command scope.")
            return self._prepare(origin, args, "Return", None, command_id, actor)

    def prepare_refund(self, request: MonetaryPartialRefundPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._plan_authority(args["return_id"], actor, "prepare")
            original = self._row(args["return_id"])
            if original["operation"] != "Return" or original["phase"] != 2:
                _fail("state_conflict", "Refund preparation requires the actual posted Return parent.")
            return self._prepare(self._origin(original["source_id"]), args, "Refund", original, command_id, actor)

    def prepare_reversal(self, request: MonetaryPartialReversePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._plan_authority(args["original_id"], actor, "prepare")
            original = self._row(args["original_id"])
            if original["operation"] not in {"Return", "Refund"} or original["phase"] != 2:
                _fail("state_conflict", "Only a posted original Return or Refund may be inverted.")
            operation: Kind = "ReverseReturn" if original["operation"] == "Return" else "ReverseRefund"
            return self._prepare(self._origin(original["source_id"]), args, operation, original, command_id, actor)

    def _current(self, plan: Mapping[str, Any], origin: Mapping[str, Any], history: MonetaryHistory) -> MonetaryEvent:
        if len(history.events) != plan["expected_history_version"]:
            _fail("state_conflict", "The active source prefix changed after monetary preparation.")
        retained = plan["monetary_event"]
        expected = prepare_monetary_event(history, plan["operation"], posting_date=plan["posting_date"], quantity_scaled=retained["quantity_scaled"],
            amount_minor=retained["amount_minor"], settlement_rate=HistoricalRate(**retained["settlement_rate"]) if retained["settlement_rate"] is not None else None,
            original_sequence=retained["original_sequence"])
        if canonical_json(asdict(expected)) != canonical_json(retained):
            _fail("evidence_invalid", "Original component, cost and historical-carrying witnesses must remain exact.")
        state = self._stock(origin).fx._state(self._stock(origin).fx._peek("source", origin["fx_source_id"]))
        if state["active_revaluation_plan_id"] is not None:
            _fail("state_conflict", "Reverse the active closing valuation before the historical correction.")
        return expected

    def _layers(self, plan: Mapping[str, Any]) -> None:
        stock = self._stock(self._origin(plan["source_id"]))
        original = stock._order(plan["source_order_id"])
        stock._stock_lock(original)
        stock._fifo_lock(original)
        for layer_id in sorted({part["cost_layer_id"] for part in plan["monetary_event"]["portions"]}):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (layer_id,))
            self._one("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, layer_id))
        if plan["operation"] == "ReverseReturn":
            for part in plan["monetary_event"]["portions"]:
                witness = self._one("""SELECT original.consumption_count_at_restore,layer.remaining_quantity_scaled,layer.remaining_value_minor,
                    (SELECT count(*) FROM reconforge.inventory_layer_consumptions consumed WHERE consumed.tenant_id=original.tenant_id
                     AND consumed.cost_layer_id=original.cost_layer_id) current_count
                    FROM reconforge.customer_partial_return_monetary_restorations original JOIN reconforge.inventory_cost_layers layer
                    ON(layer.tenant_id,layer.id)=(original.tenant_id,original.cost_layer_id)
                    WHERE original.tenant_id=%s AND original.plan_id=%s AND original.position=%s AND original.direction=1""",
                    (self.tenant_id, plan["original_id"], part["position"]))
                if (witness["current_count"] != witness["consumption_count_at_restore"]
                        or witness["remaining_quantity_scaled"] < part["quantity_scaled"] or witness["remaining_value_minor"] < part["value_minor"]):
                    _fail("reversal_dependency", "A later native FIFO consumption follows the original restored layer.")

    def _physical(self, plan: Mapping[str, Any], origin: Mapping[str, Any], actor: PostingActor) -> None:
        stock = self._stock(origin)._order(origin["stock_order_id"])
        location = self._one("""SELECT location.location_code,warehouse.warehouse_code FROM reconforge.inventory_locations location
            JOIN reconforge.inventory_warehouses warehouse ON(warehouse.tenant_id,warehouse.id)=(location.tenant_id,location.warehouse_id)
            WHERE location.tenant_id=%s AND location.id=%s""", (self.tenant_id, stock["location_id"]))
        maker = self._one("SELECT username FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan["preparer_actor_id"]))["username"]
        inventory = PostgresInventoryCoreRepository(self.connection, self.tenant_id)
        returned = plan["operation"] == "Return"
        movement = inventory.create_movement(movement_number=plan["id"].upper(), movement_type="Receipt" if returned else "Delivery",
            organization_code=plan["organization_code"], entity_code=plan["entity_code"], period_id=plan["period_id"], movement_date=plan["posting_date"],
            description=plan["reason"], source_reference=plan["id"], source_type="Generated", workspace=plan["workspace_id"], actor_label=maker,
            lines=[{"item_code": stock["source"]["item_code"], "quantity": scaled_to_text(plan["quantity_scaled"], stock["quantity_precision"]),
                    "to_location" if returned else "from_location": location["warehouse_code"] + "/" + location["location_code"]}])
        if movement["id"] != plan["movement_id"]:
            _fail("evidence_invalid", "The original physical scope and reserved native movement identity must agree.")
        inventory.post_movement(movement["id"], reason=plan["reason"], actor_label=actor.username)

    def _restore(self, plan: Mapping[str, Any], effects: Mapping[str, str]) -> None:
        direction = 1 if plan["operation"] == "Return" else -1
        effect = effects.get("CostRestoration") or effects.get("ReverseCostRestoration")
        for part in plan["monetary_event"]["portions"]:
            self.connection.execute("""INSERT INTO reconforge.customer_partial_return_monetary_restorations
                (tenant_id,workspace_id,organization_id,legal_entity_id,origin_id,plan_id,position,original_consumption_id,original_valuation_line_id,
                 cost_layer_id,before_quantity_scaled,before_value_minor,quantity_scaled,value_minor,direction,physical_movement_id,
                 correction_effect_id,original_restoration_plan_id,consumption_count_at_restore)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                 (SELECT count(*) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s AND cost_layer_id=%s))""",
                (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["source_id"], plan["id"], part["position"],
                 part["original_consumption_id"], part["original_valuation_line_id"], part["cost_layer_id"], part["before_quantity_scaled"], part["before_value_minor"],
                 part["quantity_scaled"], part["value_minor"], direction, plan["movement_id"], effect, plan["original_id"] if direction == -1 else None,
                 self.tenant_id, part["cost_layer_id"]))
            self.connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+%s,
                remaining_value_minor=remaining_value_minor+%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                (direction * part["quantity_scaled"], direction * part["value_minor"], self.tenant_id, part["cost_layer_id"]))

    def _phase(self, identifier: str, operation: str, expected: str, command: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self._plan_authority(identifier, actor, operation)
            plan = self._row(identifier)
            origin = self._origin(plan["source_id"])
            self._actor(actor, operation, origin)
            if expected != plan["plan_digest"]:
                _fail("state_conflict", "The expected immutable plan digest differs.")
            args = {"plan_id": identifier, "expected_plan_digest": expected, "reason": text(reason, "reason", maximum=500)}
            digest, replay = self._command(plan, operation, command, actor, args)
            if replay is not None:
                return replay
            history = self._locks(origin, period_id=plan["period_id"], day=plan["posting_date"])
            plan = self._row(identifier, lock=True)
            event = self._current(plan, origin, history)
            self._actor(actor, operation, origin, event)
            reviewers = records(self.connection.execute("SELECT actor_id FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'",
                                                        (self.tenant_id, identifier)))
            if actor.user_id in {plan["preparer_actor_id"], *(row["actor_id"] for row in reviewers)}:
                _fail("phase_denied", "Each financial phase requires an independent currently authorized human.")
            if (operation == "review" and plan["phase"] != 0) or (operation == "post" and plan["phase"] != 1) or (operation == "cancel" and plan["phase"] not in {0, 1}):
                _fail("state_conflict", "The governed lifecycle phase differs.")
            if operation == "post":
                self._layers(plan)
                if plan["operation"] in {"Return", "ReverseReturn"}:
                    self._physical(plan, origin, actor)
            effects: dict[str, str] = {}
            for part in plan["entries"]:
                if operation == "review":
                    self.owner.finance.validate_entry(part["entry_id"], reason=reason, actor_label=actor.username)
                elif operation == "cancel":
                    if posting_entry(self.connection, self.tenant_id, part["entry_id"])["status"] == "Draft":
                        self.owner.finance.validate_entry(part["entry_id"], reason=reason, actor_label=actor.username)
                    self.owner.finance.void_entry(part["entry_id"], reason=reason, actor_label=actor.username)
                else:
                    self._participant = _MonetaryCustomerReturnPostingParticipant(self, part["entry_id"])
                    try:
                        effect = self.owner.posting.post(part["entry_id"], command_id=native_child_command("cr3-" + part["purpose"], command),
                            expected_validation_digest=part["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
                    finally:
                        self._participant = None
                    effects[part["purpose"]] = effect["id"]
                    self.connection.execute("UPDATE reconforge.customer_partial_return_monetary_entries SET posting_effect_id=%s WHERE tenant_id=%s AND plan_id=%s AND purpose=%s",
                                            (effect["id"], self.tenant_id, identifier, part["purpose"]))
            if operation == "post" and plan["operation"] in {"Return", "ReverseReturn"}:
                self._restore(plan, effects)
            self._event(plan, operation, actor, reason)
            self.connection.execute("UPDATE reconforge.customer_partial_return_monetary_plans SET phase=%s WHERE tenant_id=%s AND id=%s",
                                    ({"review": 1, "post": 2, "cancel": 3}[operation], self.tenant_id, identifier))
            if operation == "post":
                self.connection.execute("SELECT reconforge.monetary_stock_append_partial(%s,%s,%s,%s::jsonb)",
                    (self.tenant_id, origin["stock_order_id"], identifier, canonical_json(asdict(event))))
            self.connection.execute("SELECT reconforge.monetary_stock_refresh_balance(%s,%s)", (self.tenant_id, origin["stock_order_id"]))
            return self._remember(plan, operation, command, actor, digest, args)

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase(plan_id, "review", expected_plan_digest, command_id, reason, actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase(plan_id, "post", expected_plan_digest, command_id, reason, actor)

    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase(plan_id, "cancel", expected_plan_digest, command_id, reason, actor)

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self._plan_authority(plan_id, actor, "read")
            plan = self._row(plan_id)
            origin = self._origin(plan["source_id"])
            self._actor(actor, "read", origin)
            origin = self._read_parents(origin)
            self._row(plan_id)
            self._actor(actor, "read", origin)
            self.connection.execute("SELECT reconforge.monetary_partial_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def list_plans(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self.legacy._authority_locks(actor, "read", scope)
            identifiers = records(self.connection.execute("""SELECT id FROM reconforge.customer_partial_return_monetary_plans
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            return {"plans": [self.get(row["id"], actor=actor) for row in identifiers]}

    def balance(self, source_order_id: str, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self.legacy._authority_locks(actor, "read", scope)
            origin = self._one("SELECT * FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=%s AND stock_order_id=%s",
                               (self.tenant_id, source_order_id))
            if any(origin[key] != scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                _fail("scope_denied", "The native monetary source belongs to another current scope.")
            self._actor(actor, "read", origin)
            origin = self._read_parents(origin)
            self._actor(actor, "read", origin)
            self.connection.execute("SELECT reconforge.monetary_stock_close(%s,%s)", (self.tenant_id, source_order_id))
            return self._one("SELECT reconforge.monetary_partial_balance(%s,%s) value", (self.tenant_id, origin["id"]))["value"]
