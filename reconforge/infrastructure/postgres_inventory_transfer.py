"""Caller-owned IT1 transactions over existing Core Transfer and FIFO custody."""
from __future__ import annotations

from collections.abc import Mapping
from json import loads
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text
from reconforge.domain.inventory_transfer import (
    ACK_SCHEMA_VERSION,
    PERMISSIONS,
    READ,
    TransferInversePreparation,
    TransferPreparation,
    exact_quantity,
    exact_scope,
    exposed_minor,
    fail,
    require_capacity,
    require_transition,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import platform_id


class PostgresInventoryTransferRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.inventory = PostgresInventoryCoreRepository(connection, tenant_id)

    def _one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any]:
        row = self.connection.execute(query, params).fetchone()
        if row is None:
            fail("Transfer source is absent or outside current scope.", "inventory_transfer_not_found")
        return dict(row)

    def _row(self, identifier: str, *, lock: bool = False, read_lock: bool = False) -> dict[str, Any]:
        query = "SELECT * FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s AND id=%s"
        query += " FOR UPDATE" if lock else " FOR SHARE" if read_lock else ""
        row = self._one(query, (self.tenant_id, text(identifier, "transfer_id")))
        return {**row["payload"], **{key: row[key] for key in ("phase", "row_version", "source_digest", "reviewer_actor_id",
            "poster_actor_id", "review_cost_json", "review_cost_digest", "native_creation_json", "posted_native_json")}}

    def _scope(self, source: Mapping[str, Any]) -> dict[str, str]:
        return exact_scope(source.get("scope", source))

    def _authority_locks(self, actor: PostingActor, operation: str, source: Mapping[str, Any]) -> None:
        """Pin current authority before source, metadata and quantity waits."""
        scope = self._scope(source)
        permissions = PERMISSIONS.get(operation, READ)
        if self.connection.execute("""SELECT id FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s
            AND username=%s AND NOT disabled FOR SHARE""", (self.tenant_id, actor.user_id, actor.username)).fetchone() is None:
            fail("Transfer requires a current persisted human.", "inventory_transfer_actor_denied")
        rows = records(self.connection.execute("""SELECT p.permission_name FROM reconforge.identity_user_roles a
            JOIN reconforge.identity_roles r ON r.tenant_id=a.tenant_id AND r.id=a.role_id
            JOIN reconforge.identity_role_permissions p ON p.tenant_id=r.tenant_id AND p.role_id=r.id
            WHERE a.tenant_id=%s AND a.user_id=%s AND a.active AND r.active AND p.active AND p.permission_name=ANY(%s)
            ORDER BY r.id,p.permission_name FOR SHARE OF a,r,p""", (self.tenant_id, actor.user_id, sorted(permissions))))
        if {row["permission_name"] for row in rows} != set(permissions):
            fail("Transfer requires every current persisted read and phase permission.", "inventory_transfer_actor_denied")
        grants = records(self.connection.execute("""SELECT scope_type,scope_id FROM reconforge.principal_scope_grants WHERE tenant_id=%s
            AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
            AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
                OR(scope_type='legal_entity' AND scope_id=%s)) ORDER BY scope_type,scope_id FOR SHARE""",
            (self.tenant_id, actor.user_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
        if len({(row["scope_type"], row["scope_id"]) for row in grants}) != 3:
            fail("Transfer requires every current persisted original parent grant.", "inventory_transfer_scope_denied")

    def _actor(self, actor: PostingActor, operation: str, source: Mapping[str, Any], *, lock: bool = False) -> None:
        self._authority_locks(actor, operation, source)
        scope: dict[str, Any] = self._scope(source)
        snapshots = [source[key] for key in ("cost_snapshot", "review_cost_json") if source.get(key) is not None]
        original = source.get("original")
        if isinstance(original, dict):
            snapshots.append(original["review_cost_snapshot"])
        if snapshots:
            precision = snapshots[0]["monetary_policy"]["currency_precision"]
            if any(snapshot["monetary_policy"] != snapshots[0]["monetary_policy"] for snapshot in snapshots):
                fail("Transfer originals require the same exact captured monetary policy.")
            scope.update(amount_minor=max(exposed_minor(snapshot) for snapshot in snapshots), currency_precision=precision)
        for permission in sorted(PERMISSIONS.get(operation, READ)):
            self.owner._actor(actor, permission, scope, mutation=operation != "read")
        query = """SELECT scope_type,scope_id FROM reconforge.principal_scope_grants WHERE tenant_id=%s
            AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
            AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
                OR(scope_type='legal_entity' AND scope_id=%s))"""
        if lock:
            query += " FOR SHARE"
        grants = records(self.connection.execute(query, (self.tenant_id, actor.user_id, scope["workspace_id"],
            scope["organization_id"], scope["legal_entity_id"])))
        if len({(row["scope_type"], row["scope_id"]) for row in grants}) != 3:
            fail("Transfer requires every current persisted original parent grant.", "inventory_transfer_scope_denied")

    def _context(self, identifier: str, operation: str, actor: PostingActor) -> None:
        self.connection.execute("""SELECT set_config('app.inventory_transfer_id',%s,true),
            set_config('app.inventory_transfer_actor_id',%s,true),set_config('app.inventory_transfer_operation',%s,true)""",
            (identifier, actor.user_id, operation))

    def _binding(self, args: Mapping[str, Any], *, lock: bool = False) -> dict[str, Any]:
        scope = self._scope(args)
        organization = self._one("""SELECT o.organization_code,e.entity_code FROM reconforge.organizations o
            JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
            WHERE o.tenant_id=%s AND o.id=%s AND e.id=%s AND o.application_workspace_id=%s AND o.active AND e.active""",
            (self.tenant_id, scope["organization_id"], scope["legal_entity_id"], scope["workspace_id"]))
        item = self.inventory._item(scope["workspace_id"], args["item_code"], active=True)
        if item["item_type"] not in {"Stock", "Consumable"} or item["tracking_mode"] != "None" or not item["uom_active"]:
            fail("Transfer requires an active untracked stock or consumable item and its native base unit.")
        locations = [self.inventory._location_reference(scope["workspace_id"], scope["organization_id"],
            scope["legal_entity_id"], args[key]) for key in ("from_location", "to_location")]
        if any(location is None for location in locations):
            fail("Transfer requires two actual native internal locations.")
        location_ids = [str(location["id"]) for location in locations if location is not None]
        if len(location_ids) != 2:
            fail("Transfer requires both original native locations.")
        warehouses = self._one("""SELECT count(DISTINCT w.id) warehouses,count(*) valid FROM reconforge.inventory_locations l
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
            WHERE l.tenant_id=%s AND l.id=ANY(%s) AND l.active AND l.location_type='Internal' AND NOT l.allow_negative
            AND w.active AND w.workspace_id=%s AND w.organization_id=%s AND w.legal_entity_id=%s""",
            (self.tenant_id, location_ids, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"]))
        if warehouses != {"warehouses": 2, "valid": 2}:
            fail("IT1 requires two distinct internal warehouses explicitly belonging to the same entity.")
        precision = item["decimal_places"]
        scaled, canonical_quantity = exact_quantity(args["quantity"], precision)
        if lock:
            # Metadata precedes pool and source locks. Preserve original IDs and
            # captured UOM/account interpretations through the business commit.
            self.connection.execute("SELECT 1 FROM reconforge.inventory_items WHERE tenant_id=%s AND id=%s FOR SHARE", (self.tenant_id, item["id"]))
            self.connection.execute("""SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e
                ON e.tenant_id=o.tenant_id AND e.organization_id=o.id WHERE o.tenant_id=%s AND o.id=%s AND e.id=%s FOR SHARE OF o,e""",
                (self.tenant_id, scope["organization_id"], scope["legal_entity_id"]))
            self.connection.execute("SELECT 1 FROM reconforge.inventory_units_of_measure WHERE tenant_id=%s AND id=%s FOR SHARE", (self.tenant_id, item["uom_id"]))
            self.connection.execute("SELECT 1 FROM reconforge.inventory_locations WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR SHARE", (self.tenant_id, location_ids))
            self.connection.execute("""SELECT 1 FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND id IN
                (SELECT warehouse_id FROM reconforge.inventory_locations WHERE tenant_id=%s AND id=ANY(%s)) ORDER BY id FOR SHARE""",
                (self.tenant_id, self.tenant_id, location_ids))
            # Existing Finance metadata mutation guards use this advisory key.
            # Entity-scoped FOR SHARE would invoke the narrower UPDATE RLS
            # policy for shared account metadata and is not a read authority.
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(%s::text,%s::text,%s::text)::text,0))",
                (self.tenant_id, "finance_accounts", item["inventory_account_id"]))
            # Re-read after a potentially queued metadata lock; no stale admission.
            return self._binding(args)
        period = self._one("""SELECT status,start_date::text,end_date::text,application_workspace_id FROM reconforge.fiscal_periods
            WHERE tenant_id=%s AND id=%s FOR SHARE""", (self.tenant_id, args["period_id"]))
        if period["application_workspace_id"] != scope["workspace_id"] or period["status"] != "Open" or not period["start_date"] <= args["posting_date"] <= period["end_date"]:
            fail("Transfer requires its current scoped open period and original business date.")
        account = self._one("SELECT active,workspace_id FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, item["inventory_account_id"]))
        if not account["active"] or account["workspace_id"] != scope["workspace_id"]:
            fail("Transfer requires the original active scoped inventory account.")
        return {**organization, "item_id": item["id"], "uom_id": item["uom_id"], "quantity_precision": precision,
            "quantity_scaled": scaled, "quantity": canonical_quantity, "inventory_account_id": item["inventory_account_id"],
            "from_location_id": location_ids[0], "to_location_id": location_ids[1]}

    def _pool_locks(self, source: Mapping[str, Any]) -> None:
        scope = self._scope(source)
        self.connection.execute("SELECT reconforge.inventory_quantity_source_pool_lock(%s,%s,%s,%s)",
            (self.tenant_id, scope["workspace_id"], scope["legal_entity_id"], source["item_id"]))
        for location in sorted({source["from_location_id"], source["to_location_id"]}):
            self.connection.execute("SELECT reconforge.touch_inventory_quantity_claim_gate(%s,%s,%s,%s,%s)",
                (self.tenant_id, scope["workspace_id"], scope["legal_entity_id"], source["item_id"], location))

    def _cost(self, source: Mapping[str, Any]) -> dict[str, Any]:
        scope = self._scope(source)
        return dict(self._one("SELECT reconforge.it1_cost_snapshot(%s,%s,%s,%s,%s) value",
            (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], source["item_id"]))["value"])

    def _native(self, identifier: str) -> dict[str, Any]:
        return dict(self._one("SELECT reconforge.it1_native_snapshot(%s,%s) value", (self.tenant_id, identifier))["value"])

    def _locked(self, source: Mapping[str, Any], operation: str, actor: PostingActor) -> dict[str, Any]:
        binding = self._binding(source, lock=True)
        if any(source[key] != value for key, value in binding.items()):
            fail("Current native item, UOM, account and location interpretations differ from the original transfer.")
        self._pool_locks(source)
        source = self._row(source["id"], lock=True)
        self._actor(actor, operation, source, lock=True)
        self._context(source["id"], operation, actor)
        return dict(source)

    def _command(self, source: Mapping[str, Any], operation: str, command_id: str,
                 request: Mapping[str, Any], actor: PostingActor) -> tuple[dict[str, Any], dict[str, Any] | None]:
        command = text(command_id, "command_id", maximum=140)
        wire = loads(canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}))
        scope = self._scope(source)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "inventory-transfer", command]),))
        retained = self.connection.execute("""SELECT * FROM reconforge.inventory_transfer_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, scope["workspace_id"], command)).fetchone()
        if retained is None:
            return wire, None
        if retained["request_json"] != wire or retained["request_digest"] != digest_payload(wire):
            fail("This transfer command belongs to another exact actor, body or source.", "inventory_transfer_command_conflict")
        current = self._row(retained["transfer_id"])
        self._actor(actor, operation, current, lock=True)
        current = self._row(retained["transfer_id"], read_lock=True)
        # Historical replay needs current financial/scope authority but no new
        # open-period or metadata admission: it has zero new native effects.
        self._actor(actor, operation, current, lock=True)
        self.connection.execute("SELECT reconforge.it1_close(%s,%s)", (self.tenant_id, current["id"]))
        return wire, dict(retained["response_json"])

    def _remember(self, identifier: str, operation: str, command_id: str, wire: Mapping[str, Any],
                  actor: PostingActor, reason: str) -> dict[str, Any]:
        source = self._row(identifier)
        self._actor(actor, operation, source, lock=True)
        metadata = {"source_digest": source["source_digest"], "version": source["row_version"], "operation": operation, "reason": reason}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="inventory_transfer", object_id=identifier,
            action="inventory_transfer." + operation, metadata=metadata)
        outbox = "OBX-" + uuid4().hex
        scope = self._scope(source)
        self.connection.execute("""INSERT INTO reconforge.outbox_events
            (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
            VALUES(%s,%s,%s,'inventory_transfer',%s,%s,%s,%s,%s::jsonb)""", (self.tenant_id, outbox, "inventory_transfer." + operation,
            identifier, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], canonical_json({**metadata, "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.inventory_transfer_events
            (tenant_id,transfer_id,version,operation,actor_id,request_json,request_digest,reason,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""", (self.tenant_id, identifier, source["row_version"], operation,
            actor.user_id, canonical_json(wire), digest_payload(wire), reason, audit.id, outbox))
        public = self._one("SELECT reconforge.it1_public(%s,%s,%s) value", (self.tenant_id, identifier, source["row_version"]))["value"]
        response = {"source": public, "native_response": public["native_response"]}
        self.connection.execute("""INSERT INTO reconforge.inventory_transfer_commands
            (tenant_id,workspace_id,command_id,transfer_id,version,operation,actor_id,request_json,request_digest,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""", (self.tenant_id, scope["workspace_id"], command_id, identifier,
            source["row_version"], operation, actor.user_id, canonical_json(wire), digest_payload(wire), canonical_json(response)))
        self.connection.execute("SELECT reconforge.it1_close(%s,%s)", (self.tenant_id, identifier))
        return response

    def _create(self, args: dict[str, Any], command_id: str, actor: PostingActor, *, original: Mapping[str, Any] | None = None,
                submitted: Mapping[str, Any] | None = None) -> dict[str, Any]:
        operation = "inverse-create" if original is not None else "create"
        wire, replay = self._command(args, operation, command_id, submitted or args, actor)
        if replay is not None:
            return replay
        self._authority_locks(actor, operation, args)
        binding = self._binding(args, lock=True)
        identifier = "IT1-S-" + uuid4().hex.upper()
        number = "IT1-" + identifier[-32:]
        source = {**args, **binding, "id": identifier, "creator_actor_id": actor.user_id,
            "native_movement_id": platform_id("MOV", args["scope"]["workspace_id"], number),
            "command_request": dict(submitted or args), "original": None if original is None else {
                "id": original["id"], "source_digest": original["source_digest"], "version": original["row_version"],
                "native_response": original["posted_native_json"], "review_cost_snapshot": original["review_cost_json"]}}
        self._pool_locks(source)
        source["cost_snapshot"] = self._cost(source)
        self._actor(actor, operation, source, lock=True)
        self._context(identifier, operation, actor)
        self.inventory.create_movement(movement_number=number, movement_type="Transfer", workspace=args["scope"]["workspace_id"],
            organization_code=binding["organization_code"], entity_code=binding["entity_code"], period_id=args["period_id"],
            movement_date=args["posting_date"], description=args["reason"], source_reference=identifier, source_type="Generated",
            actor_label=actor.user_id, lines=[{"item_code": args["item_code"], "quantity": binding["quantity"],
                "from_location": args["from_location"], "to_location": args["to_location"], "description": args["reason"]}])
        scope = args["scope"]
        self.connection.execute("""INSERT INTO reconforge.inventory_transfer_sources
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,number,original_transfer_id,item_id,uom_id,quantity_precision,
             quantity_scaled,from_location_id,to_location_id,period_id,posting_date,payload,source_digest,creator_actor_id,native_movement_id,native_creation_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb)""", (self.tenant_id, identifier,
            scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], args["number"], original["id"] if original else None,
            binding["item_id"], binding["uom_id"], binding["quantity_precision"], binding["quantity_scaled"], binding["from_location_id"],
            binding["to_location_id"], args["period_id"], args["posting_date"], canonical_json(source), digest_payload(source), actor.user_id,
            source["native_movement_id"], canonical_json(self._native(source["native_movement_id"]))))
        return self._remember(identifier, operation, command_id, wire, actor, args["reason"])

    def create(self, request: TransferPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            return self._create(request.payload(), command_id, actor)

    def create_inverse(self, request: TransferInversePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        submitted = request.payload()
        with self.owner._transaction():
            original = self._row(request.original_id)
            self._actor(actor, "inverse-create", original, lock=True)
            original = self._row(request.original_id, read_lock=True)
            self._actor(actor, "inverse-create", original, lock=True)
            args = {key: original[key] for key in ("schema_version", "item_code", "quantity", "scope")}
            args.update(number=submitted["number"], period_id=submitted["period_id"], posting_date=submitted["posting_date"],
                reason=submitted["reason"], from_location=original["to_location"], to_location=original["from_location"])
            wire, replay = self._command(args, "inverse-create", command_id, submitted, actor)
            if replay is not None:
                return replay
            if original["phase"] != 2 or original["original"] is not None or original["source_digest"] != request.expected_digest or original["row_version"] != request.expected_version:
                fail("Inverse requires the exact original Posted forward source.", "inventory_transfer_state_conflict")
            return self._create(args, command_id, actor, original=original, submitted=submitted)

    def _capacity(self, source: Mapping[str, Any]) -> None:
        scope = self._scope(source)
        totals = self._one("""SELECT COALESCE(sum(CASE WHEN l.to_location_id=%s THEN l.quantity_scaled ELSE 0 END
            -CASE WHEN l.from_location_id=%s THEN l.quantity_scaled ELSE 0 END),0) physical
            FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id
            WHERE l.tenant_id=%s AND m.workspace_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND l.item_id=%s AND l.inventory_lot_id IS NULL""",
            (source["from_location_id"], source["from_location_id"], self.tenant_id, scope["workspace_id"], scope["legal_entity_id"], source["item_id"]))
        reserved = self._one("""SELECT COALESCE(sum(quantity_scaled),0) reserved FROM (
            SELECT g.quantity_scaled FROM reconforge.inventory_quantity_source_guards g
            WHERE g.tenant_id=%s AND g.workspace_id=%s AND g.legal_entity_id=%s AND g.item_id=%s AND g.location_id=%s
            AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases r WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id)
            UNION ALL SELECT quantity_scaled FROM reconforge.stock_sales_reservations WHERE tenant_id=%s AND workspace_id=%s AND legal_entity_id=%s
             AND item_id=%s AND location_id=%s AND state='Active'
            UNION ALL SELECT quantity_scaled FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=%s AND workspace_id=%s AND legal_entity_id=%s
             AND item_id=%s AND location_id=%s AND state='Active') current_reservations""",
            tuple(value for _ in range(3) for value in (self.tenant_id, scope["workspace_id"], scope["legal_entity_id"], source["item_id"], source["from_location_id"])))
        fifo = self._one("SELECT reconforge.inventory_quantity_free_fifo(%s,%s,%s,%s) free",
            (self.tenant_id, scope["workspace_id"], scope["legal_entity_id"], source["item_id"]))
        require_capacity(source["quantity_scaled"], int(totals["physical"]), int(reserved["reserved"]), int(fifo["free"]))

    def act(self, identifier: str, operation: str, *, expected_digest: str, expected_version: int,
            command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in {"review", "post", "cancel"}:
            fail("Transfer operation must belong to the closed governed phase contract.")
        submitted: dict[str, Any] = {"id": text(identifier, "transfer_id"), "expected_digest": text(expected_digest, "expected_digest", maximum=64),
            "expected_version": expected_version, "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            source = self._row(identifier)
            self._actor(actor, operation, source)
            wire, replay = self._command(source, operation, command_id, submitted, actor)
            if replay is not None:
                return replay
            source = self._locked(source, operation, actor)
            if source["source_digest"] != expected_digest or source["row_version"] != expected_version or type(expected_version) is not int:
                fail("Transfer source changed; use its exact original digest and current version.", "inventory_transfer_state_conflict")
            phase = require_transition(source["phase"], operation, source["creator_actor_id"], source["reviewer_actor_id"], actor.user_id)
            scope = self._scope(source)
            if operation == "review":
                self._capacity(source)
                cost = self._cost(source)
                self._actor(actor, operation, {**source, "review_cost_json": cost}, lock=True)
                self.connection.execute("""UPDATE reconforge.inventory_transfer_sources SET phase=1,row_version=2,
                    reviewer_actor_id=%s,review_cost_json=%s::jsonb,review_cost_digest=%s WHERE tenant_id=%s AND id=%s""",
                    (actor.user_id, canonical_json(cost), digest_payload(cost), self.tenant_id, identifier))
                claim_id = "IT1-K-" + uuid4().hex.upper()
                values = (self.tenant_id, claim_id, identifier, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"],
                    source["item_id"], source["uom_id"], source["quantity_precision"], source["from_location_id"], source["quantity_scaled"])
                self.connection.execute("""INSERT INTO reconforge.inventory_transfer_claims
                    (tenant_id,id,transfer_id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,quantity_scaled,created_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2)""", values)
                self.connection.execute("""INSERT INTO reconforge.inventory_quantity_source_guards
                    (tenant_id,id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,quantity_scaled,
                     owner_namespace,owner_claim_id,warehouse_id,inventory_account_id,item_type,item_organization_key,warehouse_entity_key)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'IT1',%s,'','','Stock','','')""",
                    (self.tenant_id, claim_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], source["item_id"],
                        source["uom_id"], source["quantity_precision"], source["from_location_id"], source["quantity_scaled"], claim_id))
            else:
                if operation == "post" and self._cost(source) != source["review_cost_json"]:
                    fail("The reviewed complete FIFO/GL snapshot changed; cancel and prepare a new reviewed source.", "inventory_transfer_cost_conflict")
                claim = self.connection.execute("SELECT * FROM reconforge.inventory_transfer_claims WHERE tenant_id=%s AND transfer_id=%s",
                    (self.tenant_id, identifier)).fetchone()
                if claim is not None:
                    release = "IT1-R-" + uuid4().hex.upper()
                    self.connection.execute("""INSERT INTO reconforge.inventory_transfer_releases
                        (tenant_id,id,transfer_id,claim_id,workspace_id,organization_id,legal_entity_id,purpose,target_movement_id,actor_id,reason,created_version)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,3)""", (self.tenant_id, release, identifier, claim["id"], scope["workspace_id"],
                        scope["organization_id"], scope["legal_entity_id"], "Post" if operation == "post" else "Cancel",
                        source["native_movement_id"] if operation == "post" else None, actor.user_id, submitted["reason"]))
                    self.connection.execute("INSERT INTO reconforge.inventory_quantity_source_releases(tenant_id,guard_id,release_id,owner_namespace) VALUES(%s,%s,%s,'IT1')",
                        (self.tenant_id, claim["id"], release))
                    self.connection.execute("UPDATE reconforge.inventory_transfer_claims SET state=%s WHERE tenant_id=%s AND id=%s",
                        ("Posted" if operation == "post" else "Released", self.tenant_id, claim["id"]))
                if operation == "post":
                    self.inventory.post_movement(source["native_movement_id"], reason=submitted["reason"], actor_label=actor.user_id)
                    if self._cost(source) != source["review_cost_json"]:
                        fail("Transfer must preserve complete pooled FIFO and original posted GL bytes.", "inventory_transfer_cost_conflict")
                    self.connection.execute("""UPDATE reconforge.inventory_transfer_sources SET phase=2,row_version=row_version+1,
                        poster_actor_id=%s,posted_native_json=%s::jsonb WHERE tenant_id=%s AND id=%s""",
                        (actor.user_id, canonical_json(self._native(source["native_movement_id"])), self.tenant_id, identifier))
                else:
                    self.connection.execute("UPDATE reconforge.inventory_transfer_sources SET phase=%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                        (phase, self.tenant_id, identifier))
            return self._remember(identifier, operation, command_id, wire, actor, submitted["reason"])

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._row(identifier)
            self._actor(actor, "read", source, lock=True)
            source = self._row(identifier, read_lock=True)
            self._actor(actor, "read", source, lock=True)
            self.connection.execute("SELECT reconforge.it1_close(%s,%s)", (self.tenant_id, identifier))
            return dict(self._one("SELECT reconforge.it1_public(%s,%s,%s) value", (self.tenant_id, identifier, source["row_version"]))["value"])

    def list_transfers(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        selected = exact_scope(scope)
        with self.owner._transaction():
            rows = records(self.connection.execute("""SELECT id FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY number,id LIMIT 101""",
                (self.tenant_id, selected["workspace_id"], selected["organization_id"], selected["legal_entity_id"])))
            if len(rows) > 100:
                fail("Transfer listing exceeds the bounded complete source limit; use exact source lookup.")
            if not rows:
                self._actor(actor, "read", selected, lock=True)
            return {"transfers": [self.get(row["id"], actor=actor) for row in rows]}

    def command_receipt(self, identifier: str, command_id: str, response: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        source = self._row(identifier)
        retained = self._one("""SELECT * FROM reconforge.inventory_transfer_commands
            WHERE tenant_id=%s AND workspace_id=%s AND transfer_id=%s AND command_id=%s""",
            (self.tenant_id, source["scope"]["workspace_id"], identifier, command_id))
        self._actor(actor, retained["operation"], source, lock=True)
        source = self._row(identifier, read_lock=True)
        self._actor(actor, retained["operation"], source, lock=True)
        if retained["actor_id"] != actor.user_id or retained["response_json"] != dict(response):
            fail("Transfer ACK must be this human's exact original retained command.", "inventory_transfer_command_conflict")
        self.connection.execute("SELECT reconforge.it1_evidence(%s,%s,%s)", (self.tenant_id, identifier, retained["version"]))
        return {"schema_version": ACK_SCHEMA_VERSION, "command_id": command_id, "transfer_id": identifier,
            "source_digest": source["source_digest"], "scope": source["scope"], "version": retained["version"],
            "operation": retained["operation"], "actor_id": retained["actor_id"], "request_json": retained["request_json"],
            "request_digest": retained["request_digest"], "native_movement_id": source["native_movement_id"]}

    def evidence(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self.get(identifier, actor=actor)
            events = records(self.connection.execute("SELECT to_jsonb(e) original FROM reconforge.inventory_transfer_events e WHERE tenant_id=%s AND transfer_id=%s ORDER BY version",
                (self.tenant_id, identifier)))
            commands = records(self.connection.execute("SELECT to_jsonb(c) original FROM reconforge.inventory_transfer_commands c WHERE tenant_id=%s AND transfer_id=%s ORDER BY version",
                (self.tenant_id, identifier)))
            return {"schema_version": "inventory-transfer-evidence-v1", "source": source,
                "events": [row["original"] for row in events], "commands": [row["original"] for row in commands]}
