"""One native owner for actual-material production and partial disposition."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation, artifact_id, source_plan_id
from reconforge.domain.manufacturing_execution import (
    MAX_COMPLETIONS,
    PERMISSIONS,
    READ,
    BomPreparation,
    OrderPreparation,
    allocate_disposition,
    business_date,
    exact_integer,
    expand_requirements,
    fail,
    quantity,
    requirement_payload,
)
from reconforge.domain.stock_sales import freeze_fifo
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_quantity_coordination import lock_inventory_quantity_pools
from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import minor_to_text, quantity_to_scaled, scaled_to_text


class _ManufacturingPostingParticipant:
    def __init__(self, owner: PostgresManufacturingExecutionRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner._active
                and self.owner.connection is connection and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class _ManufacturingReceiptParticipant:
    def __init__(self, owner: PostgresManufacturingExecutionRepository, completion_id: str, plan_id: str | None) -> None:
        self.owner, self.completion_id, self.plan_id = owner, completion_id, plan_id

    def admits(self, connection: Any, tenant_id: str, identifier: str) -> bool:
        return (self.owner._receipt_participant is self and self.owner._active and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and identifier in {self.completion_id, self.plan_id})


class PostgresManufacturingExecutionRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.inventory = PostgresInventoryCoreRepository(connection, tenant_id)
        self.receipts = PostgresInventoryReceiptPostingRepository(connection, tenant_id, strict_command_actor=True)
        self._participant: _ManufacturingPostingParticipant | None = None
        self._receipt_participant: _ManufacturingReceiptParticipant | None = None
        self._active = False
        self._rollback_only = False

    @contextmanager
    def _transaction(self, *, write: bool = True) -> Iterator[None]:
        if write and self._active:
            fail("A manufacturing command cannot reenter its exact owner transaction.")
        with self.owner._transaction():
            was_active = self._active
            self._active = True
            if write:
                self._rollback_only = False
            try:
                yield
                if write and self._rollback_only:
                    fail("A failed native participant requires the complete manufacturing command to roll back.")
            finally:
                self._active = was_active

    @contextmanager
    def _receipt_context(self, completion_id: str, plan_id: str | None) -> Iterator[_ManufacturingReceiptParticipant]:
        if not self._active or self._receipt_participant is not None:
            fail("Finished receipt requires its exact active manufacturing owner.")
        self._receipt_participant = _ManufacturingReceiptParticipant(self, completion_id, plan_id)
        try:
            yield self._receipt_participant
        except BaseException:
            self._rollback_only = True
            raise
        finally:
            self._receipt_participant = None

    def _one(self, statement: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        values = records(self.connection.execute(statement, parameters))
        if not values:
            fail("Manufacturing source is absent from the current hierarchy.", "manufacturing_execution_not_found")
        return values[0]

    def _actor(self, actor: PostingActor, operation: str, source: Mapping[str, Any]) -> None:
        # Every child exposes original batch cost, so authority covers the whole retained source.
        if source.get("order_id") and source.get("schema_version") == "manufacturing-completion-v1":
            self._actor(actor, operation, self._order(str(source["order_id"])))
        cost = source.get("issue_plan") or {}
        financial = {**source}
        if cost:
            financial.update(amount_minor=cost["total_cost_minor"], currency_precision=source["monetary_policy"]["precision"])
        for permission in sorted(PERMISSIONS.get(operation, READ)):
            self.owner._actor(actor, permission, financial, mutation=operation != "read")
        grants = self.connection.execute("""SELECT count(DISTINCT(scope_type,scope_id)) AS n
            FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s
            AND revoked_at IS NULL AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
            OR(scope_type='legal_entity' AND scope_id=%s))""", (self.tenant_id, actor.user_id,
            source["workspace_id"], source["organization_id"], source["legal_entity_id"])).fetchone()
        if grants["n"] != 3:
            fail("Current persisted workspace, organization and entity grants are required.", "manufacturing_execution_scope_denied")
        if operation != "read":
            self.connection.execute("SELECT set_config('app.manufacturing_execution_actor_id',%s,true)", (actor.user_id,))

    def _bom(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT * FROM reconforge.manufacturing_execution_boms WHERE tenant_id=%s AND id=%s FOR UPDATE"
                 if lock else "SELECT * FROM reconforge.manufacturing_execution_boms WHERE tenant_id=%s AND id=%s")
        row = self._one(query, (self.tenant_id, text(identifier, "bom_id")))
        return {**row["payload"], "phase": row["phase"], "source_digest": row["source_digest"], "reviewer_id": row["reviewer_id"]}

    def _order(self, identifier: str, *, lock: bool = False, read_lock: bool = False) -> dict[str, Any]:
        query = ("SELECT * FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s AND id=%s FOR UPDATE"
                 if lock else "SELECT * FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s AND id=%s FOR SHARE"
                 if read_lock else "SELECT * FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s AND id=%s")
        row = self._one(query, (self.tenant_id, text(identifier, "order_id")))
        return {**row["payload"], **{key: row[key] for key in ("phase", "source_digest", "issue_plan", "issue_digest",
                "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor")}}

    def _completion(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT * FROM reconforge.manufacturing_execution_completions WHERE tenant_id=%s AND id=%s FOR UPDATE"
                 if lock else "SELECT * FROM reconforge.manufacturing_execution_completions WHERE tenant_id=%s AND id=%s")
        row = self._one(query, (self.tenant_id, text(identifier, "completion_id")))
        return {**row["payload"], **{key: row[key] for key in ("phase", "source_digest", "reviewer_id", "receipt_effect", "scrap_effect_id")}}

    def _source(self, identifier: str) -> dict[str, Any]:
        return self._bom(identifier) if identifier.startswith("ME1B-") else self._completion(identifier) if identifier.startswith("ME1C-") else self._order(identifier)

    def _command(self, scope: Mapping[str, Any], operation: str, command_id: str, request: Mapping[str, Any],
                 actor: PostingActor) -> tuple[dict[str, Any], dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        wire = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "manufacturing-execution", command_id]),))
        retained = records(self.connection.execute("""SELECT * FROM reconforge.manufacturing_execution_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, scope["workspace_id"], command_id)))
        if not retained:
            return wire, None
        row = retained[0]
        if row["request_json"] != wire or row["request_digest"] != digest_payload(wire):
            fail("Command already identifies another exact request or actor.", "manufacturing_execution_command_conflict")
        current = self._source(row["object_id"])
        self._actor(actor, operation, current)
        self.connection.execute("SELECT reconforge.me1_close(%s,%s)", (self.tenant_id, current["id"]))
        return wire, row["response_json"]

    def _remember(self, source: Mapping[str, Any], operation: str, command: str, wire: Mapping[str, Any],
                  actor: PostingActor, reason: str) -> dict[str, Any]:
        metadata = {"source_digest": source["source_digest"], "phase": source["phase"], "reason": reason}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="manufacturing_execution", object_id=source["id"],
            action="manufacturing_execution." + operation, metadata=metadata)
        outbox = "OBX-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events
            (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
            VALUES(%s,%s,%s,'manufacturing_execution',%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, outbox,
            "manufacturing_execution." + operation, source["id"], source["workspace_id"], source["organization_id"],
            source["legal_entity_id"], canonical_json({**metadata, "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_events
            (tenant_id,object_id,operation,actor_id,reason,audit_event_id,outbox_event_id,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, source["id"], operation, actor.user_id,
            reason, audit.id, outbox, canonical_json(metadata)))
        result = dict(source)
        self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_commands
            (tenant_id,workspace_id,object_id,operation,command_id,actor_id,request_json,request_digest,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""", (self.tenant_id, source["workspace_id"], source["id"],
            operation, command, actor.user_id, canonical_json(wire), digest_payload(wire), canonical_json(result)))
        return result

    def _binding(self, source: Mapping[str, Any], *, period: bool = True) -> None:
        if period:
            self.owner.posting._period(source["period_id"], source["workspace_id"], source["posting_date"])
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(source["workspace_id"])
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, "finance_dimensions", source["workspace_id"]]),))

    def _item(self, scope: Mapping[str, Any], item_code: str) -> dict[str, Any]:
        item = self.inventory._item(scope["workspace_id"], item_code, active=True)
        if item["item_type"] not in {"Stock", "Consumable"} or item["tracking_mode"] != "None" or item["organization_id"] not in {None, scope["organization_id"]}:
            fail("This cycle requires active untracked native stock in its canonical organization.")
        return {"item_id": item["id"], "item_code": item["item_code"], "uom_id": item["uom_id"],
                "uom_code": item["uom_code"], "quantity_precision": item["decimal_places"], "inventory_account_id": item["inventory_account_id"]}

    def prepare_bom(self, request: BomPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._actor(actor, "create", args)
            wire, replay = self._command(args, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self._binding(args, period=False)
            output = self._item(args, request.output_item_code)
            components = []
            for line in request.components:
                item = self._item(args, str(line["item_code"]))
                if item["item_id"] == output["item_id"]:
                    fail("A product cannot be its own component in this bounded BOM.")
                components.append({**item, "quantity_scaled": quantity(line["quantity"], item["quantity_precision"]),
                                   "quantity": scaled_to_text(quantity(line["quantity"], item["quantity_precision"]), decimal_places=item["quantity_precision"])})
            output_quantity = quantity(request.output_quantity, output["quantity_precision"])
            expand_requirements(components, output_quantity, output_quantity)
            source = {**args, "command_request": args, "id": "ME1B-" + uuid4().hex.upper(), "creator_id": actor.user_id,
                      "output": output, "output_quantity_scaled": output_quantity,
                      "components": sorted(components, key=lambda component: component["item_id"])}
            digest = digest_payload(source)
            self._actor(actor, "create", source)
            self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_boms
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,number,version,payload,source_digest,creator_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, source["id"], source["workspace_id"],
                source["organization_id"], source["legal_entity_id"], source["number"], source["version"], canonical_json(source), digest, actor.user_id))
            return self._remember(self._bom(source["id"]), "create", command_id, wire, actor, request.reason)

    def approve_bom(self, bom_id: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            source = self._bom(bom_id)
            self._actor(actor, "approve-bom", source)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(source, "approve-bom", command_id, {"id": bom_id, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            self._binding(source, period=False)
            source = self._bom(bom_id, lock=True)
            self._actor(actor, "approve-bom", source)
            if source["phase"] != 0 or source["source_digest"] != expected_digest or actor.user_id == source["creator_id"]:
                fail("Approve requires the exact unapproved BOM and a distinct human.", "manufacturing_execution_review_denied")
            self.connection.execute("UPDATE reconforge.manufacturing_execution_boms SET phase=1,reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, bom_id))
            return self._remember(self._bom(bom_id), "approve-bom", command_id, wire, actor, reason)

    def _mapping(self, source: Mapping[str, Any]) -> dict[str, Any]:
        journal = self._one("""SELECT * FROM reconforge.finance_journals WHERE tenant_id=%s AND workspace_id=%s
            AND organization_code=%s AND journal_code=%s AND active""", (self.tenant_id, source["workspace_id"], source["organization_code"], source["journal_code"]))
        wip = self._one("SELECT * FROM reconforge.finance_accounts WHERE tenant_id=%s AND chart_id=%s AND account_code=%s", (self.tenant_id, journal["chart_id"], source["wip_account_code"]))
        scrap = self._one("SELECT * FROM reconforge.finance_accounts WHERE tenant_id=%s AND chart_id=%s AND account_code=%s", (self.tenant_id, journal["chart_id"], source["scrap_account_code"]))
        if wip["account_type"] != "Asset" or scrap["account_type"] != "Expense" or wip["id"] == scrap["id"]:
            fail("WIP requires its own Asset account and abnormal scrap an Expense account.")
        for account in (wip, scrap):
            if not account["active"] or not account["allow_posting"] or not account["allow_manual_posting"]:
                fail("Manufacturing accounts must currently permit native posting.")
        policies = []
        for name in ("component_policy_code", "finished_policy_code"):
            policy = self._one("""SELECT * FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s
                AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s AND active""", (self.tenant_id, source["workspace_id"],
                source["organization_id"], source["legal_entity_id"], source[name]))
            if policy["costing_method"] != "FIFO" or policy["currency_code"] != journal["currency_code"] or policy["finance_journal_id"] != journal["id"]:
                fail("Both material and finished policies require the same native FIFO functional journal.")
            policies.append(policy)
        if policies[1]["receipt_clearing_account_id"] != wip["id"]:
            fail("The finished-goods native receipt policy must offset exactly this WIP account.")
        if self.connection.execute("""SELECT 1 FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s
            AND active AND required_on_entries AND(organization_code='' OR organization_code=%s)""", (self.tenant_id, source["workspace_id"], source["organization_code"])).fetchone():
            fail("Required financial dimensions are outside this explicit manufacturing source contract.")
        return {"journal_id": journal["id"], "currency_code": journal["currency_code"], "wip_account_id": wip["id"],
                "scrap_account_id": scrap["id"], "component_policy_id": policies[0]["id"], "finished_policy_id": policies[1]["id"]}

    def _admit(self, source: Mapping[str, Any]) -> None:
        mapping = self._mapping(source)
        for key, value in mapping.items():
            if source[key] != value:
                fail("Current manufacturing mapping differs from the retained original source.")
        for line in [source["output"], *source["requirements"]]:
            current = self._item(source, line["item_code"])
            if any(current[key] != line[key] for key in ("item_id", "uom_id", "quantity_precision", "inventory_account_id")):
                fail("Current component or product interpretation differs from its original canonical UOM.")
            if current["inventory_account_id"] == source["wip_account_id"]:
                fail("Native stock inventory accounts must remain distinct from WIP.")
        unit = self._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active", (self.tenant_id, source["currency_code"]))
        if unit["minor_units"] != source["monetary_policy"]["precision"]:
            fail("Currency precision changed after source capture; its original amounts cannot be reinterpreted.")
        for key in ("component_location_code", "finished_location_code"):
            current_location = self.inventory._location_reference(source["workspace_id"], source["organization_id"], source["legal_entity_id"], source[key])
            expected = source["component_location_id" if key == "component_location_code" else "finished_location_id"]
            if current_location is None or current_location["id"] != expected or current_location["location_type"] != "Internal" or current_location["allow_negative"]:
                fail("Manufacturing requires current nonnegative Internal locations in its original entity.")

    def _inventory_locks(self, order: Mapping[str, Any]) -> None:
        pairs = {(line["item_id"], order["component_location_id"]) for line in order["requirements"]}
        pairs.add((order["output_item_id"], order["finished_location_id"]))
        lock_inventory_quantity_pools(self.connection, self.tenant_id, str(order["workspace_id"]),
                                      str(order["legal_entity_id"]), (str(item) for item, _ in pairs))
        for item, location in sorted(pairs):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{order['workspace_id']}|{order['legal_entity_id']}|{location}|{item}|",))
        for item in sorted({item for item, _ in pairs}):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{order['legal_entity_id']}|{item}|",))

    def create_order(self, request: OrderPreparation, *, command_id: str, actor: PostingActor,
                     _source_owner: object | None = None) -> dict[str, Any]:
        args = request.payload()
        execution_owner_id = None
        if _source_owner is not None:
            from reconforge.infrastructure.postgres_manufacturing_execution_v2 import (
                _ManufacturingV2MaterialParticipant,
            )
            if not isinstance(_source_owner, _ManufacturingV2MaterialParticipant) or not _source_owner.admits(
                    self.connection, self.tenant_id, _source_owner.order_id):
                fail("Material delegation requires the exact active ME2 source owner.")
            execution_owner_id = _source_owner.order_id
        with self._transaction():
            self._actor(actor, "create", args)
            wire, replay = self._command(args, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self._binding(args)
            bom = self._bom(request.bom_version_id, lock=True)
            self._actor(actor, "create", bom)
            if bom["phase"] != 1 or any(bom[key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                fail("An order requires an approved exact BOM version in the same source hierarchy.")
            output = bom["output"]
            planned = quantity(request.output_quantity, output["quantity_precision"])
            requirements = expand_requirements(bom["components"], bom["output_quantity_scaled"], planned)
            identifier = "ME1-" + uuid4().hex.upper()
            for line in requirements:
                line["requirement_id"] = "ME1R-" + digest_payload([self.tenant_id, identifier, line["item_id"]])[:32].upper()
            locations = {}
            for name in ("component", "finished"):
                location = self.inventory._location_reference(args["workspace_id"], args["organization_id"], args["legal_entity_id"], args[name + "_location_code"])
                if location is None:
                    fail("Actual component and finished locations are required.")
                locations[name + "_location_id"] = location["id"]
            mapping = self._mapping(args)
            currency = self._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active", (self.tenant_id, mapping["currency_code"]))
            monetary, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(workspace_id=args["workspace_id"], currency_code=mapping["currency_code"], minor_units=currency["minor_units"], actor_label=actor.username)
            source = {**args, "command_request": args, **mapping, **locations, "id": identifier, "creator_id": actor.user_id, "bom_digest": bom["source_digest"],
                      "output": output, "output_item_id": output["item_id"], "output_quantity_scaled": planned,
                      "requirements": requirements, "monetary_policy": asdict(monetary), "movement_id": platform_id("MOV", args["workspace_id"], identifier)}
            digest = digest_payload(source)
            self._admit(source)
            self._actor(actor, "create", source)
            self._inventory_locks(source)
            values = (self.tenant_id, identifier, source["workspace_id"], source["organization_id"],
                source["legal_entity_id"], source["number"], bom["id"], source["movement_id"], canonical_json(source), digest)
            if execution_owner_id is None:
                self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_orders
                    (tenant_id,id,workspace_id,organization_id,legal_entity_id,number,bom_version_id,movement_id,payload,source_digest)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", values)
            else:
                self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_orders
                    (tenant_id,id,workspace_id,organization_id,legal_entity_id,number,bom_version_id,movement_id,payload,source_digest,execution_owner_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (*values, execution_owner_id))
            for line in requirements:
                evidence = requirement_payload(requirement_id=line["requirement_id"], order={**source, "source_digest": digest}, bom=bom, component=line)
                self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_requirements
                    (tenant_id,id,order_id,bom_version_id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,required_quantity_scaled,quantity_precision,requirement_json,requirement_digest)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, line["requirement_id"], identifier,
                    bom["id"], source["workspace_id"], source["organization_id"], source["legal_entity_id"], line["item_id"], line["uom_id"],
                    line["required_quantity_scaled"], line["quantity_precision"], canonical_json(evidence), digest_payload(evidence)))
                self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_reservations
                    (tenant_id,requirement_id,order_id,workspace_id,organization_id,legal_entity_id,item_id,location_id,quantity_scaled)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, line["requirement_id"], identifier, source["workspace_id"],
                    source["organization_id"], source["legal_entity_id"], line["item_id"], source["component_location_id"], line["required_quantity_scaled"]))
            self.inventory.create_movement(movement_number=identifier, movement_type="Delivery", organization_code=source["organization_code"],
                entity_code=source["entity_code"], period_id=source["period_id"], movement_date=source["posting_date"],
                description=request.reason, source_reference=identifier, source_type="Generated", workspace=source["workspace_id"], actor_label=actor.username,
                lines=[{"item_code": line["item_code"], "quantity": line["required_quantity"], "from_location": source["component_location_code"]} for line in requirements])
            self.connection.execute("UPDATE reconforge.inventory_movements SET manufacturing_claim_state='Reserved' WHERE tenant_id=%s AND id=%s", (self.tenant_id, source["movement_id"]))
            for line in requirements:
                self.connection.execute("SELECT reconforge.stock_sales_capacity(%s,%s,%s,%s,%s)", (self.tenant_id, source["workspace_id"], source["legal_entity_id"], source["component_location_id"], line["item_id"]))
            return self._remember(self._order(identifier), "create", command_id, wire, actor, request.reason)

    def _draft(self, identifier: str, source: Mapping[str, Any], lines: list[dict[str, Any]], actor: PostingActor) -> dict[str, Any]:
        entry = self.owner.finance.create_entry(entry_number=identifier, organization_code=source["organization_code"], entity_code=source["entity_code"],
            period_id=source["period_id"], journal_code=source["journal_code"], posting_date=source["posting_date"], description=source["reason"],
            external_reference=source["id"], workspace=source["workspace_id"], actor_label=actor.username, lines=lines)
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
        return {"entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot)}

    def _prepare_issue(self, order: Mapping[str, Any], actor: PostingActor) -> None:
        components: list[dict[str, Any]] = []
        credits: dict[str, int] = {}
        total = 0
        historical, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry({"currency_code": order["currency_code"],
            "currency_precision": order["monetary_policy"]["precision"], "currency_rounding_policy": order["monetary_policy"]["rounding_policy"],
            "currency_registry_version": order["monetary_policy"]["registry_version"], "currency_registry_digest": order["monetary_policy"]["registry_digest"]})
        for required in order["requirements"]:
            if self.connection.execute("""SELECT 1 FROM reconforge.stock_sales_issue_claims WHERE tenant_id=%s AND workspace_id=%s
                AND legal_entity_id=%s AND item_id=%s AND state='Active'""", (self.tenant_id, order["workspace_id"], order["legal_entity_id"], required["item_id"])).fetchone():
                fail("A native sales issue currently owns this component FIFO pool.", "manufacturing_execution_claim_conflict")
            if self.connection.execute("""SELECT 1 FROM reconforge.manufacturing_execution_orders o WHERE o.tenant_id=%s AND o.id<>%s AND o.phase IN(1,2)
                AND EXISTS(SELECT 1 FROM jsonb_array_elements(o.issue_plan->'components') c WHERE c->>'item_id'=%s)""", (self.tenant_id, order["id"], required["item_id"])).fetchone():
                fail("Another reviewed manufacturing issue currently owns this component FIFO pool.", "manufacturing_execution_claim_conflict")
            layers = records(self.connection.execute("""SELECT l.*,d.currency_precision,d.currency_rounding_policy,d.currency_registry_version,d.currency_registry_digest
                FROM reconforge.inventory_cost_layers l JOIN reconforge.inventory_valuation_lines v ON v.tenant_id=l.tenant_id AND v.id=l.source_valuation_line_id
                JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id
                WHERE l.tenant_id=%s AND l.workspace_id=%s AND l.legal_entity_id=%s AND l.item_id=%s AND l.inventory_lot_id IS NULL
                AND l.remaining_quantity_scaled>0 AND d.status='Approved' ORDER BY l.created_at,l.id FOR UPDATE OF l""",
                (self.tenant_id, order["workspace_id"], order["legal_entity_id"], required["item_id"])))
            for layer in layers:
                original, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(layer)
                historical.require_compatible(original)
                if layer["uom_id"] != required["uom_id"] or layer["quantity_precision"] != required["quantity_precision"]:
                    fail("A component FIFO layer differs from the original base-UOM interpretation.")
            allocations, value = freeze_fifo(layers, required["required_quantity_scaled"])
            components.append({**required, "allocations": allocations, "value_minor": value})
            credits[required["inventory_account_id"]] = credits.get(required["inventory_account_id"], 0) + value
            total += value
        exact_integer(total, positive=True)
        quoted = {**order, "issue_plan": {"total_cost_minor": total}}
        self._actor(actor, "prepare", quoted)
        lines = [{"account_code": order["wip_account_code"], "debit": minor_to_text(total, historical.precision)}]
        for account, value in sorted(credits.items()):
            account_code = self._one("SELECT account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s", (self.tenant_id, account))["account_code"]
            lines.append({"account_code": account_code, "credit": minor_to_text(value, historical.precision)})
        plan = {"schema_version": "manufacturing-issue-v1", "preparer_actor_id": actor.user_id, "source_digest": order["source_digest"],
                "components": components, "total_cost_minor": total, "entry": self._draft(order["id"], order, lines, actor)}
        self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=1,issue_plan=%s::jsonb,issue_digest=%s WHERE tenant_id=%s AND id=%s",
            (canonical_json(plan), digest_payload(plan), self.tenant_id, order["id"]))

    def _post_entry(self, entry: Mapping[str, Any], actor: PostingActor, command: str, reason: str) -> dict[str, Any]:
        self._participant = _ManufacturingPostingParticipant(self, entry["entry_id"])
        try:
            return self.owner.posting.post(entry["entry_id"], command_id=command, expected_validation_digest=entry["validation_digest"],
                reason=reason, actor=actor, _source_owner=self._participant)
        except BaseException:
            self._rollback_only = True
            raise
        finally:
            self._participant = None

    def _issue(self, order: Mapping[str, Any], actor: PostingActor, command: str, reason: str) -> None:
        plan, monetary = order["issue_plan"], order["monetary_policy"]
        for component in plan["components"]:
            for allocation in component["allocations"]:
                layer = self._one("SELECT * FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, allocation["cost_layer_id"]))
                if any(layer[key] != allocation[key] for key in ("row_version", "remaining_quantity_scaled", "remaining_value_minor")):
                    fail("Reviewed original FIFO residual changed; manufacturing cannot silently recost.")
        # Owner moves to Issued before the native writes; every deferred guard sees the complete final transaction.
        valuation_id = platform_id("MEVAL", order["id"])
        self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=3,valuation_id=%s WHERE tenant_id=%s AND id=%s", (valuation_id, self.tenant_id, order["id"]))
        self.connection.execute("UPDATE reconforge.manufacturing_execution_reservations SET state='Consumed' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, order["id"]))
        self.connection.execute("UPDATE reconforge.inventory_movements SET manufacturing_claim_state='Issued' WHERE tenant_id=%s AND id=%s", (self.tenant_id, order["movement_id"]))
        self.inventory.post_movement(order["movement_id"], reason=reason, actor_label=actor.username)
        self.connection.execute("""INSERT INTO reconforge.inventory_valuation_documents
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_id,policy_id,valuation_number,valuation_date,currency_code,
             created_by,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, valuation_id, order["workspace_id"],
            order["organization_id"], order["legal_entity_id"], order["period_id"], order["movement_id"], order["component_policy_id"], order["id"],
            order["posting_date"], order["currency_code"], plan["entry"]["snapshot"]["entry"]["preparer_actor_id"], monetary["precision"],
            monetary["rounding_policy"], monetary["registry_version"], monetary["registry_digest"]))
        movement = self.inventory.get_movement(order["movement_id"])
        for number, component in enumerate(plan["components"], 1):
            line = next(line for line in movement["lines"] if line["item_id"] == component["item_id"])
            line_id = platform_id("MEVL", order["id"], component["item_id"])
            self.connection.execute("""INSERT INTO reconforge.inventory_valuation_lines
                (tenant_id,id,valuation_document_id,movement_line_id,line_number,flow_direction,item_id,uom_id,quantity_scaled,quantity_precision,value_minor,inventory_account_id,offset_account_id)
                VALUES(%s,%s,%s,%s,%s,'Outbound',%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, line_id, valuation_id, line["id"], number,
                component["item_id"], component["uom_id"], component["required_quantity_scaled"], component["quantity_precision"],
                component["value_minor"], component["inventory_account_id"], order["wip_account_id"]))
            for allocation in component["allocations"]:
                self.connection.execute("""INSERT INTO reconforge.inventory_layer_consumptions
                    (tenant_id,id,workspace_id,valuation_line_id,cost_layer_id,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, platform_id("MECON", line_id, allocation["cost_layer_id"]), order["workspace_id"], line_id,
                    allocation["cost_layer_id"], allocation["quantity_scaled"], allocation["value_minor"]))
                self.connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled-%s,
                    remaining_value_minor=remaining_value_minor-%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""", (allocation["quantity_scaled"], allocation["value_minor"], self.tenant_id, allocation["cost_layer_id"]))
        self.connection.execute("""UPDATE reconforge.inventory_valuation_documents SET status='Approved',total_value_minor=%s,finance_entry_id=%s,
            approved_by=%s,approved_at=now(),approval_reason=%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
            (plan["total_cost_minor"], plan["entry"]["entry_id"], actor.username, reason, self.tenant_id, valuation_id))
        effect = self._post_entry(plan["entry"], actor, "me1-issue:" + command, reason)
        self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET issue_effect_id=%s WHERE tenant_id=%s AND id=%s", (effect["id"], self.tenant_id, order["id"]))

    def act(self, order_id: str, operation: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"prepare", "review", "post", "cancel"}:
            fail("Unknown manufacturing order lifecycle operation.")
        with self._transaction():
            order = self._order(order_id)
            self._actor(actor, operation, order)
            reason = text(reason, "reason", maximum=500)
            args = {"id": order_id, "expected_digest": expected_digest, "reason": reason}
            wire, replay = self._command(order, operation, command_id, args, actor)
            if replay is not None:
                return replay
            self._binding(order)
            order = self._order(order_id, lock=True)
            self._actor(actor, operation, order)
            self._admit(order)
            self._inventory_locks(order)
            if expected_digest != order["source_digest"]:
                fail("Expected original order digest differs.", "manufacturing_execution_state_conflict")
            phase = {"prepare": 0, "review": 1, "post": 2}.get(operation)
            if operation != "cancel" and order["phase"] != phase or operation == "cancel" and order["phase"] not in {0, 1, 2}:
                fail("Order is outside this operation's current complete phase.", "manufacturing_execution_state_conflict")
            if operation == "prepare":
                self._prepare_issue(order, actor)
            elif operation == "review":
                if actor.user_id == order["issue_plan"]["preparer_actor_id"]:
                    fail("Issue review requires a distinct human.", "manufacturing_execution_review_denied")
                self.owner.finance.validate_entry(order["issue_plan"]["entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=2,issue_reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, order_id))
            elif operation == "post":
                if actor.user_id in {order["issue_plan"]["preparer_actor_id"], order["issue_reviewer_id"]}:
                    fail("Material issue posting requires a third human.", "manufacturing_execution_post_denied")
                self._issue(order, actor, command_id, reason)
            else:
                if order["issue_plan"]:
                    self.owner.finance.void_entry(order["issue_plan"]["entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=5 WHERE tenant_id=%s AND id=%s", (self.tenant_id, order_id))
                self.connection.execute("UPDATE reconforge.manufacturing_execution_reservations SET state='Released' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, order_id))
            marker = {0: "Reserved", 1: "IssuePrepared", 2: "IssueReviewed", 3: "Issued", 4: "Issued", 5: "Cancelled"}[self._order(order_id)["phase"]]
            self.connection.execute("UPDATE reconforge.inventory_movements SET manufacturing_claim_state=%s WHERE tenant_id=%s AND id=%s", (marker, self.tenant_id, order["movement_id"]))
            return self._remember(self._order(order_id), operation, command_id, wire, actor, reason)

    def prepare_completion(self, order_id: str, *, good_quantity: str, scrap_quantity: str, period_id: str, posting_date: str,
                           command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        args = {"order_id": order_id, "good_quantity": good_quantity, "scrap_quantity": scrap_quantity,
                "period_id": period_id, "posting_date": business_date(posting_date), "reason": text(reason, "reason", maximum=500)}
        with self._transaction():
            order = self._order(order_id)
            self._actor(actor, "prepare", order)
            wire, replay = self._command(order, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self._binding({**order, **args})
            order = self._order(order_id, lock=True)
            self._actor(actor, "prepare", order)
            native = self._one("SELECT to_jsonb(o)->>'execution_owner_id' AS execution_owner_id FROM reconforge.manufacturing_execution_orders o WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, order_id))
            if native["execution_owner_id"] is not None:
                fail("This material order delegates complete cost and quality disposition to its ME2 owner.",
                     "manufacturing_execution_source_owner_required")
            self._admit(order)
            self._inventory_locks(order)
            if order["phase"] != 3 or posting_date < order["posting_date"]:
                fail("A partial disposition requires posted original WIP and a later or equal business date.")
            if self.connection.execute("SELECT 1 FROM reconforge.manufacturing_execution_completions WHERE tenant_id=%s AND order_id=%s AND phase IN(0,1)", (self.tenant_id, order_id)).fetchone():
                fail("Complete or cancel the current reviewed disposition before preparing another.")
            count = self._one("SELECT count(*) count FROM reconforge.manufacturing_execution_completions WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, order_id))["count"]
            if count >= MAX_COMPLETIONS:
                fail("The bounded completion history permits at most two hundred attempts.")
            good = quantity_to_scaled(good_quantity, order["output"]["quantity_precision"], allow_zero=True)
            scrap = quantity_to_scaled(scrap_quantity, order["output"]["quantity_precision"], allow_zero=True)
            allocation = allocate_disposition(original_quantity=order["output_quantity_scaled"], original_cost=order["issue_plan"]["total_cost_minor"],
                disposed_quantity=order["disposed_quantity_scaled"], released_cost=order["released_cost_minor"], good_quantity=good, scrap_quantity=scrap)
            identifier = self._completion_identifier(order, posting_date, count, good)
            source = {key: order[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code", "journal_code",
                                                 "currency_code", "monetary_policy", "wip_account_code", "scrap_account_code")}
            source.update(schema_version="manufacturing-completion-v1", id=identifier, command_request=args, **args, **allocation,
                          order_digest=order["source_digest"], issue_digest=order["issue_digest"], preparer_actor_id=actor.user_id,
                          receipt_identity_candidates=self._chronology_candidates)
            receipt = None
            self.connection.execute("SELECT set_config('app.manufacturing_execution_completion_id',%s,true)", (identifier,))
            if good:
                with self._receipt_context(identifier, None) as participant:
                    receipt = self.receipts.prepare_receipt(ReceiptPreparation(receipt_number=identifier, posting_date=posting_date, period_id=period_id,
                        item_code=order["output"]["item_code"], location_code=order["finished_location_code"], quantity=scaled_to_text(good, decimal_places=order["output"]["quantity_precision"]),
                        total_value_minor=allocation["good_cost_minor"], policy_code=order["finished_policy_code"], organization_code=order["organization_code"],
                        entity_code=order["entity_code"], workspace=order["workspace_id"], reason=reason), command_id="me1-fg-prepare:" + command_id, actor=actor, _source_owner=participant)
            scrap_entry = None
            if scrap:
                value = minor_to_text(allocation["scrap_cost_minor"], order["monetary_policy"]["precision"])
                scrap_entry = self._draft(identifier, source, [{"account_code": order["scrap_account_code"], "debit": value},
                    {"account_code": order["wip_account_code"], "credit": value}], actor)
            source.update(receipt_plan=receipt, scrap_entry=scrap_entry)
            digest = digest_payload(source)
            self._actor(actor, "prepare", source)
            self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_completions
                (tenant_id,id,order_id,workspace_id,organization_id,legal_entity_id,payload,source_digest)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, identifier, order_id, order["workspace_id"],
                order["organization_id"], order["legal_entity_id"], canonical_json(source), digest))
            return self._remember(self._completion(identifier), "create", command_id, wire, actor, reason)

    def _completion_identifier(self, order: Mapping[str, Any], posting_date: str, count: int, good: int) -> str:
        # IRP intentionally orders same-day receipts by its immutable hashed movement
        # number. Select a bounded source identity that respects that existing order;
        # never weaken native chronology or rewrite a previously posted receipt.
        latest = None
        self._chronology_candidates = 0
        if good:
            row = self.connection.execute("""SELECT max(m.movement_number) number
                FROM reconforge.inventory_movements m JOIN reconforge.inventory_valuation_documents v
                  ON v.tenant_id=m.tenant_id AND v.movement_id=m.id
                WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s
                  AND m.legal_entity_id=%s AND m.movement_date=%s::date AND v.status='Approved'
                  AND EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines l
                      WHERE l.tenant_id=m.tenant_id AND l.movement_id=m.id AND l.item_id=%s)""",
                (self.tenant_id, order["workspace_id"], order["organization_id"], order["legal_entity_id"],
                 posting_date, order["output_item_id"])).fetchone()
            latest = row["number"] if row is not None else None
        for candidate in range(4096):
            identifier = "ME1C-" + digest_payload([self.tenant_id, order["id"], count, candidate])[:32].upper()
            if latest is None or artifact_id(source_plan_id(order, identifier), "MOV").upper() > latest:
                self._chronology_candidates = candidate + 1 if good else 0
                return identifier
        fail("This posting date has exhausted bounded receipt chronology identities; select a later business date.")

    def act_completion(self, completion_id: str, operation: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"review", "post", "cancel"}:
            fail("Unknown manufacturing disposition lifecycle operation.")
        with self._transaction():
            completion = self._completion(completion_id)
            self._actor(actor, operation, completion)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(completion, operation, command_id, {"id": completion_id, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            self._binding(completion)
            order = self._order(completion["order_id"], lock=True)
            completion = self._completion(completion_id, lock=True)
            self._actor(actor, operation, completion)
            self._admit(order)
            self._inventory_locks(order)
            if expected_digest != completion["source_digest"] or completion["phase"] not in ({0} if operation == "review" else {1} if operation == "post" else {0, 1}):
                fail("Disposition digest or current phase differs.", "manufacturing_execution_state_conflict")
            if order["disposed_quantity_scaled"] != completion["disposed_before_scaled"] or order["released_cost_minor"] != completion["released_before_minor"]:
                fail("The retained original WIP changed after disposition preparation.")
            if operation == "review" and actor.user_id == completion["preparer_actor_id"]:
                fail("Disposition review requires an independent human.", "manufacturing_execution_review_denied")
            if operation == "post" and actor.user_id in {completion["preparer_actor_id"], completion["reviewer_id"]}:
                fail("Disposition posting requires a third human.", "manufacturing_execution_post_denied")
            self.connection.execute("SELECT set_config('app.manufacturing_execution_completion_id',%s,true)", (completion_id,))
            if operation == "cancel":
                if completion["scrap_entry"]:
                    self.owner.finance.void_entry(completion["scrap_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_completions SET phase=3 WHERE tenant_id=%s AND id=%s", (self.tenant_id, completion_id))
            elif operation == "review":
                if completion["receipt_plan"]:
                    with self._receipt_context(completion_id, completion["receipt_plan"]["plan_id"]) as participant:
                        self.receipts.review(completion["receipt_plan"]["plan_id"], command_id="me1-fg-review:" + command_id,
                            expected_plan_digest=completion["receipt_plan"]["plan_digest"], reason=reason, actor=actor, _source_owner=participant)
                if completion["scrap_entry"]:
                    self.owner.finance.validate_entry(completion["scrap_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_completions SET phase=1,reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, completion_id))
            else:
                receipt_effect, scrap_effect = None, None
                if completion["receipt_plan"]:
                    with self._receipt_context(completion_id, completion["receipt_plan"]["plan_id"]) as participant:
                        receipt_view = self.receipts.get_plan(completion["receipt_plan"]["plan_id"], actor=actor, _source_owner=participant)
                        review = receipt_view["review"]
                        if review is None:
                            fail("The exact native finished receipt requires its retained independent review.")
                        receipt_effect = self.receipts.commit(completion["receipt_plan"]["plan_id"], command_id="me1-fg-post:" + command_id,
                            expected_review_digest=review["review_digest"], reason=reason, actor=actor, _source_owner=participant)
                if completion["scrap_entry"]:
                    scrap_effect = self._post_entry(completion["scrap_entry"], actor, "me1-scrap:" + command_id, reason)
                self.connection.execute("""UPDATE reconforge.manufacturing_execution_completions SET phase=2,receipt_effect=%s::jsonb,scrap_effect_id=%s WHERE tenant_id=%s AND id=%s""",
                    (canonical_json(receipt_effect), None if scrap_effect is None else scrap_effect["id"], self.tenant_id, completion_id))
                disposed = order["disposed_quantity_scaled"] + completion["stage_quantity_scaled"]
                released = order["released_cost_minor"] + completion["released_cost_minor"]
                self.connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=%s,disposed_quantity_scaled=%s,released_cost_minor=%s WHERE tenant_id=%s AND id=%s",
                    (4 if disposed == order["output_quantity_scaled"] else 3, disposed, released, self.tenant_id, order["id"]))
            return self._remember(self._completion(completion_id), operation, command_id, wire, actor, reason)

    def get_order(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction(write=False):
            order = self._order(order_id, read_lock=True)
            self._actor(actor, "read", order)
            self.connection.execute("SELECT reconforge.me1_close(%s,%s)", (self.tenant_id, order_id))
            completions = records(self.connection.execute("SELECT id FROM reconforge.manufacturing_execution_completions WHERE tenant_id=%s AND order_id=%s ORDER BY id COLLATE \"C\"", (self.tenant_id, order_id)))
            retained = []
            for row in completions:
                completion = self._completion(row["id"])
                self._actor(actor, "read", completion)
                if completion["receipt_plan"]:
                    with self._receipt_context(completion["id"], completion["receipt_plan"]["plan_id"]) as participant:
                        backing = self.receipts.get_plan(completion["receipt_plan"]["plan_id"], actor=actor, _source_owner=participant)
                        if backing["effect"] != completion["receipt_effect"]:
                            fail("Retained finished-goods acknowledgement differs from verified native financial backing.")
                retained.append(completion)
            result = {**order, "completions": retained,
                      "wip_minor": 0 if order["phase"] not in {3, 4} else order["issue_plan"]["total_cost_minor"] - order["released_cost_minor"]}
            native = self._one("SELECT to_jsonb(o)->>'execution_owner_id' AS execution_owner_id FROM reconforge.manufacturing_execution_orders o WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, order_id))
            if native["execution_owner_id"] is not None:
                from reconforge.infrastructure.postgres_manufacturing_execution_v2 import (
                    PostgresManufacturingExecutionV2Repository,
                )
                delegated = PostgresManufacturingExecutionV2Repository(self.connection, self.tenant_id)
                parent = delegated._source(native["execution_owner_id"], read_lock=True)
                delegated._actor(actor, "read", parent)
                result.update(execution_version=2, execution_owner={key: parent[key] for key in
                    ("id", "phase", "source_digest", "total_cost_minor", "produced_quantity_scaled", "disposed_quantity_scaled", "released_cost_minor")},
                    material_cost_minor=0 if order["issue_plan"] is None else order["issue_plan"]["total_cost_minor"],
                    wip_minor=parent["total_cost_minor"] - parent["released_cost_minor"] if parent["phase"] in {3, 4} else 0)
            return result

    def get_requirement(self, requirement_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction(write=False):
            row = self._one("SELECT * FROM reconforge.manufacturing_execution_requirements WHERE tenant_id=%s AND id=%s", (self.tenant_id, requirement_id))
            order = self._order(row["order_id"], read_lock=True)
            self._actor(actor, "read", order)
            self.connection.execute("SELECT reconforge.me1_close(%s,%s)", (self.tenant_id, order["id"]))
            if digest_payload(row["requirement_json"]) != row["requirement_digest"]:
                fail("Original requirement evidence failed exact verification.")
            return {**row["requirement_json"], "requirement_digest": row["requirement_digest"]}

    def list_orders(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction(write=False):
            self._actor(actor, "read", scope)
            orders = records(self.connection.execute("""SELECT id FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id COLLATE "C" LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            boms = records(self.connection.execute("""SELECT id FROM reconforge.manufacturing_execution_boms WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY number COLLATE "C",version LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            return {"orders": [self.get_order(row["id"], actor=actor) for row in orders], "boms": [self._bom(row["id"]) for row in boms]}
