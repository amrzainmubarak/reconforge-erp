"""Pre-stock engineering demand, exclusive native stock custody and SRC companions."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, replace
from json import loads
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text
from reconforge.domain.manufacturing_execution import exact_integer, expand_requirements, fail, quantity
from reconforge.domain.manufacturing_execution_v2 import ManufacturingOrderPreparation
from reconforge.domain.manufacturing_supply_plan import (
    PERMISSIONS,
    PURCHASE_OPERATIONS,
    READ,
    SupplyPlanPreparation,
    coverage_payload,
    plan_requirements,
    planned_requirement_payload,
    procurement_headroom,
    require_complete_handoff,
)
from reconforge.domain.procurement_operations import line_total
from reconforge.domain.procurement_partial import (
    MultilineInvoicePreparation,
    PartialQuantityPreparation,
    normalize_invoice_lines,
    normalize_part,
)
from reconforge.domain.procurement_sourcing import (
    RequisitionPreparation,
    SupplierQuotationPreparation,
    normalize_requisition,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import quantity_to_scaled


class _ManufacturingSupplyParticipant:
    """Finite live native source admission; a number prefix alone never admits."""

    def __init__(self, owner: PostgresManufacturingSupplyPlanRepository, source: Mapping[str, Any],
                 identifiers: frozenset[str]) -> None:
        self.owner = owner
        self.scope = tuple(source[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
        self.plan_id = str(source["id"])
        self.identifiers = identifiers

    def admits(self, connection: Any, tenant_id: str, identifier: str) -> bool:
        return (self.owner.connection is connection and self.owner.tenant_id == tenant_id and self.owner._active
                and self.owner._supply_participant is self and self.owner._locked_plan_id == self.plan_id
                and self.owner._locked_scope == self.scope and identifier in self.identifiers)


class PostgresManufacturingSupplyPlanRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.execution = PostgresManufacturingExecutionV2Repository(connection, tenant_id)
        self.material, self.owner = self.execution.material, self.execution.owner
        self.inventory = self.material.inventory
        self.sourcing = PostgresProcurementSourcingRepository(connection, tenant_id)
        self._active = False
        self._rollback_only = False
        self._supply_participant: _ManufacturingSupplyParticipant | None = None
        self._locked_plan_id: str | None = None
        self._locked_scope: tuple[str, ...] | None = None

    def command_receipt(self, identifier: str, command_id: str, response: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        """Read the exact immutable owner receipt under current caller authority.

        The API calls this inside the same outer business transaction. Historical
        response/operation/actor/native membership come from the original command,
        including replay; no current phase or request receipt is fabricated.
        """
        source = self._row(identifier, lock=True)
        retained = self.material._one("""SELECT * FROM reconforge.manufacturing_supply_commands
            WHERE tenant_id=%s AND workspace_id=%s AND plan_id=%s AND command_id=%s""",
            (self.tenant_id, source["workspace_id"], identifier, command_id))
        self._actor(actor, retained["operation"], source, lock=True)
        if retained["actor_id"] != actor.user_id or dict(response) != retained["response_json"]:
            fail("The response must be this human's exact immutable owner command.", "manufacturing_supply_command_conflict")
        self.connection.execute("SELECT reconforge.msp_evidence(%s,%s,%s)", (self.tenant_id, identifier, retained["version"]))
        return {"schema_version": "manufacturing-supply-command-ack-v1", "command_id": retained["command_id"],
            "plan_id": identifier, "source_digest": source["source_digest"], "version": retained["version"],
            "operation": retained["operation"], "actor_id": retained["actor_id"],
            "scope": {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "request_json": retained["request_json"], "request_digest": retained["request_digest"],
            "native_kind": retained["native_kind"], "native_owner_id": retained["native_owner_id"],
            "native_command_id": retained["native_command_id"]}

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self._active:
            fail("A supply owner cannot reenter another command.", "manufacturing_supply_command_conflict")
        with self.owner._transaction():
            self._active = True
            self._rollback_only = False
            try:
                yield
                if self._rollback_only:
                    fail("A failed native participant requires the full supply command to roll back.")
            finally:
                self._active = False
                self._locked_plan_id = None
                self._locked_scope = None

    def _row(self, identifier: str, *, lock: bool = False, read_lock: bool = False) -> dict[str, Any]:
        query = "SELECT * FROM reconforge.manufacturing_supply_plans WHERE tenant_id=%s AND id=%s"
        query += " FOR UPDATE" if lock else " FOR SHARE" if read_lock else ""
        row = self.material._one(query, (self.tenant_id, text(identifier, "plan_id")))
        result = {**row["payload"], **{key: row[key] for key in ("phase", "row_version", "source_digest",
                  "reviewer_actor_id", "material_order_id", "manufacturing_order_id")}}
        if lock:
            self._locked_plan_id = result["id"]
            self._locked_scope = tuple(result[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
        return result

    def _actor(self, actor: PostingActor, operation: str, source: Mapping[str, Any], *, lock: bool = False) -> None:
        financial = dict(source)
        if "ceiling_minor" in source:
            # Fractional quantities can have a small transaction total while the
            # retained/public unit price exceeds the reader's current amount cap.
            # Authorize every original financial value under captured precision.
            quoted = self.connection.execute("""SELECT GREATEST(COALESCE(max(quote.total_minor),0),
                COALESCE(max(unit.value::numeric),0)) highest FROM reconforge.procurement_sourcing_quotes quote
                JOIN reconforge.manufacturing_supply_procurement_claims claim ON claim.tenant_id=quote.tenant_id AND claim.requisition_id=quote.requisition_id
                LEFT JOIN LATERAL jsonb_array_elements(quote.payload#>'{quotation,unit_prices_minor}') unit(value) ON TRUE
                WHERE claim.tenant_id=%s AND claim.plan_id=%s""", (self.tenant_id, source["id"])).fetchone()["highest"]
            exposed = max(source["ceiling_minor"], int(quoted), *source["unit_price_ceilings_minor"].values())
            financial.update(amount_minor=exposed, currency_precision=source["monetary_policy"]["precision"])
        permission_operation = operation
        for permission in sorted(PERMISSIONS.get(permission_operation, READ)):
            self.owner._actor(actor, permission, financial, mutation=operation != "read")
        statement = """SELECT scope_type,scope_id FROM reconforge.principal_scope_grants WHERE tenant_id=%s
            AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
            AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
                OR(scope_type='legal_entity' AND scope_id=%s))"""
        if lock:
            statement += " FOR SHARE"
        grants = records(self.connection.execute(statement, (self.tenant_id, actor.user_id,
                         source["workspace_id"], source["organization_id"], source["legal_entity_id"])))
        if len({(row["scope_type"], row["scope_id"]) for row in grants}) != 3:
            fail("Supply planning requires every current persisted original scope grant.", "manufacturing_supply_scope_denied")
        if operation != "read":
            self.connection.execute("SELECT set_config('app.manufacturing_supply_actor_id',%s,true)", (actor.user_id,))
            self.connection.execute("SELECT set_config('app.manufacturing_supply_operation',%s,true)", (operation,))

    def _command(self, source: Mapping[str, Any], operation: str, command_id: str, request: Mapping[str, Any],
                 actor: PostingActor) -> tuple[dict[str, Any], dict[str, Any] | None]:
        command_id = text(command_id, "command_id", maximum=140)
        wire = loads(canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}))
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, source["workspace_id"], "manufacturing-supply", command_id]),))
        retained = self.connection.execute("""SELECT * FROM reconforge.manufacturing_supply_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, source["workspace_id"], command_id)).fetchone()
        if retained is None:
            return wire, None
        if retained["request_json"] != wire or retained["request_digest"] != digest_payload(wire):
            fail("This command belongs to another exact source, actor or request.", "manufacturing_supply_command_conflict")
        current = self._row(retained["plan_id"], lock=True)
        self._actor(actor, operation, current, lock=True)
        if retained["native_kind"] == "SRC":
            # Exact replay still needs CURRENT native SRC operation and whole retained quote authority.
            self.sourcing._actor(self.sourcing._row(retained["native_owner_id"], read_lock=True), actor, operation.removeprefix("source-"))
        elif retained["native_kind"] in {"PP", "BPC"}:
            with self._purchase_context(current, retained["native_owner_id"]) as native:
                native.purchase._authorize(native.purchase._order(retained["native_owner_id"]), actor,
                    {"prepare-receipt-line": "prepare-receipt", "match-invoice-lines": "match-invoice"}.get(
                        PURCHASE_OPERATIONS[operation], PURCHASE_OPERATIONS[operation]))
        elif retained["native_kind"] == "ME2":
            self.execution._actor(actor, "create", self.execution._source(retained["native_owner_id"], read_lock=True), lock=True)
        self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, current["id"]))
        return wire, dict(retained["response_json"])

    def _remember(self, identifier: str, operation: str, command: str, wire: Mapping[str, Any],
                  actor: PostingActor, reason: str, *, native: Mapping[str, Any] | None = None) -> dict[str, Any]:
        source = self._row(identifier)
        self._actor(actor, operation, source, lock=True)
        metadata = {"source_digest": source["source_digest"], "version": source["row_version"], "operation": operation, "reason": reason}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="manufacturing_supply_plan", object_id=identifier,
            action="manufacturing_supply_plan." + operation, metadata=metadata)
        outbox = "OBX-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events
            (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
            VALUES(%s,%s,%s,'manufacturing_supply_plan',%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, outbox,
            "manufacturing_supply_plan." + operation, identifier, source["workspace_id"], source["organization_id"],
            source["legal_entity_id"], canonical_json({**metadata, "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_events
            (tenant_id,plan_id,version,operation,actor_id,request_json,request_digest,reason,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""", (self.tenant_id, identifier, source["row_version"],
            operation, actor.user_id, canonical_json(wire), digest_payload(wire), reason, audit.id, outbox))
        response = {"source": self.connection.execute("SELECT reconforge.msp_public(%s,%s,%s) value",
                    (self.tenant_id, identifier, source["row_version"])).fetchone()["value"]}
        if native is not None:
            response["native_response"] = native["response"]
        self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_commands
            (tenant_id,workspace_id,command_id,plan_id,version,operation,actor_id,request_json,request_digest,
             native_kind,native_owner_id,native_command_id,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, source["workspace_id"], command,
            identifier, source["row_version"], operation, actor.user_id, canonical_json(wire), digest_payload(wire),
            native["kind"] if native else None, native["id"] if native else None, native["command_id"] if native else None,
            canonical_json(response)))
        self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, identifier))
        return response

    def _pool_locks(self, source: Mapping[str, Any]) -> None:
        # ALL common gates precede ANY native physical/FIFO key; readonly get never calls this.
        pairs = {(line["item_id"], source["component_location_id"]) for line in source["requirements"]}
        pairs.add((source["output_item_id"], source["finished_location_id"]))
        for item in sorted({item for item, _ in pairs}):
            self.connection.execute("SELECT reconforge.inventory_quantity_source_pool_lock(%s,%s,%s,%s)",
                (self.tenant_id, source["workspace_id"], source["legal_entity_id"], item))
        self.material._inventory_locks(source)
        for item, location in sorted(pairs):
            self.connection.execute("SELECT reconforge.touch_inventory_quantity_claim_gate(%s,%s,%s,%s,%s)",
                (self.tenant_id, source["workspace_id"], source["legal_entity_id"], item, location))

    def _locked(self, source: Mapping[str, Any], actor: PostingActor, operation: str) -> dict[str, Any]:
        self.material._binding(source)
        self._pool_locks(source)
        source = self._row(source["id"], lock=True)
        self._actor(actor, operation, source, lock=True)
        self.material._admit(source)
        return source

    def create(self, request: SupplyPlanPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        material = args["material"]
        with self._transaction():
            self._actor(actor, "create", material)
            wire, replay = self._command(material, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self.material._binding(material)
            bom = self.material._bom(material["bom_version_id"])
            self.material._actor(actor, "read", bom)
            routing = self.execution._source(request.routing_id, read_lock=True)
            self.execution._actor(actor, "read", routing, lock=True)
            if bom["phase"] != 1 or routing["kind"] != "Routing" or routing["phase"] != 1 or routing["bom_version_id"] != bom["id"]:
                fail("Supply planning requires an actual approved BOM and matching approved engineering routing.")
            if any(bom[key] != material[key] or routing[key] != material[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                fail("All engineering demand sources require the exact original hierarchy.")
            if not routing["effective_from"] <= material["posting_date"] <= routing["effective_until"]:
                fail("Approved routing is not effective on the original plan business date.")
            planned = quantity(material["output_quantity"], bom["output"]["quantity_precision"])
            requirements = expand_requirements(bom["components"], bom["output_quantity_scaled"], planned)
            if set(request.unit_price_ceilings_minor) != {line["item_code"] for line in requirements}:
                fail("Every original component needs exactly one retained native purchase-price ceiling.")
            mapping = self.material._mapping(material)
            locations = {}
            for name in ("component", "finished"):
                location = self.inventory._location_reference(material["workspace_id"], material["organization_id"],
                    material["legal_entity_id"], material[name + "_location_code"])
                if location is None:
                    fail("Planning requires actual scoped component and finished locations.")
                locations[name + "_location_id"] = location["id"]
            unit = self.material._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active",
                                      (self.tenant_id, mapping["currency_code"]))
            monetary, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(workspace_id=material["workspace_id"],
                currency_code=mapping["currency_code"], minor_units=unit["minor_units"], actor_label=actor.username)
            budget = self.sourcing.budgets._row(BudgetScope(*(material[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))), request.budget_id)
            if budget["status"] != "Approved" or (budget["currency_code"], budget["period_id"], budget["currency_precision"]) != (
                    mapping["currency_code"], material["period_id"], monetary.precision):
                fail("A current approved same-scope native budget and original monetary precision are required.")
            identifier = "MSP1-" + uuid4().hex.upper()
            for line in requirements:
                line["requirement_id"] = "MSP1D-" + digest_payload([self.tenant_id, identifier, line["item_id"]])[:32].upper()
            source = {**material, **mapping, **locations, "schema_version": args["schema_version"], "command_request": args,
                "id": identifier, "creator_id": actor.user_id, "bom_digest": bom["source_digest"], "routing_id": routing["id"],
                "routing_digest": routing["source_digest"], "budget_id": request.budget_id, "output": bom["output"],
                "output_item_id": bom["output"]["item_id"], "output_quantity_scaled": planned, "requirements": requirements,
                "unit_price_ceilings_minor": args["unit_price_ceilings_minor"], "monetary_policy": asdict(monetary),
                "ceiling_minor": exact_integer(sum(line_total(line["required_quantity"], request.unit_price_ceilings_minor[line["item_code"]])[1]
                                                    for line in requirements), positive=True)}
            digest = digest_payload(source)
            self.material._admit(source)
            self._pool_locks(source)
            self._actor(actor, "create", source, lock=True)
            self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_plans
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,number,bom_version_id,routing_id,budget_id,payload,source_digest,creator_actor_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, identifier, source["workspace_id"],
                source["organization_id"], source["legal_entity_id"], source["number"], bom["id"], routing["id"], request.budget_id,
                canonical_json(source), digest, actor.user_id))
            for sequence, line in enumerate(requirements, 1):
                payload = planned_requirement_payload(identifier=line["requirement_id"], plan={**source, "source_digest": digest},
                                                      component=line, sequence=sequence)
                self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_requirements
                    (tenant_id,id,plan_id,sequence,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,
                     gross_quantity_scaled,payload,source_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                    (self.tenant_id, payload["id"], identifier, sequence, source["workspace_id"], source["organization_id"], source["legal_entity_id"],
                     line["item_id"], line["uom_id"], line["quantity_precision"], source["component_location_id"], line["required_quantity_scaled"],
                     canonical_json(payload), digest_payload(payload)))
            return self._remember(identifier, "create", command_id, wire, actor, material["reason"])

    def _observations(self, source: Mapping[str, Any]) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        available: dict[str, int] = {}
        reserved: dict[str, int] = {}
        fifo: dict[str, int] = {}
        for component in source["requirements"]:
            item, location = component["item_id"], source["component_location_id"]
            parameters = (self.tenant_id, source["workspace_id"], source["legal_entity_id"], item, location)
            if self.connection.execute("""SELECT 1 FROM reconforge.inventory_movement_lines line
                JOIN reconforge.inventory_movements movement ON movement.tenant_id=line.tenant_id AND movement.id=line.movement_id
                WHERE line.tenant_id=%s AND movement.workspace_id=%s AND movement.legal_entity_id=%s AND line.item_id=%s
                AND movement.status='Posted' AND line.inventory_lot_id IS NULL AND(line.to_location_id=%s OR line.from_location_id=%s)
                AND(line.uom_id,line.quantity_precision) IS DISTINCT FROM(%s,%s) LIMIT 1""",
                (*parameters, location, component["uom_id"], component["quantity_precision"])).fetchone():
                fail("Existing physical stock differs from the original required base UOM/precision; refuse reinterpretation.",
                     "manufacturing_supply_capacity_invalid")
            available[item] = int(self.connection.execute("""SELECT COALESCE(sum(CASE WHEN line.to_location_id=%s THEN line.quantity_scaled ELSE 0 END
                -CASE WHEN line.from_location_id=%s THEN line.quantity_scaled ELSE 0 END),0) n
                FROM reconforge.inventory_movement_lines line JOIN reconforge.inventory_movements movement
                ON movement.tenant_id=line.tenant_id AND movement.id=line.movement_id
                WHERE line.tenant_id=%s AND movement.workspace_id=%s AND movement.legal_entity_id=%s AND line.item_id=%s
                AND movement.status='Posted' AND line.inventory_lot_id IS NULL""", (location, location, *parameters[:-1])).fetchone()["n"])
            reserved[item] = int(self.connection.execute("""SELECT COALESCE(sum(n),0) n FROM (
                SELECT quantity_scaled n FROM reconforge.stock_sales_reservations WHERE tenant_id=%s AND workspace_id=%s AND legal_entity_id=%s
                AND item_id=%s AND location_id=%s AND state='Active'
                UNION ALL SELECT quantity_scaled FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=%s AND workspace_id=%s AND legal_entity_id=%s
                AND item_id=%s AND location_id=%s AND state='Active'
                UNION ALL SELECT guard.quantity_scaled FROM reconforge.inventory_quantity_source_guards guard WHERE guard.tenant_id=%s
                AND guard.workspace_id=%s AND guard.legal_entity_id=%s AND guard.item_id=%s AND guard.location_id=%s
                AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases release WHERE release.tenant_id=guard.tenant_id AND release.guard_id=guard.id)
                ) original""", parameters * 3).fetchone()["n"])
            fifo[item] = int(self.connection.execute("SELECT reconforge.inventory_quantity_free_fifo(%s,%s,%s,%s) n", parameters[:-1]).fetchone()["n"])
        return available, reserved, fifo

    def approve(self, identifier: str, *, expected_digest: str, command_id: str, reason: str,
                actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, "approve", source)
            request = {"id": identifier, "expected_digest": expected_digest, "reason": reason}
            wire, replay = self._command(source, "approve", command_id, request, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, "approve")
            if source["phase"] != 0 or source["source_digest"] != expected_digest or source["creator_id"] == actor.user_id:
                fail("Net coverage approval requires the exact Draft source and an independent current human.")
            physical, reserved, fifo = self._observations(source)
            bom = self.material._bom(source["bom_version_id"])
            expanded = plan_requirements(bom["components"], batch_output_scaled=bom["output_quantity_scaled"],
                planned_output_scaled=source["output_quantity_scaled"], available_scaled=physical, active_reserved_scaled=reserved, fifo_free_scaled=fifo)
            original_ids = {line["item_id"]: line["requirement_id"] for line in source["requirements"]}
            for component in expanded:
                row = self.material._one("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND id=%s",
                                          (self.tenant_id, original_ids[component["item_id"]]))
                coverage = coverage_payload(row, component)
                self.connection.execute("""UPDATE reconforge.manufacturing_supply_requirements SET onhand_reserved_scaled=%s,shortage_quantity_scaled=%s,
                    coverage_json=%s::jsonb,coverage_digest=%s WHERE tenant_id=%s AND id=%s""", (coverage["onhand_reserved_scaled"],
                    coverage["shortage_quantity_scaled"], canonical_json(coverage), digest_payload(coverage), self.tenant_id, row["id"]))
                if coverage["onhand_reserved_scaled"]:
                    claim = "MSP1K-" + uuid4().hex.upper()
                    self._stock_claim(source, row, claim, coverage["onhand_reserved_scaled"], "OnHand", None, 2)
            self.connection.execute("UPDATE reconforge.manufacturing_supply_plans SET phase=1,row_version=row_version+1,reviewer_actor_id=%s WHERE tenant_id=%s AND id=%s",
                                    (actor.user_id, self.tenant_id, identifier))
            return self._remember(identifier, "approve", command_id, wire, actor, reason)

    def _stock_claim(self, source: Mapping[str, Any], requirement: Mapping[str, Any], identifier: str, quantity_scaled: int,
                     origin: str, receipt_plan_id: str | None, version: int) -> None:
        values = (self.tenant_id, identifier, source["id"], requirement["id"], source["workspace_id"], source["organization_id"],
                  source["legal_entity_id"], requirement["item_id"], requirement["uom_id"], requirement["quantity_precision"],
                  requirement["location_id"], quantity_scaled, origin, receipt_plan_id, version)
        self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_stock_claims
            (tenant_id,id,plan_id,requirement_id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,
             quantity_scaled,origin,native_receipt_plan_id,created_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values)
        self.connection.execute("""INSERT INTO reconforge.inventory_quantity_source_guards
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,quantity_scaled,
             owner_namespace,owner_claim_id,source_receipt_plan_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MSP1',%s,%s)""",
            (self.tenant_id, identifier, source["workspace_id"], source["organization_id"], source["legal_entity_id"], requirement["item_id"],
             requirement["uom_id"], requirement["quantity_precision"], requirement["location_id"], quantity_scaled, identifier, receipt_plan_id))

    def cancel(self, identifier: str, *, expected_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, "cancel", source)
            wire, replay = self._command(source, "cancel", command_id,
                {"id": identifier, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, "cancel")
            if source["source_digest"] != expected_digest or source["phase"] not in {0, 1}:
                fail("Only original unhanded planning custody can be cancelled.")
            if self.connection.execute("SELECT 1 FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=%s AND plan_id=%s AND state<>'Released'",
                                       (self.tenant_id, identifier)).fetchone():
                fail("Cancel the actual unawarded native requisitions before releasing the planner; awarded native purchasing remains retained.")
            for claim in records(self.connection.execute("SELECT * FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=%s AND plan_id=%s AND state='Active' ORDER BY id",
                                                         (self.tenant_id, identifier))):
                release = "MSP1X-" + uuid4().hex.upper()
                self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_stock_releases
                    (tenant_id,id,plan_id,claim_id,workspace_id,organization_id,legal_entity_id,purpose,actor_id,reason,created_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,'Cancel',%s,%s,%s)""", (self.tenant_id, release, identifier, claim["id"],
                    source["workspace_id"], source["organization_id"], source["legal_entity_id"], actor.user_id, reason, source["row_version"] + 1))
                self.connection.execute("INSERT INTO reconforge.inventory_quantity_source_releases(tenant_id,guard_id,release_id) VALUES(%s,%s,%s)",
                                        (self.tenant_id, claim["id"], release))
                self.connection.execute("UPDATE reconforge.manufacturing_supply_stock_claims SET state='Released' WHERE tenant_id=%s AND id=%s",
                                        (self.tenant_id, claim["id"]))
            self.connection.execute("UPDATE reconforge.manufacturing_supply_plans SET phase=3,row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            return self._remember(identifier, "cancel", command_id, wire, actor, reason)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._row(identifier, read_lock=True)
            self._actor(actor, "read", source, lock=True)
            self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, identifier))
            return dict(self.connection.execute("SELECT reconforge.msp_public(%s,%s,%s) value",
                        (self.tenant_id, identifier, source["row_version"])).fetchone()["value"])

    def get_requirement(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            row = self.material._one("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND id=%s",
                                      (self.tenant_id, text(identifier, "requirement_id")))
            source = self._row(row["plan_id"], read_lock=True)
            self._actor(actor, "read", source, lock=True)
            row = self.material._one("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND id=%s AND plan_id=%s",
                                      (self.tenant_id, identifier, source["id"]))
            self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, source["id"]))
            return {**row["payload"], "source_digest": row["source_digest"], "coverage": row["coverage_json"], "coverage_digest": row["coverage_digest"]}

    def list_plans(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        self._actor(actor, "read", scope)
        rows = records(self.connection.execute("""SELECT id FROM reconforge.manufacturing_supply_plans
            WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id LIMIT 25""",
            (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
        return {"records": [self.get(row["id"], actor=actor) for row in rows]}

    def get_requisition(self, identifier: str, requisition_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            source = self._row(identifier, lock=True)
            self._actor(actor, "read", source, lock=True)
            native_row = self.material._one("""SELECT DISTINCT requisition.* FROM reconforge.procurement_sourcing_requisitions requisition
                JOIN reconforge.manufacturing_supply_procurement_claims claim ON claim.tenant_id=requisition.tenant_id AND claim.requisition_id=requisition.id
                WHERE claim.tenant_id=%s AND claim.plan_id=%s AND requisition.id=%s""", (self.tenant_id, identifier, requisition_id))
            self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, identifier))
            with self._supply_context(source, frozenset({requisition_id, native_row["number"], native_row["order_id"], "BPC1-" + native_row["number"]})) as native:
                return native.get(requisition_id, actor=actor)

    @contextmanager
    def _supply_context(self, source: Mapping[str, Any], identifiers: frozenset[str]) -> Iterator[PostgresProcurementSourcingRepository]:
        if not self._active or self._supply_participant is not None or self._locked_plan_id != source["id"]:
            fail("Planned sourcing requires its exact active prelocked owning plan.")
        participant = _ManufacturingSupplyParticipant(self, source, identifiers)
        self._supply_participant = participant
        try:
            yield PostgresProcurementSourcingRepository(self.connection, self.tenant_id, _supply_participant=participant)
        except BaseException:
            self._rollback_only = True
            raise
        finally:
            self._supply_participant = None

    def create_requisition(self, identifier: str, request: RequisitionPreparation, *, requirement_ids: tuple[str, ...],
                           expected_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request, _ = normalize_requisition(request)
        if (not request.order.number.startswith("SRC5-MSP-") or len(request.order.number) != 25
                or any(value is not None for value in request.requirements)
                or not isinstance(requirement_ids, tuple) or len(requirement_ids) != len(request.order.lines)
                or len(set(requirement_ids)) != len(requirement_ids)):
            fail("Planned requisitions need an exact distinct requirement companion and original SRC1 unlinked format.")
        native_request = asdict(request)
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, "source-create", source)
            wire, replay = self._command(source, "source-create", command_id, {"id": identifier, "expected_digest": expected_digest,
                "requirement_ids": list(requirement_ids), "native_request": native_request}, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, "source-create")
            if source["phase"] != 1 or source["source_digest"] != expected_digest:
                fail("Only approved current original net demand can create a native requisition.")
            order = request.order
            if (request.budget_id, order.workspace, order.organization_code, order.entity_code, order.period_id, order.posting_date,
                    order.currency_code, order.journal_code) != (source["budget_id"], source["workspace_id"], source["organization_code"],
                    source["entity_code"], source["period_id"], source["posting_date"], source["currency_code"], source["journal_code"]):
                fail("Native source must retain original plan hierarchy, period, policy and approved budget.")
            claims = []
            for index, (requirement_id, line) in enumerate(zip(requirement_ids, order.lines, strict=True), 1):
                requirement = self.material._one("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND id=%s AND plan_id=%s",
                                                (self.tenant_id, text(requirement_id, "requirement_id"), identifier))
                quantities = [row["quantity_scaled"] for row in records(self.connection.execute("""SELECT quantity_scaled
                    FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=%s AND requirement_id=%s AND state<>'Released' ORDER BY id""",
                    (self.tenant_id, requirement_id)))]
                proposed = quantity_to_scaled(line.quantity, decimal_places=requirement["quantity_precision"])
                if (proposed > procurement_headroom(requirement["shortage_quantity_scaled"], quantities)
                        or line.item_code != requirement["payload"]["item_code"] or line.location_code != source["component_location_code"]
                        or line.policy_code != source["component_policy_code"]
                        or line.unit_price_minor != source["unit_price_ceilings_minor"][line.item_code]):
                    fail("Requisition cannot exceed unclaimed net shortage or change its original item/location/UOM/purchase ceiling.")
                claims.append((index, requirement, proposed))
            requisition_id = platform_id("PSREQ", source["workspace_id"], order.number)
            purchase_number = "BPC1-" + order.number
            purchase_id = platform_id("PPORDER", source["workspace_id"], purchase_number)
            native_command = platform_id("MSPSRC", identifier, command_id)
            with self._supply_context(source, frozenset({order.number, requisition_id, purchase_number, purchase_id})) as native:
                response = native.create(request, command_id=native_command, actor=actor)
            for index, requirement, proposed in claims:
                claim_id = "MSP1Q-" + uuid4().hex.upper()
                payload = {"schema_version": "manufacturing-planned-origin-v2", "id": claim_id, "plan_id": identifier,
                    "plan_digest": source["source_digest"], "requirement_id": requirement["id"], "requirement_digest": requirement["source_digest"],
                    "coverage_digest": requirement["coverage_digest"], "requisition_id": requisition_id, "source_line": index,
                    "quantity_scaled": proposed, "scope": {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                    **{key: requirement[key] for key in ("item_id", "uom_id", "quantity_precision", "location_id")}}
                self.connection.execute("""INSERT INTO reconforge.manufacturing_supply_procurement_claims
                    (tenant_id,id,plan_id,requirement_id,workspace_id,organization_id,legal_entity_id,quantity_scaled,requisition_id,
                     source_line,payload,source_digest,created_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                    (self.tenant_id, claim_id, identifier, requirement["id"], source["workspace_id"], source["organization_id"], source["legal_entity_id"],
                     proposed, requisition_id, index, canonical_json(payload), digest_payload(payload), source["row_version"] + 1))
            self.connection.execute("UPDATE reconforge.manufacturing_supply_plans SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            return self._remember(identifier, "source-create", command_id, wire, actor, request.reason,
                                  native={"kind": "SRC", "id": requisition_id, "command_id": native_command, "response": response})

    def act_requisition(self, identifier: str, requisition_id: str, operation: str, *, expected_version: int,
                        command_id: str, reason: str, actor: PostingActor, expected_budget_version: int | None = None,
                        quotation: SupplierQuotationPreparation | None = None) -> dict[str, Any]:
        if operation not in {"open-rfq", "quote", "review-selection", "award", "cancel"}:
            fail("Unknown planned native requisition operation.")
        reason = text(reason, "reason", maximum=500)
        if operation == "quote":
            if quotation is None:
                fail("A quote operation requires one complete native supplier quotation.")
            native_request = {"requisition_id": requisition_id, "expected_version": expected_version, "quotation": asdict(quotation)}
            reason = quotation.reason
        else:
            if quotation is not None:
                fail("Only quote registration may contain a supplier quotation.")
            native_request = {"requisition_id": requisition_id, "expected_version": expected_version, "reason": reason}
            if operation == "award":
                native_request["expected_budget_version"] = expected_budget_version
        owner_operation = "source-" + operation
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, owner_operation, source)
            wire, replay = self._command(source, owner_operation, command_id, {"id": identifier, "native_request": native_request}, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, owner_operation)
            if source["phase"] != 1 or not self.connection.execute("SELECT 1 FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=%s AND plan_id=%s AND requisition_id=%s",
                                                                  (self.tenant_id, identifier, requisition_id)).fetchone():
                fail("Native requisition must belong to this active original planner.")
            native_row = self.sourcing._row(requisition_id)
            native_command = platform_id("MSPSRC", identifier, command_id)
            with self._supply_context(source, frozenset({requisition_id, native_row["number"], native_row["order_id"], "BPC1-" + native_row["number"]})) as native:
                response = (native.record_quotation(requisition_id, quotation, expected_version=expected_version,
                            command_id=native_command, actor=actor) if quotation is not None else
                            native.act(requisition_id, operation, expected_version=expected_version, command_id=native_command,
                            reason=reason, actor=actor, expected_budget_version=expected_budget_version))
            if operation == "cancel":
                self.connection.execute("UPDATE reconforge.manufacturing_supply_procurement_claims SET state='Released' WHERE tenant_id=%s AND requisition_id=%s",
                                        (self.tenant_id, requisition_id))
            self.connection.execute("UPDATE reconforge.manufacturing_supply_plans SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            return self._remember(identifier, owner_operation, command_id, wire, actor, reason,
                                  native={"kind": "SRC", "id": requisition_id, "command_id": native_command, "response": response})

    @contextmanager
    def _purchase_context(self, source: Mapping[str, Any], order_id: str) -> Iterator[PostgresProcurementSourcingRepository]:
        requisition = self.material._one("""SELECT DISTINCT requisition.* FROM reconforge.procurement_sourcing_requisitions requisition
            JOIN reconforge.manufacturing_supply_procurement_claims claim ON claim.tenant_id=requisition.tenant_id AND claim.requisition_id=requisition.id
            WHERE claim.tenant_id=%s AND claim.plan_id=%s AND requisition.order_id=%s AND requisition.phase=3""",
            (self.tenant_id, source["id"], text(order_id, "order_id")))
        with self._supply_context(source, frozenset({order_id, requisition["id"], requisition["number"], "BPC1-" + requisition["number"]})) as native:
            yield native

    def get_purchase(self, identifier: str, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            source = self._row(identifier, lock=True)
            self._actor(actor, "read", source, lock=True)
            self.connection.execute("SELECT reconforge.msp_close(%s,%s)", (self.tenant_id, identifier))
            with self._purchase_context(source, order_id) as native:
                return native.purchase.get(order_id, actor=actor)

    def procurement_operation(self, identifier: str, order_id: str, operation: str, *, expected_version: int,
                              command_id: str, reason: str, actor: PostingActor, line_id: str | None = None,
                              document_id: str | None = None, quantity_request: PartialQuantityPreparation | None = None,
                              invoice_request: MultilineInvoicePreparation | None = None,
                              expected_budget_version: int | None = None) -> dict[str, Any]:
        if operation not in PURCHASE_OPERATIONS:
            fail("Unknown native supply receiving or AP operation.")
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, operation, source)
            native_operation = PURCHASE_OPERATIONS[operation]
            native_request: dict[str, Any] = {"expected_version": expected_version, "reason": reason, "document_id": document_id}
            if operation == "receive-prepare":
                if quantity_request is None or line_id is None or invoice_request is not None or document_id is not None:
                    fail("Receipt preparation requires one exact owned line and typed quantity request.")
                price = self.material._one("SELECT unit_price_minor FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                    (self.tenant_id, order_id, line_id))["unit_price_minor"]
                quantity_request, _ = normalize_part(quantity_request, price)
                reason = quantity_request.reason
                native_request = {**asdict(quantity_request), "line_id": line_id, "expected_version": expected_version}
            elif operation == "invoice-match":
                if invoice_request is None or quantity_request is not None or line_id is not None or document_id is not None:
                    fail("Invoice matching requires a complete typed exact native line allocation.")
                invoice_request = normalize_invoice_lines(invoice_request)
                normalized_lines = []
                for allocation in invoice_request.lines:
                    price = self.material._one("SELECT unit_price_minor FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                        (self.tenant_id, order_id, allocation.line_id))["unit_price_minor"]
                    normalized, _ = normalize_part(PartialQuantityPreparation(quantity=allocation.quantity, posting_date=invoice_request.posting_date,
                        period_id=invoice_request.period_id, reason=invoice_request.reason), price)
                    normalized_lines.append(replace(allocation, quantity=normalized.quantity))
                invoice_request = replace(invoice_request, lines=tuple(normalized_lines))
                reason = invoice_request.reason
                native_request = {**asdict(invoice_request), "expected_version": expected_version}
            else:
                if (quantity_request is not None or invoice_request is not None or line_id is not None
                        or (document_id is None) != (operation in {"purchase-submit", "purchase-approve"})):
                    fail("Native document transition requires one original owned receipt or invoice.")
                if operation == "invoice-post":
                    if expected_budget_version is None:
                        fail("AP publication requires its current budget version.")
                    native_request = {"order_id": order_id, "invoice_id": document_id, "expected_order_version": expected_version,
                                      "expected_budget_version": expected_budget_version, "reason": reason}
            wire, replay = self._command(source, operation, command_id, {"id": identifier, "order_id": order_id,
                "native_operation": native_operation, "native_request": native_request}, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, operation)
            if source["phase"] != 1:
                fail("Actual receiving and AP require the active original approved supply owner.")
            native_command = platform_id("MSPPP", identifier, command_id)
            with self._purchase_context(source, order_id) as native:
                if operation == "receive-prepare":
                    if quantity_request is None or line_id is None:
                        fail("Receipt preparation requires one exact owned line and typed quantity request.")
                    native.purchase.prepare_receipt_line(order_id, line_id, quantity_request,
                        expected_version=expected_version, command_id=native_command, actor=actor)
                elif operation == "invoice-match":
                    if invoice_request is None:
                        fail("Invoice matching requires a complete typed exact native line allocation.")
                    native.purchase.match_invoice_lines(order_id, invoice_request, expected_version=expected_version,
                        command_id=native_command, actor=actor)
                elif operation == "invoice-post":
                    if document_id is None:
                        fail("AP publication requires its original owned invoice.")
                    if expected_budget_version is None:
                        fail("AP publication requires its current budget version.")
                    native.commitments.consume_invoice(order_id, document_id, expected_order_version=expected_version,
                        expected_budget_version=expected_budget_version, command_id=native_command, reason=reason, actor=actor)
                else:
                    native.purchase.act(order_id, native_operation, expected_version=expected_version,
                        command_id=native_command, reason=reason, document_id=document_id, actor=actor)
                if operation == "receive-commit":
                    receipt = self.material._one("""SELECT receipt.*,claim.requirement_id,requirement.quantity_precision
                        FROM reconforge.procurement_partial_receipts receipt JOIN reconforge.procurement_partial_order_lines line
                        ON line.tenant_id=receipt.tenant_id AND line.id=receipt.order_line_id
                        JOIN reconforge.procurement_sourcing_requisitions requisition ON requisition.tenant_id=line.tenant_id AND requisition.order_id=line.order_id
                        JOIN reconforge.manufacturing_supply_procurement_claims claim
                        ON claim.tenant_id=requisition.tenant_id AND claim.requisition_id=requisition.id AND claim.source_line=line.sequence
                        JOIN reconforge.manufacturing_supply_requirements requirement ON requirement.tenant_id=claim.tenant_id AND requirement.id=claim.requirement_id
                        WHERE receipt.tenant_id=%s AND receipt.order_id=%s AND receipt.id=%s AND claim.plan_id=%s AND receipt.stage=2""",
                        (self.tenant_id, order_id, document_id, identifier))
                    requirement = self.material._one("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND id=%s AND plan_id=%s",
                        (self.tenant_id, receipt["requirement_id"], identifier))
                    self._stock_claim(source, requirement, "MSP1K-" + uuid4().hex.upper(),
                        quantity_to_scaled(receipt["quantity_text"], decimal_places=receipt["quantity_precision"]), origin="Receipt",
                        receipt_plan_id=receipt["receipt_plan_id"], version=source["row_version"] + 1)
            self.connection.execute("UPDATE reconforge.manufacturing_supply_plans SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, identifier))
            retained_query = (
                "SELECT response_json FROM reconforge.procurement_commitment_commands "
                "WHERE tenant_id=%s AND workspace_id=%s AND order_id=%s AND command_id=%s"
                if operation == "invoice-post" else
                "SELECT response_json FROM reconforge.procurement_partial_commands "
                "WHERE tenant_id=%s AND workspace_id=%s AND order_id=%s AND command_id=%s")
            retained = self.material._one(retained_query,
                (self.tenant_id, source["workspace_id"], order_id, native_command))
            return self._remember(identifier, operation, command_id, wire, actor, reason,
                native={"kind": "BPC" if operation == "invoice-post" else "PP", "id": order_id,
                        "command_id": native_command, "response": retained["response_json"]})

    def handoff(self, identifier: str, request: ManufacturingOrderPreparation, *, expected_digest: str,
                command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            source = self._row(identifier)
            self._actor(actor, "handoff", source)
            wire, replay = self._command(source, "handoff", command_id,
                {"id": identifier, "expected_digest": expected_digest, "reason": reason, "native_request": args}, actor)
            if replay is not None:
                return replay
            source = self._locked(source, actor, "handoff")
            if (source["phase"] != 1 or source["source_digest"] != expected_digest
                    or {key: value for key, value in args["material"].items() if key != "posting_date"} !=
                       {key: value for key, value in source["command_request"]["material"].items() if key != "posting_date"}
                    or request.material.posting_date < source["posting_date"] or args["routing_id"] != source["routing_id"]):
                fail("Handoff must retain the complete original approved material request and routing.")
            for requirement in records(self.connection.execute("SELECT * FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=%s AND plan_id=%s ORDER BY sequence",
                    (self.tenant_id, identifier))):
                received = [row["quantity_scaled"] for row in records(self.connection.execute("""SELECT quantity_scaled
                    FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=%s AND requirement_id=%s AND origin='Receipt' AND state='Active' ORDER BY id""",
                    (self.tenant_id, requirement["id"])))]
                require_complete_handoff(requirement["gross_quantity_scaled"], requirement["onhand_reserved_scaled"], received)
            self.connection.execute("SELECT reconforge.msp_handoff_ready(%s,%s)", (self.tenant_id, identifier))
            native_command = platform_id("MSPME2", identifier, command_id)
            # The owned native INSERT adapter transfers guards only after an
            # actual ME1 row exists and before its ordinary capacity/reservation
            # checks. Deferred exact owner closure forbids detached invocation.
            self.connection.execute("SELECT set_config('app.manufacturing_supply_handoff_plan_id',%s,true)", (identifier,))
            self.connection.execute("SELECT set_config('app.manufacturing_supply_handoff_reason',%s,true)", (reason,))
            try:
                response = self.execution.create_order(request, command_id=native_command, actor=actor)
            except BaseException:
                self._rollback_only = True
                raise
            finally:
                self.connection.execute("SELECT set_config('app.manufacturing_supply_handoff_plan_id','',true)")
                self.connection.execute("SELECT set_config('app.manufacturing_supply_handoff_reason','',true)")
            self.connection.execute("UPDATE reconforge.manufacturing_supply_procurement_claims SET state='HandedOff' WHERE tenant_id=%s AND plan_id=%s AND state='Active'",
                (self.tenant_id, identifier))
            self.connection.execute("""UPDATE reconforge.manufacturing_supply_plans SET phase=2,row_version=row_version+1,
                material_order_id=%s,manufacturing_order_id=%s WHERE tenant_id=%s AND id=%s""",
                (response["material_order_id"], response["id"], self.tenant_id, identifier))
            self._actor(actor, "handoff", self._row(identifier))
            return self._remember(identifier, "handoff", command_id, wire, actor, reason,
                native={"kind": "ME2", "id": response["id"], "command_id": native_command, "response": response})
