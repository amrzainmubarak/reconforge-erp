"""Atomic paid landed cost, existing receipt/FIFO/AP sources and native GL."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, validation_digest
from reconforge.domain.landed_cost import MAX_MINOR, LandedCostPreparation, allocate_minor, normalize
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.procurement_partial import (
    PartialQuantityPreparation,
    ProcurementPartialError,
    normalize_part,
    require_third_poster,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from reconforge.platform.common import platform_id


class _LandedCostPostingParticipant:
    def __init__(self, owner: PostgresLandedCostRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class _LandedCostReceivingParticipant:
    def __init__(self, owner: PostgresLandedCostRepository, order_id: str, receipt_id: str) -> None:
        self.owner, self.order_id, self.receipt_id = owner, order_id, receipt_id

    def admits(self, connection: Any, tenant_id: str, order_id: str, receipt_id: str) -> bool:
        return (self.owner._receiving_participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.order_id == order_id and self.receipt_id == receipt_id)


class PostgresLandedCostRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.purchase = PostgresProcurementPartialRepository(connection, tenant_id)
        self.finance = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _LandedCostPostingParticipant | None = None
        self._receiving_participant: _LandedCostReceivingParticipant | None = None

    def _row(self, identifier: str) -> dict[str, Any]:
        return self.purchase._one("SELECT * FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                  (self.tenant_id, identifier))

    def _authorize(self, row: Mapping[str, Any], actor: PostingActor, operation: str, amount: int) -> None:
        scoped = {**row, "total_minor": int(row["total_minor"]) + amount}
        receipt_action = {"prepare": "prepare-receipt", "review": "review-receipt", "post": "receive", "read": "read"}[operation]
        self.purchase.shared._authorize(scoped, actor, receipt_action)
        if operation != "read":
            self.purchase.shared._authorize(scoped, actor, {"prepare": "prepare-payment", "review": "review-payment", "post": "pay"}[operation])

    def _command(self, row: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        from reconforge.domain.inventory_receipt_posting import exact_text
        command = exact_text(command, maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, row["workspace_id"], "landed-cost", command]),))
        cancelled = self._cancellation(command_id=command, workspace_id=str(row["workspace_id"]))
        if cancelled is not None:
            raise ProcurementPartialError("landed_cost_command_conflict", "Command already belongs to retained cancellation evidence.")
        retained = self.connection.execute("SELECT * FROM reconforge.landed_cost_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                            (self.tenant_id, row["workspace_id"], command)).fetchone()
        if retained is None:
            return digest, None
        if (retained["operation"], retained["actor_id"], retained["request_digest"]) != (operation, actor.user_id, digest):
            raise ProcurementPartialError("landed_cost_command_conflict", "Command belongs to another exact request or human.")
        self.connection.execute("SELECT reconforge.landed_cost_close(%s,%s)", (self.tenant_id, retained["plan_id"]))
        return digest, dict(retained["response_json"])

    def _event(self, plan: Mapping[str, Any], action: str, actor: PostingActor) -> tuple[str, str]:
        metadata = {"plan_digest": plan["plan_digest"]}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="landed_cost", object_id=plan["id"], action=action, metadata=metadata)
        outbox = "LCOUT-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,
            workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,%s,'landed_cost',%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, outbox, action, plan["id"], plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"],
             canonical_json({**metadata, "audit_event_id": audit.id})))
        return audit.id, outbox

    def _view(self, identifier: str) -> dict[str, Any]:
        row = self._row(identifier)
        payload = row["payload"]
        allocations = self.connection.execute("""SELECT a.*,r.receipt_plan_id,r.stage FROM reconforge.landed_cost_allocations a
            JOIN reconforge.procurement_partial_receipts r ON r.tenant_id=a.tenant_id AND r.id=a.receipt_id
            WHERE a.tenant_id=%s AND a.plan_id=%s ORDER BY a.sequence""", (self.tenant_id, identifier)).fetchall()
        review = self.connection.execute("SELECT reviewer_actor_id FROM reconforge.landed_cost_reviews WHERE tenant_id=%s AND plan_id=%s",
                                          (self.tenant_id, identifier)).fetchone()
        link = self.connection.execute("SELECT posted_actor_id,posting_effect_id FROM reconforge.landed_cost_links WHERE tenant_id=%s AND plan_id=%s",
                                        (self.tenant_id, identifier)).fetchone()
        result = {"id": identifier, "order_id": row["order_id"], "number": payload["request"]["number"],
            "workspace_id": row["workspace_id"], "organization_id": row["organization_id"], "legal_entity_id": row["legal_entity_id"],
            "phase": row["phase"], "status": ("Prepared", "Reviewed", "Posted")[row["phase"]],
            "plan_digest": row["plan_digest"], "freight_minor": str(payload["request"]["freight_minor"]),
            "duty_minor": str(payload["request"]["duty_minor"]), "amount_minor": str(row["amount_minor"]),
            "currency_code": payload["snapshot"]["entry"]["currency_code"], "entry_id": row["entry_id"],
            "preparer_actor_id": payload["preparer_actor_id"], "reviewer_actor_id": review["reviewer_actor_id"] if review else None,
            "posted_actor_id": link["posted_actor_id"] if link else None, "posting_effect_id": link["posting_effect_id"] if link else None,
            "allocations": [{key: str(value) if key in {"base_minor", "freight_minor", "duty_minor"} else value
                             for key, value in dict(item).items() if key not in {"tenant_id", "plan_id", "order_id"}} for item in allocations]}
        cancelled = self._cancellation(plan_id=identifier)
        if cancelled is not None:
            result.update(status="Cancelled", cancellation=self._cancellation_projection(cancelled))
        return result

    def _cancellation(self, *, plan_id: str | None = None, command_id: str | None = None,
                      workspace_id: str | None = None) -> dict[str, Any] | None:
        if not self.connection.execute("SELECT to_regclass('reconforge.landed_cost_cancellations') IS NOT NULL AS installed").fetchone()["installed"]:
            return None
        query = ("SELECT * FROM reconforge.landed_cost_cancellations WHERE tenant_id=%s AND plan_id=%s" if plan_id is not None
                 else "SELECT * FROM reconforge.landed_cost_cancellations WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s")
        args = (self.tenant_id, plan_id) if plan_id is not None else (self.tenant_id, workspace_id, command_id)
        row = self.connection.execute(query, args).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _cancellation_projection(row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("actor_id", "reason", "command_id", "audit_event_id", "outbox_event_id")}

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  request: Mapping[str, Any], digest: str) -> dict[str, Any]:
        result = self._view(str(plan["id"]))
        self.connection.execute("""INSERT INTO reconforge.landed_cost_commands(tenant_id,workspace_id,plan_id,operation,command_id,
            actor_id,request_digest,request_json,response_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["id"], operation, command, actor.user_id, digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        return result

    def prepare(self, request: LandedCostPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = normalize(request)
        with self.connection.transaction():
            self.purchase._scope_transaction()
            parent = self.purchase._order(request.order_id, lock=True)
            amount = request.freight_minor + request.duty_minor
            self._authorize(parent, actor, "prepare", amount)
            self.purchase._require_multiline(parent)
            digest, replay = self._command(parent, "prepare", command_id, actor, asdict(request))
            if replay is not None:
                return replay
            if parent["row_version"] != request.expected_version or parent["stage"] != 2:
                raise ProcurementPartialError("landed_cost_version_conflict", "Reload the current approved purchase order before preparing paid charges.")
            if self.connection.execute("SELECT count(*) n FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND order_id=%s",
                                       (self.tenant_id, request.order_id)).fetchone()["n"] >= 200:
                raise ProcurementPartialError("landed_cost_limit", "The order exceeds its 200-bundle evidence budget.")
            if self.connection.execute("SELECT 1 FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND order_id=%s AND payload#>>'{request,number}'=%s",
                                       (self.tenant_id, request.order_id, request.number)).fetchone() is not None:
                raise ProcurementPartialError("landed_cost_number_conflict", "This paid-charge number already belongs to retained evidence for the purchase.")
            parts = []
            for allocation in sorted(request.lines, key=lambda value: value.line_id):
                line = self.purchase._one("SELECT * FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                                          (self.tenant_id, parent["id"], allocation.line_id))
                part, base = normalize_part(PartialQuantityPreparation(quantity=allocation.quantity, posting_date=request.posting_date,
                    period_id=request.period_id, reason=request.reason), line["unit_price_minor"])
                parts.append((line, part, base))
            weights = tuple((line["id"], base) for line, _, base in parts)
            freight, duties = allocate_minor(request.freight_minor, weights), allocate_minor(request.duty_minor, weights)
            if any(base + freight[line["id"]] + duties[line["id"]] > MAX_MINOR for line, _, base in parts):
                raise ProcurementPartialError("landed_cost_amount_invalid", "Capitalized receipt cost exceeds supported exact native bounds.")
            identifier = "LC1-" + uuid4().hex
            initial = self.connection.execute("SELECT COALESCE(max(sequence),0) n FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s",
                                               (self.tenant_id, parent["id"])).fetchone()["n"]
            retained = []
            for index, (line, part, base) in enumerate(parts, start=1):
                retained.append({"sequence": index, "order_line_id": line["id"], "quantity_text": part.quantity,
                    "base_minor": base, "freight_minor": freight[line["id"]], "duty_minor": duties[line["id"]],
                    "receipt_id": platform_id("PPRECEIPT", parent["id"], initial + index)})
            mapping = self.purchase._one("""SELECT p.receipt_clearing_account_id,a.account_code FROM reconforge.inventory_valuation_policies p
                JOIN reconforge.finance_accounts a ON a.tenant_id=p.tenant_id AND a.id=p.receipt_clearing_account_id
                WHERE p.tenant_id=%s AND p.id=%s""", (self.tenant_id, parts[0][0]["policy_id"]))
            for line, _, _ in parts:
                if self.purchase._one("SELECT receipt_clearing_account_id FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND id=%s",
                                       (self.tenant_id, line["policy_id"]))["receipt_clearing_account_id"] != mapping["receipt_clearing_account_id"]:
                    raise ProcurementPartialError("landed_cost_mapping_invalid", "The bundle requires one retained clearing mapping.")
            original = parent["request_json"]
            precision = self.purchase._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active",
                                           (self.tenant_id, original["currency_code"]))["minor_units"]
            paid = exact_minor_text(amount, precision)
            entry = self.finance.finance.create_entry(entry_number=identifier.upper(), workspace=parent["workspace_id"],
                organization_code=original["organization_code"], entity_code=original["entity_code"], journal_code=original["journal_code"],
                posting_date=request.posting_date, period_id=request.period_id, description=request.reason,
                external_reference="LANDED-COST:" + identifier, actor_label=actor.username,
                lines=[{"account_code": mapping["account_code"], "debit": paid, "credit": "0", "description": request.reason},
                       {"account_code": original["cash_account_code"], "debit": "0", "credit": paid, "description": request.reason}])
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if snapshot["entry"]["currency_code"] != original["currency_code"]:
                raise ProcurementPartialError("landed_cost_currency_invalid", "Landed cost and purchase must use the same functional currency.")
            payload = {"schema_version": "landed-cost-v1", "id": identifier, "request": asdict(request), "allocations": retained,
                "entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot),
                "preparer_actor_id": actor.user_id, **{key: parent[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}}
            seal = digest_payload(payload)
            plan = {**payload, "plan_digest": seal}
            audit, outbox = self._event(plan, "landed_cost_prepared", actor)
            self.connection.execute("""INSERT INTO reconforge.landed_cost_plans(tenant_id,id,order_id,workspace_id,organization_id,
                legal_entity_id,entry_id,amount_minor,phase,payload,plan_digest,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, identifier, parent["id"], parent["workspace_id"], parent["organization_id"], parent["legal_entity_id"],
                 entry["id"], amount, canonical_json(payload), seal, audit, outbox))
            for captured in retained:
                self.connection.execute("""INSERT INTO reconforge.landed_cost_allocations(tenant_id,plan_id,order_id,sequence,order_line_id,
                    quantity_text,base_minor,freight_minor,duty_minor,receipt_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, identifier, parent["id"], *captured.values()))
            for index, (line, part, _) in enumerate(parts, start=1):
                current = self.purchase._order(parent["id"])
                self._receiving_participant = _LandedCostReceivingParticipant(self, parent["id"], retained[index - 1]["receipt_id"])
                try:
                    self.purchase.prepare_receipt_line(parent["id"], line["id"], part, expected_version=current["row_version"],
                        command_id=platform_id("LCCMD", identifier, "prepare", index), actor=actor, _source_owner=self._receiving_participant)
                finally:
                    self._receiving_participant = None
            return self._remember(plan, "prepare", command_id, actor, asdict(request), digest)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self.purchase._scope_transaction()
            plan = self._row(identifier)
            self._authorize(self.purchase._order(plan["order_id"]), actor, "read", plan["amount_minor"])
            self.connection.execute("SELECT reconforge.landed_cost_close(%s,%s)", (self.tenant_id, identifier))
            return self._view(identifier)

    def list_for_order(self, order_id: str, *, actor: PostingActor, after: str = "") -> dict[str, Any]:
        with self.connection.transaction():
            self.purchase._scope_transaction()
            self._authorize(self.purchase._order(order_id), actor, "read", 0)
            if after and self.connection.execute("SELECT 1 FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND order_id=%s AND id=%s",
                                                 (self.tenant_id, order_id, after)).fetchone() is None:
                raise ProcurementPartialError("landed_cost_cursor_invalid", "Cursor must identify a bundle in the same current purchase scope.")
            rows = self.connection.execute("SELECT id FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND order_id=%s AND id>%s ORDER BY id LIMIT 5",
                                            (self.tenant_id, order_id, after)).fetchall()
            return {"records": [self.get(row["id"], actor=actor) for row in rows[:4]],
                    "next_after": rows[3]["id"] if len(rows) == 5 else None}

    def act(self, identifier: str, operation: str, *, expected_plan_digest: str, command_id: str,
            reason: str, actor: PostingActor) -> dict[str, Any]:
        from reconforge.domain.inventory_receipt_posting import exact_text
        if operation not in {"review", "post"}:
            raise ProcurementPartialError("landed_cost_operation_invalid", "A retained review or atomic publication is required.")
        reason = exact_text(reason, maximum=500)
        request = {"plan_id": identifier, "expected_plan_digest": expected_plan_digest, "reason": reason}
        with self.connection.transaction():
            self.purchase._scope_transaction()
            plan = self._row(identifier)
            parent = self.purchase._order(plan["order_id"], lock=True)
            self._authorize(parent, actor, operation, plan["amount_minor"])
            digest, replay = self._command(plan, operation, command_id, actor, request)
            if replay is not None:
                return replay
            if self._cancellation(plan_id=identifier) is not None:
                raise ProcurementPartialError("landed_cost_cancelled_conflict", "Retained cancelled receiving cannot progress to review or publication.")
            if plan["phase"] != (0 if operation == "review" else 1) or plan["plan_digest"] != expected_plan_digest:
                raise ProcurementPartialError("landed_cost_phase_conflict", "The current retained bundle stage and digest are required.")
            payload = plan["payload"]
            if operation == "review":
                if actor.user_id == payload["preparer_actor_id"]:
                    raise ProcurementPartialError("landed_cost_duties_conflict", "The preparer cannot review paid charges.")
            else:
                require_third_poster(payload["preparer_actor_id"], self._view(identifier)["reviewer_actor_id"], actor.user_id)
            for allocation in payload["allocations"]:
                current = self.purchase._order(parent["id"])
                self.purchase.act(parent["id"], "review-receipt" if operation == "review" else "receive",
                    expected_version=current["row_version"], command_id=platform_id("LCCMD", identifier, operation, allocation["sequence"]),
                    reason=reason, actor=actor, document_id=allocation["receipt_id"])
            if operation == "review":
                self.finance.finance.validate_entry(plan["entry_id"], reason=reason, actor_label=actor.username)
                audit, outbox = self._event(plan, "landed_cost_reviewed", actor)
                self.connection.execute("""INSERT INTO reconforge.landed_cost_reviews(tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id)
                    VALUES(%s,%s,%s,%s,%s,%s)""", (self.tenant_id, identifier, actor.user_id, reason, audit, outbox))
            else:
                self._participant = _LandedCostPostingParticipant(self, plan["entry_id"])
                try:
                    effect = self.finance.posting.post(plan["entry_id"], command_id="LC1:" + command_id,
                        expected_validation_digest=payload["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                audit, outbox = self._event(plan, "landed_cost_posted", actor)
                self.connection.execute("""INSERT INTO reconforge.landed_cost_links(tenant_id,plan_id,posting_effect_id,posted_actor_id,reason,audit_event_id,outbox_event_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, identifier, effect["id"], actor.user_id, reason, audit, outbox))
            self.connection.execute("UPDATE reconforge.landed_cost_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
            return self._remember({**payload, "plan_digest": plan["plan_digest"]}, operation, command_id, actor, request, digest)

    def cancel(self, identifier: str, *, expected_plan_digest: str, command_id: str,
               reason: str, actor: PostingActor) -> dict[str, Any]:
        """Retain an unreceived bundle and release only its exact reservations."""
        from reconforge.domain.inventory_receipt_posting import exact_text
        reason, command_id = exact_text(reason, maximum=500), exact_text(command_id, maximum=140)
        request = {"plan_id": identifier, "expected_plan_digest": expected_plan_digest, "reason": reason}
        envelope = {"operation": "cancel", "actor_id": actor.user_id, "request": request}
        digest = digest_payload(envelope)
        with self.connection.transaction():
            self.purchase._scope_transaction()
            plan = self._row(identifier)
            parent = self.purchase._order(plan["order_id"], lock=True)
            self._authorize(parent, actor, "review", plan["amount_minor"])
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (canonical_json([self.tenant_id, plan["workspace_id"], "landed-cost", command_id]),))
            if self.connection.execute("SELECT 1 FROM reconforge.landed_cost_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                (self.tenant_id, plan["workspace_id"], command_id)).fetchone() is not None:
                raise ProcurementPartialError("landed_cost_command_conflict", "Command belongs to a retained receiving operation.")
            retained = self._cancellation(command_id=command_id, workspace_id=plan["workspace_id"])
            if retained is not None:
                if (retained["plan_id"], retained["actor_id"], retained["request_digest"]) != (identifier, actor.user_id, digest):
                    raise ProcurementPartialError("landed_cost_command_conflict", "Cancellation command belongs to another exact source, request or human.")
                self.connection.execute("SELECT reconforge.landed_cost_close(%s,%s)", (self.tenant_id, identifier))
                return dict(retained["response_json"])
            if plan["phase"] not in (0, 1) or plan["plan_digest"] != expected_plan_digest or self._cancellation(plan_id=identifier) is not None:
                raise ProcurementPartialError("landed_cost_phase_conflict", "Only the current uncancelled unreceived bundle can be cancelled.")
            view = self._view(identifier)
            if actor.user_id in (view["preparer_actor_id"], view["reviewer_actor_id"]):
                raise ProcurementPartialError("landed_cost_duties_conflict", "Cancellation requires a human independent of the preparer and any reviewer.")
            audit, outbox = self._event(plan, "landed_cost_cancelled", actor)
            cancellation = {"actor_id": actor.user_id, "reason": reason, "command_id": command_id,
                            "audit_event_id": audit, "outbox_event_id": outbox}
            response = {**view, "status": "Cancelled", "cancellation": cancellation}
            self.connection.execute("""INSERT INTO reconforge.landed_cost_cancellations(tenant_id,plan_id,workspace_id,source_phase,
                actor_id,reason,command_id,request_digest,request_json,response_json,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, plan["workspace_id"], plan["phase"], actor.user_id, reason, command_id, digest,
                 canonical_json(envelope), canonical_json(response), audit, outbox))
            return response
