"""Atomic PR/RFQ/quote/award ownership over native budget-backed procurement."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import exact_text
from reconforge.domain.procurement_commitments import BudgetPurchasePreparation, version
from reconforge.domain.procurement_partial import (
    MultilineProcurementPreparation,
    ProcurementOrderLine,
    ProcurementPartialError,
)
from reconforge.domain.procurement_sourcing import (
    MAX_QUOTES,
    PERMISSIONS,
    SCHEMA_VERSION,
    RequirementReference,
    RequisitionPreparation,
    SupplierQuotationPreparation,
    deterministic_winner,
    normalize_requisition,
    quotation_order,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_procurement_commitments import PostgresProcurementCommitmentRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import quantity_to_scaled


class PostgresProcurementSourcingRepository:
    def __init__(self, connection: Any, tenant_id: str, *, require_live_session_assurance: bool = False) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.commitments = PostgresProcurementCommitmentRepository(connection, tenant_id,
            require_live_session_assurance=require_live_session_assurance)
        self.purchase, self.budgets = self.commitments.purchase, self.commitments.budgets

    @staticmethod
    def _scope(row: Mapping[str, Any]) -> BudgetScope:
        return BudgetScope(*(str(row[key]) for key in ("workspace_id", "organization_id", "legal_entity_id")))

    @staticmethod
    def _order(payload: Mapping[str, Any]) -> MultilineProcurementPreparation:
        order = dict(payload["request"]["order"])
        order["lines"] = tuple(ProcurementOrderLine(**line) for line in order["lines"])
        return MultilineProcurementPreparation(**order)

    def _row(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT * FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=%s AND id=%s FOR UPDATE" if lock
                 else "SELECT * FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=%s AND id=%s")
        return self.purchase._one(query, (self.tenant_id, exact_text(identifier)))

    def _actor(self, row: Mapping[str, Any], actor: PostingActor, operation: str) -> None:
        scope = self._scope(row)
        amount = Decimal((0, tuple(map(int, str(int(row["ceiling_minor"])))), -int(row["payload"]["currency_precision"])))
        for permission in sorted(PERMISSIONS["read"] | PERMISSIONS.get(operation, frozenset())):
            live = self.budgets._actor(scope, permission, write=operation != "read", amount=amount)
            if live.id != actor.user_id:
                raise ProcurementPartialError("procurement_sourcing_actor_denied", "Sourcing requires the same current persisted human authority.")
        currency = self.purchase._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active",
            (self.tenant_id, row["payload"]["request"]["order"]["currency_code"]))
        if currency["minor_units"] != row["payload"]["currency_precision"]:
            raise ProcurementPartialError("procurement_sourcing_currency_policy", "Retained demand precision cannot be reinterpreted by current currency metadata.")
        if operation != "read":
            self.connection.execute("SELECT set_config('app.procurement_sourcing_actor_id',%s,true)", (actor.user_id,))
        if any(reference is not None for reference in row["payload"]["request"].get("requirements", ())):
            # Recheck the source owner's current scoped/retained authority on reads and lost acknowledgments too.
            references = tuple(RequirementReference(**reference) if reference else None
                               for reference in row["payload"]["request"]["requirements"])
            self._requirements(RequisitionPreparation(budget_id=row["payload"]["request"]["budget_id"],
                order=self._order(row["payload"]), reason=row["payload"]["request"]["reason"], requirements=references), row, actor)

    def _period(self, row: Mapping[str, Any]) -> None:
        order = row["payload"]["request"]["order"]
        PostgresFinancePostingRepository(self.connection, self.tenant_id)._period(order["period_id"], row["workspace_id"], order["posting_date"])

    def _command(self, row: Mapping[str, Any], operation: str, command_id: str,
                 request: Mapping[str, Any], actor: PostingActor) -> tuple[str, dict[str, Any] | None]:
        command_id = exact_text(command_id, maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, row["workspace_id"], "procurement-sourcing", command_id]),))
        retained = self.connection.execute("SELECT * FROM reconforge.procurement_sourcing_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, row["workspace_id"], command_id)).fetchone()
        if retained is None:
            return digest, None
        if (retained["requisition_id"], retained["actor_id"], retained["request_digest"]) != (row["id"], actor.user_id, digest):
            raise ProcurementPartialError("procurement_sourcing_command_conflict", "The command identifies another exact request, original source or human.")
        self._actor(self._row(row["id"]), actor, operation)
        self.connection.execute("SELECT reconforge.ps_close(%s,%s)", (self.tenant_id, row["id"]))
        return digest, dict(retained["response_json"])

    def _remember(self, row: Mapping[str, Any], operation: str, command_id: str, request: Mapping[str, Any],
                  digest: str, actor: PostingActor, reason: str) -> dict[str, Any]:
        metadata = {"source_digest": row["source_digest"], "command_id": command_id,
                    "request_digest": digest, "version": row["row_version"], "operation": operation, "reason": reason}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="procurement_sourcing", object_id=row["id"],
            action="procurement_sourcing_" + operation, metadata=metadata)
        outbox = "PSOUT-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,
            workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,%s,'procurement_sourcing',%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, outbox, "procurement_sourcing_" + operation, row["id"], row["workspace_id"], row["organization_id"],
             row["legal_entity_id"], canonical_json({**metadata, "audit_event_id": audit.id})))
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self.connection.execute("""INSERT INTO reconforge.procurement_sourcing_events(tenant_id,requisition_id,version,operation,
            actor_id,command_id,request_json,request_digest,reason,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
            (self.tenant_id, row["id"], row["row_version"], operation, actor.user_id, command_id,
             canonical_json(envelope), digest, reason, audit.id, outbox))
        response = self.connection.execute("SELECT reconforge.ps_public(%s,%s,%s) value",
            (self.tenant_id, row["id"], row["row_version"])).fetchone()["value"]
        self.connection.execute("""INSERT INTO reconforge.procurement_sourcing_commands(tenant_id,workspace_id,requisition_id,
            command_id,actor_id,request_digest,request_json,version,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""",
            (self.tenant_id, row["workspace_id"], row["id"], command_id, actor.user_id, digest,
             canonical_json(envelope), row["row_version"], canonical_json(response)))
        self.connection.execute("SELECT reconforge.ps_close(%s,%s)", (self.tenant_id, row["id"]))
        return dict(response)

    def _requirements(self, request: RequisitionPreparation, scope: Mapping[str, Any], actor: PostingActor) -> list[dict[str, Any] | None]:
        retained: list[dict[str, Any] | None] = []
        for line, reference in zip(request.order.lines, request.requirements, strict=True):
            if reference is None:
                retained.append(None)
                continue
            # Empty ordinary sources never load or plan against protected manufacturing.
            from reconforge.infrastructure.postgres_manufacturing_execution import (
                PostgresManufacturingExecutionRepository,
            )
            requirement = PostgresManufacturingExecutionRepository(self.connection, self.tenant_id).get_requirement(reference.requirement_id, actor=actor)
            if (requirement["requirement_digest"] != reference.requirement_digest or requirement["item_code"] != line.item_code
                    or any(requirement["scope"][key] != scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
                    or quantity_to_scaled(line.quantity, int(requirement["quantity_precision"])) > int(requirement["required_quantity_scaled"])):
                raise ProcurementPartialError("procurement_sourcing_requirement_invalid", "Demand must bind its original same-scope manufacturing item and exact requirement quantity.")
            retained.append(dict(requirement))
        return retained

    def _demand_masters(self, request: RequisitionPreparation, scope: Mapping[str, Any]) -> list[dict[str, Any]]:
        retained: list[dict[str, Any]] = []
        clearing: str | None = None
        for line in request.order.lines:
            item = self.purchase.receipts.inventory._item(scope["workspace_id"], line.item_code, active=True)
            if (item["item_type"] not in ("Stock", "Consumable") or item["tracking_mode"] != "None"
                    or not item["uom_active"] or item["organization_id"] not in (None, scope["organization_id"])):
                raise ProcurementPartialError("procurement_sourcing_item_invalid", "Demand requires active untracked stock and its exact base unit.")
            quantity_to_scaled(line.quantity, item["decimal_places"])
            location = self.purchase.receipts.inventory._location_reference(scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], line.location_code)
            if location is None or location["location_type"] != "Internal" or location["allow_negative"]:
                raise ProcurementPartialError("procurement_sourcing_location_invalid", "Demand requires an active scoped internal warehouse with negative stock disabled.")
            policy = self.purchase._one("""SELECT id,receipt_clearing_account_id FROM reconforge.inventory_valuation_policies
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s
                AND active AND costing_method='FIFO' AND currency_code=%s FOR SHARE""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], line.policy_code, request.order.currency_code))
            if clearing is not None and clearing != policy["receipt_clearing_account_id"]:
                raise ProcurementPartialError("procurement_sourcing_mapping_invalid", "Demand requires one native payable receipt-clearing mapping.")
            clearing = policy["receipt_clearing_account_id"]
            retained.append({"item_id": item["id"], "uom_id": item["uom_id"], "quantity_precision": item["decimal_places"],
                             "location_id": location["id"], "policy_id": policy["id"]})
        return retained

    def create(self, request: RequisitionPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request, total = normalize_requisition(request)
        with self.connection.transaction():
            self.purchase._scope_transaction()
            scope = self.purchase.shared._codes_scope(request.order.workspace, request.order.organization_code, request.order.entity_code)
            envelope = self.budgets._row(BudgetScope(*(scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))), request.budget_id)
            if envelope["status"] != "Approved" or (envelope["currency_code"], envelope["period_id"]) != (request.order.currency_code, request.order.period_id):
                raise ProcurementPartialError("procurement_sourcing_budget_invalid", "An approved same-scope appropriation with the exact demand currency and fiscal period is required.")
            identifier = platform_id("PSREQ", scope["workspace_id"], request.order.number)
            payload = {"schema_version": SCHEMA_VERSION, "request": asdict(request), "scope": {key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                       "ceiling_minor": total, "currency_precision": envelope["currency_precision"], "creator_actor_id": actor.user_id}
            row = {**scope, "id": identifier, "ceiling_minor": total, "payload": payload}
            self._actor(row, actor, "create")
            digest, replay = self._command(row, "create", command_id, asdict(request), actor)
            if replay is not None:
                return replay
            self._period(row)
            payload["demand_masters"] = self._demand_masters(request, scope)
            payload["manufacturing_requirements"] = self._requirements(request, scope, actor)
            seal = digest_payload(payload)
            self.connection.execute("""INSERT INTO reconforge.procurement_sourcing_requisitions(tenant_id,id,workspace_id,organization_id,
                legal_entity_id,number,budget_id,order_id,ceiling_minor,payload,source_digest,creator_actor_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], request.order.number,
                 request.budget_id, platform_id("PPORDER", scope["workspace_id"], "BPC1-" + request.order.number), total,
                 canonical_json(payload), seal, actor.user_id))
            return self._remember(self._row(identifier), "create", command_id, asdict(request), digest, actor, request.reason)

    def _begin(self, identifier: str, operation: str, expected_version: int, command_id: str,
               request: Mapping[str, Any], actor: PostingActor) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        version(expected_version)
        self.purchase._scope_transaction()
        row = self._row(identifier)
        self._actor(row, actor, operation)
        digest, replay = self._command(row, operation, command_id, request, actor)
        if replay is not None:
            return row, digest, replay
        self._period(row)
        if operation == "award":
            self.budgets._row(self._scope(row), row["budget_id"], lock=True)
        row = self._row(identifier, lock=True)
        self._actor(row, actor, operation)
        if row["row_version"] != expected_version:
            raise ProcurementPartialError("procurement_sourcing_version_conflict", "The retained demand or offer set changed; review the current version.")
        return row, digest, None

    def record_quotation(self, identifier: str, quote: SupplierQuotationPreparation, *, expected_version: int,
                         command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            request = {"requisition_id": identifier, "expected_version": expected_version, "quotation": asdict(quote)}
            row, digest, replay = self._begin(identifier, "quote", expected_version, command_id, request, actor)
            if replay is not None:
                return replay
            if row["phase"] != 1:
                raise ProcurementPartialError("procurement_sourcing_quote_conflict", "Only an independently opened RFQ may retain supplier offers.")
            order, total = quotation_order(self._order(row["payload"]), quote)
            count = self.connection.execute("SELECT count(*) n FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=%s AND requisition_id=%s",
                (self.tenant_id, identifier)).fetchone()["n"]
            if count >= MAX_QUOTES:
                raise ProcurementPartialError("procurement_sourcing_quote_limit", "The retained RFQ quote set reached its explicit bound.")
            supplier = self.purchase._one("""SELECT id FROM reconforge.ap_suppliers WHERE tenant_id=%s AND workspace_id=%s AND supplier_code=%s
                AND status='Active' AND(organization_id IS NULL OR organization_id=%s) AND(legal_entity_id IS NULL OR legal_entity_id=%s)
                AND currency_code=%s FOR SHARE""", (self.tenant_id, row["workspace_id"], order.supplier_code,
                row["organization_id"], row["legal_entity_id"], order.currency_code))
            payload = {"schema_version": "supplier-quotation-v1", "requisition_id": identifier, "source_digest": row["source_digest"],
                "supplier_id": supplier["id"], "quotation": asdict(quote), "order": asdict(order), "total_minor": total, "registrar_actor_id": actor.user_id}
            quote_id = platform_id("PSQUOTE", identifier, order.supplier_code)
            self.connection.execute("""INSERT INTO reconforge.procurement_sourcing_quotes(tenant_id,id,requisition_id,supplier_id,supplier_code,
                total_minor,payload,quote_digest,registrar_actor_id,created_version) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, quote_id, identifier, supplier["id"], order.supplier_code, total, canonical_json(payload),
                 digest_payload(payload), actor.user_id, expected_version + 1))
            self.connection.execute("UPDATE reconforge.procurement_sourcing_requisitions SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, identifier))
            return self._remember(self._row(identifier), "quote", command_id, request, digest, actor, quote.reason)

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, actor: PostingActor, expected_budget_version: int | None = None) -> dict[str, Any]:
        if operation not in {"open-rfq", "review-selection", "award", "cancel"}:
            raise ProcurementPartialError("procurement_sourcing_operation_invalid", "The sourcing command is not recognized.")
        reason = exact_text(reason, maximum=500)
        request = {"requisition_id": identifier, "expected_version": expected_version, "reason": reason}
        if operation == "award":
            expected_budget_version = version(expected_budget_version)
            request["expected_budget_version"] = expected_budget_version
        elif expected_budget_version is not None:
            raise ProcurementPartialError("procurement_sourcing_operation_invalid", "Only an award may supply the current budget version.")
        with self.connection.transaction():
            row, digest, replay = self._begin(identifier, operation, expected_version, command_id, request, actor)
            if replay is not None:
                return replay
            if actor.user_id == row["creator_actor_id"]:
                raise ProcurementPartialError("procurement_sourcing_duties_conflict", "Approval, award and cancellation require an independent persisted human.")
            next_phase, selected = row["phase"], row["selected_quote_id"]
            if operation == "open-rfq" and row["phase"] == 0:
                next_phase = 1
            elif operation == "review-selection" and row["phase"] == 1:
                quotes = self.connection.execute("SELECT id,supplier_code,total_minor,registrar_actor_id FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=%s AND requisition_id=%s",
                    (self.tenant_id, identifier)).fetchall()
                if any(quote["registrar_actor_id"] == actor.user_id for quote in quotes):
                    raise ProcurementPartialError("procurement_sourcing_duties_conflict", "Selection reviewer cannot register any offer in the retained candidate set.")
                selected = deterministic_winner(tuple((quote["id"], quote["supplier_code"], quote["total_minor"]) for quote in quotes), row["ceiling_minor"])
                next_phase = 2
            elif operation == "award" and row["phase"] == 2:
                reviewers = self.connection.execute("SELECT actor_id FROM reconforge.procurement_sourcing_events WHERE tenant_id=%s AND requisition_id=%s AND operation IN('open-rfq','review-selection')",
                    (self.tenant_id, identifier)).fetchall()
                quote = self.purchase._one("SELECT * FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, selected))
                if actor.user_id in {quote["registrar_actor_id"], *(review["actor_id"] for review in reviewers)}:
                    raise ProcurementPartialError("procurement_sourcing_duties_conflict", "Award publication requires the third independent human beyond preparation and both approvals.")
                order = dict(quote["payload"]["order"])
                order["lines"] = tuple(ProcurementOrderLine(**line) for line in order["lines"])
                if expected_budget_version is None:
                    raise ProcurementPartialError("procurement_sourcing_budget_version", "Award requires its exact current appropriation version.")
                self.commitments.create(BudgetPurchasePreparation(budget_id=row["budget_id"], expected_budget_version=expected_budget_version,
                    order=MultilineProcurementPreparation(**order), reason=reason), command_id=platform_id("PSAWARD", identifier, command_id), actor=actor)
                next_phase = 3
            elif operation == "cancel" and row["phase"] in (0, 1, 2):
                next_phase = 4
            else:
                raise ProcurementPartialError("procurement_sourcing_state_conflict", "The exact current sourcing stage refuses this transition.")
            self.connection.execute("""UPDATE reconforge.procurement_sourcing_requisitions SET phase=%s,selected_quote_id=%s,row_version=row_version+1
                WHERE tenant_id=%s AND id=%s""", (next_phase, selected, self.tenant_id, identifier))
            return self._remember(self._row(identifier), operation, command_id, request, digest, actor, reason)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self.purchase._scope_transaction()
            row = self._row(identifier)
            self._actor(row, actor, "read")
            self.connection.execute("SELECT reconforge.ps_close(%s,%s)", (self.tenant_id, identifier))
            head = self.connection.execute("SELECT reconforge.ps_public(%s,%s,%s) value",
                (self.tenant_id, identifier, row["row_version"])).fetchone()["value"]
            quotes = self.connection.execute("SELECT id,payload,quote_digest,created_version FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=%s AND requisition_id=%s ORDER BY total_minor,supplier_code COLLATE \"C\"",
                (self.tenant_id, identifier)).fetchall()
            def exact(value: Any, key: str = "") -> Any:
                if isinstance(value, dict):
                    return {field: exact(part, field) for field, part in value.items()}
                if isinstance(value, list):
                    return [str(part) for part in value] if key == "unit_prices_minor" else [exact(part) for part in value]
                return str(value) if key.endswith(("_minor", "_scaled")) and type(value) is int else value
            return {"head": dict(head), "source": exact(row["payload"]), "canonical_source_json": canonical_json(row["payload"]),
                    "quotations": [{**dict(quote), "payload": exact(quote["payload"]),
                                    "canonical_quote_json": canonical_json(quote["payload"])} for quote in quotes]}

    def list_requisitions(self, workspace_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self.purchase._scope_transaction()
            rows = self.connection.execute("SELECT id FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=%s AND workspace_id=%s ORDER BY id LIMIT 25",
                (self.tenant_id, exact_text(workspace_id))).fetchall()
            return {"records": [self.get(row["id"], actor=actor)["head"] for row in rows]}

