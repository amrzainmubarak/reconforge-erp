"""ME2 owns expense claims, quality holds and inspected native receipts atomically."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation, artifact_id, source_plan_id
from reconforge.domain.manufacturing_execution import business_date, exact_integer, fail, quantity
from reconforge.domain.manufacturing_execution_v2 import (
    MAX_PRODUCTIONS,
    PERMISSIONS,
    READ,
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
    cost_claims,
    held_allocation,
    inspection_allocation,
    operation_reports,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, records
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from reconforge.platform.inventory_values import minor_to_text, quantity_to_scaled, scaled_to_text


class _ManufacturingV2PostingParticipant:
    def __init__(self, owner: PostgresManufacturingExecutionV2Repository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._active and self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class _ManufacturingV2MaterialParticipant:
    def __init__(self, owner: PostgresManufacturingExecutionV2Repository, order_id: str) -> None:
        self.owner, self.order_id = owner, order_id

    def admits(self, connection: Any, tenant_id: str, order_id: str) -> bool:
        return (self.owner._active and self.owner._material_participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.order_id == order_id)


class _ManufacturingV2ReceiptParticipant:
    def __init__(self, owner: PostgresManufacturingExecutionV2Repository, completion_id: str, plan_id: str | None) -> None:
        self.owner, self.completion_id, self.plan_id = owner, completion_id, plan_id

    def admits(self, connection: Any, tenant_id: str, identifier: str) -> bool:
        return (self.owner._active and self.owner._receipt_participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and identifier in {self.completion_id, self.plan_id})


class PostgresManufacturingExecutionV2Repository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.material = PostgresManufacturingExecutionRepository(connection, tenant_id)
        self.owner, self.receipts = self.material.owner, self.material.receipts
        self._active = False
        self._rollback_only = False
        self._participant: _ManufacturingV2PostingParticipant | None = None
        self._material_participant: _ManufacturingV2MaterialParticipant | None = None
        self._receipt_participant: _ManufacturingV2ReceiptParticipant | None = None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self._active:
            fail("A complete ME2 command cannot reenter its owner.")
        with self.owner._transaction():
            self._active = True
            self._rollback_only = False
            try:
                yield
                if self._rollback_only:
                    fail("A failed native ME2 participant requires the complete command to roll back.")
            finally:
                self._active = False

    def _source(self, identifier: str, *, lock: bool = False, read_lock: bool = False) -> dict[str, Any]:
        from psycopg import sql
        table = ("manufacturing_execution_v2_definitions" if identifier.startswith(("ME2W-", "ME2R-"))
                 else "manufacturing_execution_v2_productions" if identifier.startswith("ME2P-")
                 else "manufacturing_execution_v2_inspections" if identifier.startswith("ME2C-")
                 else "manufacturing_execution_v2_orders")
        statement = sql.SQL("SELECT * FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(sql.Identifier(table))
        statement += sql.SQL(" FOR UPDATE" if lock else " FOR SHARE" if read_lock else "")
        rows = records(self.connection.execute(statement, (self.tenant_id, text(identifier, "source_id"))))
        if not rows:
            fail("ME2 source is absent from the current hierarchy.", "manufacturing_execution_v2_not_found")
        row = rows[0]
        return {**row["payload"], **{key: value for key, value in row.items() if key not in {"tenant_id", "payload", "created_at"}}}

    def _actor(self, actor: PostingActor, operation: str, source: Mapping[str, Any], *, lock: bool = False) -> None:
        if source.get("order_id"):
            self._actor(actor, operation, self._source(str(source["order_id"])), lock=lock)
        financial = dict(source)
        if source.get("material_order_id"):
            original = self.material._order(str(source["material_order_id"]))
            amount = max(source.get("total_cost_minor", 0), sum(claim["original_debit_minor"] for claim in source["claims"]))
            if original.get("issue_plan"):
                amount = max(amount, original["issue_plan"]["total_cost_minor"] + sum(claim["amount_minor"] for claim in source["claims"]))
            financial.update(amount_minor=amount, currency_precision=source["monetary_policy"]["precision"])
        for permission in sorted(PERMISSIONS.get(operation, READ)):
            self.owner._actor(actor, permission, financial, mutation=operation != "read")
        scope_query = """SELECT scope_type,scope_id FROM reconforge.principal_scope_grants
            WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
            AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
                OR(scope_type='legal_entity' AND scope_id=%s))"""
        if lock:
            scope_query += " FOR SHARE"
        rows = records(self.connection.execute(scope_query, (self.tenant_id, actor.user_id,
                source["workspace_id"], source["organization_id"], source["legal_entity_id"])))
        if len({(row["scope_type"], row["scope_id"]) for row in rows}) != 3:
            fail("ME2 requires every current persisted parent scope.", "manufacturing_execution_v2_scope_denied")
        if operation != "read":
            self.connection.execute("SELECT set_config('app.manufacturing_execution_v2_actor_id',%s,true)", (actor.user_id,))

    def _command(self, source: Mapping[str, Any], operation: str, command: str,
                 request: Mapping[str, Any], actor: PostingActor) -> tuple[dict[str, Any], dict[str, Any] | None]:
        command = text(command, "command_id", maximum=140)
        wire = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, source["workspace_id"], "manufacturing-execution-v2", command]),))
        rows = records(self.connection.execute("""SELECT * FROM reconforge.manufacturing_execution_v2_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, source["workspace_id"], command)))
        if not rows:
            return wire, None
        retained = rows[0]
        if retained["request_json"] != wire or retained["request_digest"] != digest_payload(wire):
            fail("ME2 command belongs to another exact actor or request.", "manufacturing_execution_v2_command_conflict")
        current = self._source(retained["object_id"], read_lock=True)
        self._actor(actor, operation, current, lock=True)
        self.connection.execute("SELECT reconforge.me2_close(%s,%s)", (self.tenant_id, current["id"]))
        return wire, retained["response_json"]

    def _remember(self, identifier: str, operation: str, command: str, wire: Mapping[str, Any],
                  actor: PostingActor, reason: str) -> dict[str, Any]:
        source = self._source(identifier)
        self._actor(actor, operation, source, lock=True)
        metadata = {"source_digest": source["source_digest"], "phase": source["phase"], "reason": reason}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="manufacturing_execution_v2", object_id=identifier,
            action="manufacturing_execution_v2." + operation, metadata=metadata)
        outbox = "OBX-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events
            (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
            VALUES(%s,%s,%s,'manufacturing_execution_v2',%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, outbox,
            "manufacturing_execution_v2." + operation, identifier, source["workspace_id"], source["organization_id"],
            source["legal_entity_id"], canonical_json({**metadata, "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_events
            (tenant_id,object_id,operation,actor_id,reason,audit_event_id,outbox_event_id,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, identifier, operation, actor.user_id,
            reason, audit.id, outbox, canonical_json(metadata)))
        self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_commands
            (tenant_id,workspace_id,object_id,operation,command_id,actor_id,request_json,request_digest,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""", (self.tenant_id, source["workspace_id"], identifier,
            operation, command, actor.user_id, canonical_json(wire), digest_payload(wire), canonical_json(source)))
        return source

    def _insert_definition(self, source: dict[str, Any], kind: str, actor: PostingActor) -> None:
        self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_definitions
            (tenant_id,id,kind,workspace_id,organization_id,legal_entity_id,number,version,payload,source_digest,creator_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, source["id"], kind,
            source["workspace_id"], source["organization_id"], source["legal_entity_id"], source.get("code", source.get("number")),
            source["version"], canonical_json(source), digest_payload(source), actor.user_id))

    def create_workcenter(self, request: WorkcenterPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._actor(actor, "create", args)
            wire, replay = self._command(args, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self.material._binding(args, period=False)
            self._actor(actor, "create", args)
            source = {**args, "command_request": args, "id": "ME2W-" + uuid4().hex.upper(), "creator_id": actor.user_id}
            self._insert_definition(source, "Workcenter", actor)
            return self._remember(source["id"], "create", command_id, wire, actor, request.reason)

    def create_routing(self, request: RoutingPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._actor(actor, "create", args)
            wire, replay = self._command(args, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self.material._binding(args, period=False)
            bom = self.material._bom(request.bom_version_id, lock=True)
            self.material._actor(actor, "read", bom)
            if bom["phase"] != 1 or any(bom[key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                fail("An engineering routing needs the exact independently approved native BOM in its hierarchy.")
            operations = []
            for operation in args["operations"]:
                center = self._source(operation["workcenter_id"], read_lock=True)
                self._actor(actor, "read", center)
                if center["kind"] != "Workcenter" or center["phase"] != 1 or any(center[key] != args[key]
                        for key in ("workspace_id", "organization_id", "legal_entity_id")):
                    fail("Every routing operation needs its approved actual workcenter in the same hierarchy.")
                if center["effective_from"] > args["effective_from"] or center["effective_until"] < args["effective_until"]:
                    fail("Routing dates exceed the retained effective workcenter revision.")
                operations.append({**operation, "workcenter_digest": center["source_digest"]})
            source = {**args, "command_request": args, "operations": operations, "bom_digest": bom["source_digest"],
                      "id": "ME2R-" + uuid4().hex.upper(), "creator_id": actor.user_id}
            self._insert_definition(source, "Routing", actor)
            return self._remember(source["id"], "create", command_id, wire, actor, request.reason)

    def approve_definition(self, identifier: str, *, expected_digest: str, command_id: str,
                           reason: str, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            source = self._source(identifier)
            self._actor(actor, "approve", source)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(source, "approve", command_id, {"id": identifier, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            self.material._binding(source, period=False)
            source = self._source(identifier, lock=True)
            self._actor(actor, "approve", source, lock=True)
            if source["phase"] != 0 or source["source_digest"] != expected_digest or actor.user_id == source["creator_id"]:
                fail("Approval requires an exact unapproved revision and independent current human.")
            self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_definitions SET phase=1,reviewer_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, self.tenant_id, identifier))
            return self._remember(identifier, "approve", command_id, wire, actor, reason)

    def _expense_claim(self, claim: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
        self.connection.execute("SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)", (self.tenant_id, claim["effect_id"]))
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, "me2-expense-line", claim["effect_id"], claim["line_id"]]),))
        effect = self.owner.posting._get_effect(claim["effect_id"])
        original_header = posting_entry(self.connection, self.tenant_id, effect["entry_id"])
        if (effect["source_kind"] != "Manual" or effect["reverses_effect_id"] is not None
                or original_header["source_type"] != "Manual" or original_header["posting_date"] > source["posting_date"]
                or any(effect[key] != source[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "currency_code"))
                or any(effect["currency_" + key] != source["monetary_policy"][key] for key in ("precision", "rounding_policy", "registry_version", "registry_digest"))):
            fail("Cost allocation requires an original posted native Manual expense in the exact original currency policy and hierarchy.")
        if self.connection.execute("SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND reverses_effect_id=%s", (self.tenant_id, effect["id"])).fetchone():
            fail("Reversed original expenses cannot back production cost.")
        native = self.material._one("SELECT * FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND id=%s AND entry_id=%s",
            (self.tenant_id, claim["line_id"], effect["entry_id"]))
        original = next((line for line in effect["snapshot"]["lines"] if line["line_number"] == native["line_number"]), None)
        if original is None or original["debit_minor"] <= 0 or original["credit_minor"]:
            fail("A claim must identify one positive original native debit expense line.")
        account = self.material._one("SELECT * FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s", (self.tenant_id, original["account_id"]))
        wip = self.material._one("SELECT chart_id FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s", (self.tenant_id, source["wip_account_id"]))
        if account["account_type"] != "Expense" or account["chart_id"] != wip["chart_id"] or account["id"] == source["wip_account_id"]:
            fail("Only original Expense lines can be reclassified to retained WIP.")
        used = self.connection.execute("""SELECT COALESCE(sum(amount_minor),0) AS used FROM reconforge.manufacturing_execution_v2_cost_claims
            WHERE tenant_id=%s AND effect_id=%s AND line_id=%s AND state<>'Released'""", (self.tenant_id, effect["id"], native["id"])).fetchone()["used"]
        if used + claim["amount_minor"] > original["debit_minor"]:
            fail("Cumulative production claims exceed the original posted expense line.", "manufacturing_execution_v2_cost_capacity_denied")
        dimensions = {}
        for dimension, value in original["dimensions"].items():
            ref = self.material._one("""SELECT d.dimension_code,v.value_code FROM reconforge.finance_dimensions d
                JOIN reconforge.finance_dimension_values v ON v.tenant_id=d.tenant_id AND v.dimension_id=d.id
                WHERE d.tenant_id=%s AND d.id=%s AND v.id=%s""", (self.tenant_id, dimension, value))
            dimensions[ref["dimension_code"]] = ref["value_code"]
        return {**dict(claim), "original_debit_minor": original["debit_minor"], "account_id": account["id"],
                "account_code": account["account_code"], "original_line": original, "effect_validation_digest": effect["validation_digest"],
                "effect_entry_id": effect["entry_id"], "dimensions": dimensions}

    def create_order(self, request: ManufacturingOrderPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self._transaction():
            self._actor(actor, "create", args)
            wire, replay = self._command(args, "create", command_id, args, actor)
            if replay is not None:
                return replay
            self.material._binding(args["material"])
            routing = self._source(request.routing_id, read_lock=True)
            self._actor(actor, "read", routing)
            if routing["kind"] != "Routing" or routing["phase"] != 1 or routing["bom_version_id"] != request.material.bom_version_id:
                fail("The order requires its exact approved engineering BOM/routing pair.")
            if any(routing[key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")) or not routing["effective_from"] <= request.material.posting_date <= routing["effective_until"]:
                fail("Routing does not cover this original hierarchy and manufacturing business date.")
            identifier = "ME2-" + uuid4().hex.upper()
            self._material_participant = _ManufacturingV2MaterialParticipant(self, identifier)
            try:
                material = self.material.create_order(request.material, command_id="me2-material:" + command_id,
                    actor=actor, _source_owner=self._material_participant)
            finally:
                self._material_participant = None
            claims = [self._expense_claim(claim, material) for claim in cost_claims(request.claims, routing["operations"])]
            source = {**args["material"], "schema_version": "manufacturing-order-v2", "command_request": args,
                "id": identifier, "creator_id": actor.user_id, "routing_id": routing["id"], "routing_digest": routing["source_digest"],
                "operations": routing["operations"], "material_order_id": material["id"], "material_source_digest": material["source_digest"],
                "claims": claims, "monetary_policy": material["monetary_policy"], "currency_code": material["currency_code"]}
            self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_orders
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,material_order_id,routing_id,payload,source_digest)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, identifier, source["workspace_id"],
                source["organization_id"], source["legal_entity_id"], material["id"], routing["id"], canonical_json(source), digest_payload(source)))
            for claim in claims:
                claim_id = "ME2K-" + uuid4().hex.upper()
                self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_cost_claims
                    (tenant_id,id,order_id,workspace_id,organization_id,legal_entity_id,effect_id,line_id,amount_minor,payload)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, claim_id, identifier,
                    source["workspace_id"], source["organization_id"], source["legal_entity_id"], claim["effect_id"], claim["line_id"],
                    claim["amount_minor"], canonical_json(claim)))
                self.connection.execute("""INSERT INTO reconforge.financial_effect_ownership_guards
                    (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_effect_id,owner_namespace,owner_claim_id)
                    VALUES(%s,%s,%s,%s,%s,%s,'ME2',%s)""", (self.tenant_id, claim_id, source["workspace_id"],
                    source["organization_id"], source["legal_entity_id"], claim["effect_id"], claim_id))
            self._actor(actor, "create", self._source(identifier))
            return self._remember(identifier, "create", command_id, wire, actor, request.material.reason)

    def _locked_order(self, source: Mapping[str, Any], actor: PostingActor, operation: str,
                      *, period: str | None = None, date: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        self.material._binding({**source, "period_id": period or source["period_id"], "posting_date": date or source["posting_date"]})
        self.material._order(source["material_order_id"], lock=True)
        order = self._source(source["id"], lock=True)
        self._actor(actor, operation, order, lock=True)
        material = self.material._order(order["material_order_id"])
        self.material._admit(material)
        self.material._inventory_locks(material)
        return order, material

    def _post(self, entry: Mapping[str, Any], command: str, actor: PostingActor, reason: str) -> dict[str, Any]:
        self._participant = _ManufacturingV2PostingParticipant(self, entry["entry_id"])
        try:
            return self.owner.posting.post(entry["entry_id"], command_id=command, expected_validation_digest=entry["validation_digest"],
                reason=reason, actor=actor, _source_owner=self._participant)
        except BaseException:
            self._rollback_only = True
            raise
        finally:
            self._participant = None

    def _draft(self, identifier: str, source: Mapping[str, Any], lines: list[dict[str, Any]], actor: PostingActor) -> dict[str, Any]:
        entry = self.material._draft(identifier, source, lines, actor)
        header = entry["snapshot"]["entry"]
        original = source["monetary_policy"]
        if header["currency_code"] != source["currency_code"] or any(header["currency_" + key] != original[key]
                for key in ("precision", "rounding_policy", "registry_version", "registry_digest")):
            fail("Manufacturing allocation must retain its exact original monetary policy; prepare a newly approved source after policy changes.")
        return entry

    def act_order(self, identifier: str, operation: str, *, expected_digest: str, command_id: str,
                  reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"prepare", "review", "post", "cancel"}:
            fail("Unknown ME2 order operation.")
        with self._transaction():
            source = self._source(identifier)
            self._actor(actor, operation, source)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(source, operation, command_id, {"id": identifier, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            order, material = self._locked_order(source, actor, operation)
            if order["source_digest"] != expected_digest or order["phase"] not in ({0, 1, 2} if operation == "cancel" else { {"prepare": 0, "review": 1, "post": 2}[operation]}):
                fail("ME2 phase or original digest changed.")
            if operation in {"review", "post"} and actor.user_id == order["cost_entry"]["snapshot"]["entry"]["preparer_actor_id"]:
                fail("Manufacturing costing requires independent humans.")
            if operation == "post" and actor.user_id == order["reviewer_id"]:
                fail("Manufacturing costing posting requires a third human.")
            material_result = self.material.act(material["id"], operation, expected_digest=material["source_digest"],
                command_id="me2-material:" + command_id, reason=reason, actor=actor)
            if operation == "prepare":
                lines = []
                extra = sum(claim["amount_minor"] for claim in order["claims"])
                for claim in order["claims"]:
                    amount = minor_to_text(claim["amount_minor"], order["monetary_policy"]["precision"])
                    lines.extend([{"account_code": order["wip_account_code"], "debit": amount, "dimensions": claim["dimensions"]},
                                  {"account_code": claim["account_code"], "credit": amount, "dimensions": claim["dimensions"]}])
                entry = self._draft(identifier, order, lines, actor)
                total = exact_integer(material_result["issue_plan"]["total_cost_minor"] + extra, positive=True)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=1,cost_entry=%s::jsonb,total_cost_minor=%s WHERE tenant_id=%s AND id=%s",
                    (canonical_json(entry), total, self.tenant_id, identifier))
            elif operation == "review":
                self.owner.finance.validate_entry(order["cost_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=2,reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, identifier))
            elif operation == "post":
                effect = self._post(order["cost_entry"], "me2-cost:" + command_id, actor, reason)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=3,cost_effect_id=%s WHERE tenant_id=%s AND id=%s", (effect["id"], self.tenant_id, identifier))
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_cost_claims SET state='Consumed' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, identifier))
            else:
                if order["cost_entry"]:
                    self.owner.finance.void_entry(order["cost_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=5 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
                for claim in records(self.connection.execute("SELECT * FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=%s AND order_id=%s ORDER BY effect_id,line_id", (self.tenant_id, identifier))):
                    self.connection.execute("SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)", (self.tenant_id, claim["effect_id"]))
                    release_id = "ME2X-" + digest_payload([self.tenant_id, claim["id"]])[:32].upper()
                    self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_cost_releases
                        (tenant_id,id,order_id,claim_id,workspace_id,organization_id,legal_entity_id,actor_id,reason)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, release_id, identifier, claim["id"],
                        order["workspace_id"], order["organization_id"], order["legal_entity_id"], actor.user_id, reason))
                    self.connection.execute("INSERT INTO reconforge.financial_effect_ownership_releases(tenant_id,guard_id,release_id) VALUES(%s,%s,%s)", (self.tenant_id, claim["id"], release_id))
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_cost_claims SET state='Released' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, identifier))
            return self._remember(identifier, operation, command_id, wire, actor, reason)

    def produce(self, identifier: str, *, output_quantity: str, operations: list[dict[str, Any]], period_id: str,
                posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        args = {"order_id": identifier, "output_quantity": output_quantity, "operations": operations, "period_id": period_id,
                "posting_date": business_date(posting_date), "reason": text(reason, "reason", maximum=500)}
        with self._transaction():
            source = self._source(identifier)
            self._actor(actor, "prepare", source)
            wire, replay = self._command(source, "create", command_id, args, actor)
            if replay is not None:
                return replay
            order, material = self._locked_order(source, actor, "prepare", period=period_id, date=posting_date)
            if order["phase"] != 3 or posting_date < order["posting_date"]:
                fail("Production requires the complete frozen posted material/labor/overhead pool.")
            pending = self.connection.execute("SELECT 1 FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=%s AND order_id=%s AND phase IN(0,1,2)", (self.tenant_id, identifier)).fetchone()
            count = self.connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, identifier)).fetchone()["n"]
            if pending or count >= MAX_PRODUCTIONS:
                fail("Inspect or cancel the current tranche before producing another; history is bounded at two hundred attempts.")
            allocation = held_allocation(output_quantity=material["output_quantity_scaled"], total_cost=order["total_cost_minor"],
                produced_quantity=order["produced_quantity_scaled"], produced_cost=order["produced_cost_minor"], quantity=quantity(output_quantity, material["output"]["quantity_precision"]))
            production = {**{key: order[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code")},
                **args, **allocation, "schema_version": "manufacturing-held-production-v2", "id": "ME2P-" + uuid4().hex.upper(),
                "order_digest": order["source_digest"], "routing_digest": order["routing_digest"], "cost_effect_id": order["cost_effect_id"],
                "operations": operation_reports(operations, order["operations"]), "command_request": args, "preparer_id": actor.user_id}
            self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_productions
                (tenant_id,id,order_id,workspace_id,organization_id,legal_entity_id,payload,source_digest)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, production["id"], identifier, order["workspace_id"],
                order["organization_id"], order["legal_entity_id"], canonical_json(production), digest_payload(production)))
            return self._remember(production["id"], "create", command_id, wire, actor, reason)

    def act_production(self, identifier: str, operation: str, *, expected_digest: str, command_id: str,
                       reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"review", "post", "cancel"}:
            fail("Unknown production hold operation.")
        with self._transaction():
            source = self._source(identifier)
            self._actor(actor, operation, source)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(source, operation, command_id, {"id": identifier, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            order, _ = self._locked_order(self._source(source["order_id"]), actor, operation, period=source["period_id"], date=source["posting_date"])
            production = self._source(identifier, lock=True)
            self._actor(actor, operation, production, lock=True)
            if production["source_digest"] != expected_digest or production["phase"] not in ({0, 1} if operation == "cancel" else {0} if operation == "review" else {1}):
                fail("Production hold phase or digest changed.")
            if operation in {"review", "post"} and actor.user_id == production["preparer_id"] or operation == "post" and actor.user_id == production["reviewer_id"]:
                fail("Production requires distinct preparer, reviewer and poster.")
            if operation == "post":
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_productions SET phase=2 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET produced_quantity_scaled=produced_quantity_scaled+%s,produced_cost_minor=produced_cost_minor+%s WHERE tenant_id=%s AND id=%s",
                    (production["quantity_scaled"], production["held_cost_minor"], self.tenant_id, order["id"]))
            elif operation == "review":
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_productions SET phase=1,reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, identifier))
            else:
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_productions SET phase=4 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            return self._remember(identifier, operation, command_id, wire, actor, reason)

    @contextmanager
    def _receipt_context(self, identifier: str, plan: str | None) -> Iterator[_ManufacturingV2ReceiptParticipant]:
        if not self._active or self._receipt_participant is not None:
            fail("Inspected receipt requires its exact complete ME2 owner.")
        self._receipt_participant = _ManufacturingV2ReceiptParticipant(self, identifier, plan)
        try:
            yield self._receipt_participant
        except BaseException:
            self._rollback_only = True
            raise
        finally:
            self._receipt_participant = None

    def inspect(self, identifier: str, *, accepted_quantity: str, rejected_quantity: str, inspection_reference: str,
                period_id: str, posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        args = {"production_id": identifier, "accepted_quantity": accepted_quantity, "rejected_quantity": rejected_quantity,
            "inspection_reference": text(inspection_reference, "inspection_reference", maximum=500), "period_id": period_id,
            "posting_date": business_date(posting_date), "reason": text(reason, "reason", maximum=500)}
        with self._transaction():
            production = self._source(identifier)
            order = self._source(production["order_id"])
            self._actor(actor, "prepare", order)
            wire, replay = self._command(order, "create", command_id, args, actor)
            if replay is not None:
                return replay
            order, material = self._locked_order(order, actor, "prepare", period=period_id, date=posting_date)
            production = self._source(identifier, lock=True)
            self._actor(actor, "prepare", production, lock=True)
            if production["phase"] != 2 or posting_date < production["posting_date"]:
                fail("Inspection requires a posted complete quality hold and a later or equal date.")
            if self.connection.execute("SELECT 1 FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=%s AND production_id=%s AND phase IN(0,1,2)", (self.tenant_id, identifier)).fetchone():
                fail("A held production tranche already has a pending or posted disposition.")
            accepted = quantity_to_scaled(accepted_quantity, material["output"]["quantity_precision"], allow_zero=True)
            rejected = quantity_to_scaled(rejected_quantity, material["output"]["quantity_precision"], allow_zero=True)
            allocation = inspection_allocation(held_quantity=production["quantity_scaled"], held_cost=production["held_cost_minor"], accepted_quantity=accepted, rejected_quantity=rejected)
            count = self.connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, order["id"])).fetchone()["n"]
            completion_id = self._receipt_identifier(material, order["id"], posting_date, count, accepted)
            source = {**{key: order[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code", "journal_code", "currency_code", "monetary_policy", "wip_account_code", "scrap_account_code")},
                **args, **allocation, "schema_version": "manufacturing-inspection-v2", "id": completion_id,
                "order_id": order["id"], "order_digest": order["source_digest"], "production_digest": production["source_digest"],
                "preparer_id": actor.user_id, "command_request": args}
            receipt = None
            if accepted:
                with self._receipt_context(completion_id, None) as participant:
                    receipt = self.receipts.prepare_receipt(ReceiptPreparation(receipt_number=completion_id, posting_date=posting_date, period_id=period_id,
                        item_code=material["output"]["item_code"], location_code=material["finished_location_code"], quantity=scaled_to_text(accepted, decimal_places=material["output"]["quantity_precision"]),
                        total_value_minor=allocation["accepted_cost_minor"], policy_code=material["finished_policy_code"], organization_code=order["organization_code"],
                        entity_code=order["entity_code"], workspace=order["workspace_id"], reason=reason), command_id="me2-fg-prepare:" + command_id, actor=actor, _source_owner=participant)
            loss = None
            if rejected:
                amount = minor_to_text(allocation["rejected_cost_minor"], order["monetary_policy"]["precision"])
                loss = self._draft(completion_id, source, [{"account_code": order["scrap_account_code"], "debit": amount}, {"account_code": order["wip_account_code"], "credit": amount}], actor)
            source.update(receipt_plan=receipt, loss_entry=loss)
            self.connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_inspections
                (tenant_id,id,order_id,production_id,workspace_id,organization_id,legal_entity_id,payload,source_digest)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, completion_id, order["id"], identifier, order["workspace_id"],
                order["organization_id"], order["legal_entity_id"], canonical_json(source), digest_payload(source)))
            return self._remember(completion_id, "create", command_id, wire, actor, reason)

    def _receipt_identifier(self, material: Mapping[str, Any], order_id: str, date: str, count: int, accepted: int) -> str:
        latest = None
        if accepted:
            latest = self.connection.execute("""SELECT max(m.movement_number) n FROM reconforge.inventory_movements m
                JOIN reconforge.inventory_valuation_documents v ON v.tenant_id=m.tenant_id AND v.movement_id=m.id
                WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.legal_entity_id=%s AND m.movement_date=%s::date
                AND v.status='Approved' AND EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines l
                    WHERE l.tenant_id=m.tenant_id AND l.movement_id=m.id AND l.item_id=%s)""",
                (self.tenant_id, material["workspace_id"], material["legal_entity_id"], date, material["output_item_id"])).fetchone()["n"]
        for candidate in range(4096):
            identifier = "ME2C-" + digest_payload([self.tenant_id, order_id, count, candidate])[:32].upper()
            if latest is None or artifact_id(source_plan_id(material, identifier), "MOV").upper() > latest:
                return identifier
        fail("The existing native same-date receipt chronology exhausted its4096 bounded identities; use a later business date.")

    def act_inspection(self, identifier: str, operation: str, *, expected_digest: str, command_id: str,
                       reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"review", "post", "cancel"}:
            fail("Unknown quality-disposition operation.")
        with self._transaction():
            source = self._source(identifier)
            self._actor(actor, operation, source)
            reason = text(reason, "reason", maximum=500)
            wire, replay = self._command(source, operation, command_id, {"id": identifier, "expected_digest": expected_digest, "reason": reason}, actor)
            if replay is not None:
                return replay
            order, material = self._locked_order(self._source(source["order_id"]), actor, operation, period=source["period_id"], date=source["posting_date"])
            production = self._source(source["production_id"], lock=True)
            inspection = self._source(identifier, lock=True)
            self._actor(actor, operation, inspection, lock=True)
            if inspection["source_digest"] != expected_digest or inspection["phase"] not in ({0, 1} if operation == "cancel" else {0} if operation == "review" else {1}) or production["phase"] != 2:
                fail("The complete held source, inspection phase or digest changed.")
            if operation in {"review", "post"} and actor.user_id == inspection["preparer_id"] or operation == "post" and actor.user_id == inspection["reviewer_id"]:
                fail("Quality disposition needs distinct preparer, reviewer and posting humans.")
            if operation == "cancel":
                if inspection["loss_entry"]:
                    self.owner.finance.void_entry(inspection["loss_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                # IRP prepare/review retain immutable plans and review evidence.
                # Native movement/valuation/GL are born only at commit; the ME2
                # cancellation source guard seals the plan against later commit.
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_inspections SET phase=3 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            elif operation == "review":
                if inspection["receipt_plan"]:
                    with self._receipt_context(identifier, inspection["receipt_plan"]["plan_id"]) as participant:
                        self.receipts.review(inspection["receipt_plan"]["plan_id"], command_id="me2-fg-review:" + command_id,
                            expected_plan_digest=inspection["receipt_plan"]["plan_digest"], reason=reason, actor=actor, _source_owner=participant)
                if inspection["loss_entry"]:
                    self.owner.finance.validate_entry(inspection["loss_entry"]["entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_inspections SET phase=1,reviewer_id=%s WHERE tenant_id=%s AND id=%s", (actor.user_id, self.tenant_id, identifier))
            else:
                receipt_effect = loss_effect = None
                if inspection["receipt_plan"]:
                    with self._receipt_context(identifier, inspection["receipt_plan"]["plan_id"]) as participant:
                        retained = self.receipts.get_plan(inspection["receipt_plan"]["plan_id"], actor=actor, _source_owner=participant)
                        if retained["review"] is None:
                            fail("Inspected FG requires its original native independent review.")
                        receipt_effect = self.receipts.commit(inspection["receipt_plan"]["plan_id"], command_id="me2-fg-post:" + command_id,
                            expected_review_digest=retained["review"]["review_digest"], reason=reason, actor=actor, _source_owner=participant)
                if inspection["loss_entry"]:
                    loss_effect = self._post(inspection["loss_entry"], "me2-loss:" + command_id, actor, reason)
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_inspections SET phase=2,receipt_effect=%s::jsonb,loss_effect_id=%s WHERE tenant_id=%s AND id=%s",
                    (canonical_json(receipt_effect), None if loss_effect is None else loss_effect["id"], self.tenant_id, identifier))
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_productions SET phase=3 WHERE tenant_id=%s AND id=%s", (self.tenant_id, production["id"]))
                disposed = order["disposed_quantity_scaled"] + production["quantity_scaled"]
                self.connection.execute("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=%s,disposed_quantity_scaled=%s,released_cost_minor=released_cost_minor+%s WHERE tenant_id=%s AND id=%s",
                    (4 if disposed == material["output_quantity_scaled"] else 3, disposed, inspection["released_cost_minor"], self.tenant_id, order["id"]))
            return self._remember(identifier, operation, command_id, wire, actor, reason)

    def get_order(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            source = self._source(identifier)
            self.material._order(source["material_order_id"], read_lock=True)
            source = self._source(identifier, read_lock=True)
            self._actor(actor, "read", source, lock=True)
            self.connection.execute("SELECT reconforge.me2_close(%s,%s)", (self.tenant_id, identifier))
            productions = records(self.connection.execute("SELECT id FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=%s AND order_id=%s ORDER BY id", (self.tenant_id, identifier)))
            inspections = records(self.connection.execute("SELECT id FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=%s AND order_id=%s ORDER BY id", (self.tenant_id, identifier)))
            retained = []
            for row in inspections:
                inspection = self._source(row["id"])
                self._actor(actor, "read", inspection)
                if inspection["receipt_plan"]:
                    with self._receipt_context(inspection["id"], inspection["receipt_plan"]["plan_id"]) as participant:
                        backing = self.receipts.get_plan(inspection["receipt_plan"]["plan_id"], actor=actor, _source_owner=participant)
                        if backing["effect"] != inspection["receipt_effect"]:
                            fail("Inspected FG projection differs from its complete native original receipt evidence.")
                retained.append(inspection)
            return {**source, "material": self.material.get_order(source["material_order_id"], actor=actor),
                "productions": [self._source(row["id"]) for row in productions], "inspections": retained,
                "wip_minor": source["total_cost_minor"] - source["released_cost_minor"] if source["phase"] in {3, 4} else 0,
                "held_quantity_scaled": source["produced_quantity_scaled"] - source["disposed_quantity_scaled"],
                "held_cost_minor": source["produced_cost_minor"] - source["released_cost_minor"]}

    def list_sources(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self._actor(actor, "read", scope)
            orders = records(self.connection.execute("""SELECT id FROM reconforge.manufacturing_execution_v2_orders
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            definitions = records(self.connection.execute("""SELECT id FROM reconforge.manufacturing_execution_v2_definitions
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY kind,number,version LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            sources = []
            for row in definitions:
                definition = self._source(row["id"], read_lock=True)
                self._actor(actor, "read", definition)
                self.connection.execute("SELECT reconforge.me2_close(%s,%s)", (self.tenant_id, definition["id"]))
                sources.append(definition)
        # Each child owns its read transaction and rechecks current full-source authority.
        return {"orders": [self.get_order(row["id"], actor=actor) for row in orders], "definitions": sources}
