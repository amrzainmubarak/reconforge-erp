"""Three-scope native intercompany owners on one caller-owned transaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_balances import business_date
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.intercompany_operations import (
    MAX_SETTLEMENTS,
    IntercompanyPreparation,
    Kind,
    consolidate_reports,
    equation,
    fail,
)
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository

BOOKS = ("seller", "buyer", "adjustment")
SUFFIXES = {"seller": "A", "buyer": "B", "adjustment": "G"}
PERMISSIONS = {"prepare": "finance_core.manage", "review": "finance_core.validate", "post": "finance_core.post", "read": "finance_core.read"}


class _IntercompanyPostingParticipant:
    """Private admission binds the live owner, connection and exact entry."""

    def __init__(self, owner: PostgresIntercompanyOperationsRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresIntercompanyOperationsRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _IntercompanyPostingParticipant | None = None

    def _peek(self, kind: str, identifier: str) -> dict[str, Any]:
        statement = {
            "source": "SELECT payload FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s AND id=%s",
            "plan": "SELECT payload FROM reconforge.intercompany_operation_plans WHERE tenant_id=%s AND id=%s",
        }[kind]
        rows = records(self.connection.execute(statement, (self.tenant_id, text(identifier, kind + "_id"))))
        if not rows:
            fail("Intercompany source is absent or outside the complete authorized group scope.", "intercompany_not_found")
        return dict(rows[0]["payload"])

    def _authorize(self, actor: PostingActor, operation: str, source: Mapping[str, Any],
                   plan: Mapping[str, Any] | None = None) -> None:
        request = source.get("request", source)
        precision = source.get("monetary_policy", {}).get("currency_precision")
        amount = max(request["amount_minor"], plan["amount_minor"] if plan else 0)
        for book in BOOKS:
            scope = {"workspace_id": request["workspace_id"], "organization_id": request["organization_id"],
                     "legal_entity_id": request[book + "_entity_id"]}
            if precision is not None:
                scope.update(amount_minor=amount, currency_precision=precision)
            for permission in ("intercompany_operations." + operation, PERMISSIONS[operation]):
                self.owner._actor(actor, permission, scope, mutation=operation != "read")

    def _parents(self, request: Mapping[str, Any], period_id: str) -> None:
        if self.connection.execute("SELECT id FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                                   (self.tenant_id, period_id, request["workspace_id"])).fetchone() is None:
            fail("The scoped fiscal period is absent.", "intercompany_scope_denied")
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(request["workspace_id"])
        ids = sorted(request[book + "_entity_id"] for book in BOOKS)
        rows = records(self.connection.execute("""SELECT e.id,e.entity_code,e.currency_code,e.active,o.organization_code,o.active AS organization_active
            FROM reconforge.legal_entities e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id
            WHERE e.tenant_id=%s AND e.organization_id=%s AND o.application_workspace_id=%s AND e.id=ANY(%s)
            ORDER BY e.id FOR SHARE OF e,o""", (self.tenant_id, request["organization_id"], request["workspace_id"], ids)))
        by_id = {row["id"]: row for row in rows}
        if (len(by_id) != 3 or len({row["currency_code"] for row in rows}) != 1
                or any(not row["active"] or not row["organization_active"] or row["organization_code"] != request["organization_code"] for row in rows)
                or any(by_id[request[book + "_entity_id"]]["entity_code"] != request[book + "_entity_code"] for book in BOOKS)):
            fail("Three current active entity scopes with one functional currency are required.", "intercompany_scope_denied")

    def _source(self, identifier: str) -> dict[str, Any]:
        rows = records(self.connection.execute("SELECT payload FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                               (self.tenant_id, identifier)))
        if not rows:
            fail("The original paired source is absent or unauthorized.", "intercompany_not_found")
        return dict(rows[0]["payload"])

    def _plan(self, identifier: str) -> dict[str, Any]:
        initial = self._peek("plan", identifier)
        self._source(initial["source_id"])
        row = records(self.connection.execute("SELECT payload,phase FROM reconforge.intercompany_operation_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                              (self.tenant_id, identifier)))[0]
        return {**row["payload"], "phase": row["phase"]}

    def _state(self, source: Mapping[str, Any]) -> dict[str, Any]:
        rows = records(self.connection.execute("SELECT payload FROM reconforge.intercompany_operation_plans WHERE tenant_id=%s AND source_id=%s AND phase=2 ORDER BY sequence",
                                               (self.tenant_id, source["id"])))
        plans = [row["payload"] for row in rows]
        paid = sum(plan["equation"]["settlement_minor"] for plan in plans if plan["kind"] == "settle")
        return {"recognized": bool(plans), "sequence": len(plans), "settled_minor": paid,
                "closed": bool(plans and plans[-1]["kind"] == "eliminate"),
                "last_posting_date": plans[-1]["posting_date"] if plans else source["request"]["posting_date"]}

    def _command(self, workspace: str, operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(envelope)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, workspace, "intercompany-operations", command_id]),))
        rows = records(self.connection.execute("SELECT * FROM reconforge.intercompany_operation_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                               (self.tenant_id, workspace, command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            fail("Command key already binds a different actor or immutable request.", "intercompany_command_conflict")
        return digest, row["response_json"]

    def _scope(self, source: Mapping[str, Any]) -> dict[str, Any]:
        req = source["request"]
        return {key: req[key] for key in ("workspace_id", "organization_id", "seller_entity_id", "buyer_entity_id", "adjustment_entity_id")}

    def _event(self, source: Mapping[str, Any], plan_id: str, action: str, actor: PostingActor,
               metadata: dict[str, Any]) -> tuple[str, str]:
        return self.owner._event({"id": plan_id, "workspace_id": source["request"]["workspace_id"],
            "organization_id": source["request"]["organization_id"], "legal_entity_id": source["request"]["adjustment_entity_id"]}, action, actor, metadata)

    def _view(self, identifier: str) -> dict[str, Any]:
        plan = self._plan(identifier)
        review = records(self.connection.execute("SELECT reviewer_actor_id FROM reconforge.intercompany_operation_reviews WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, identifier)))
        links = records(self.connection.execute("SELECT book,posting_effect_id,posted_actor_id FROM reconforge.intercompany_operation_links WHERE tenant_id=%s AND plan_id=%s ORDER BY book", (self.tenant_id, identifier)))
        return {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
                "posted_actor_id": links[0]["posted_actor_id"] if links else None,
                "posting_effect_ids": {link["book"]: link["posting_effect_id"] for link in links}}

    def _remember(self, source: Mapping[str, Any], plan: Mapping[str, Any], operation: str, command_id: str,
                  actor: PostingActor, digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(plan["id"])
        scope = self._scope(source)
        self.connection.execute("""INSERT INTO reconforge.intercompany_operation_commands
            (tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, *scope.values(), plan["id"], operation, command_id, actor.user_id, digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, plan["id"]))
        return result

    def _prepare(self, source: Mapping[str, Any], kind: Kind, *, amount_minor: int, period_id: str, posting_date: str,
                 reason: str, command_id: str, digest: str, request: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        state = self._state(source)
        if (state["closed"] or state["sequence"] > MAX_SETTLEMENTS + 1
                or (kind == "settle" and state["sequence"] > MAX_SETTLEMENTS)
                or posting_date < state["last_posting_date"]):
            fail("Use the open original source, monotonic business date and bounded settlement history.", "intercompany_state_conflict")
        if kind != "recognize" and not state["recognized"]:
            fail("Post both original recognition entries before progressing.", "intercompany_state_conflict")
        if self.connection.execute("SELECT 1 FROM reconforge.intercompany_operation_plans WHERE tenant_id=%s AND source_id=%s AND phase<2", (self.tenant_id, source["id"])).fetchone():
            fail("Complete the pending paired operation before preparing another.", "intercompany_state_conflict")
        eq = equation(source["request"], kind, settled_before_minor=state["settled_minor"], settlement_minor=amount_minor)
        self._authorize(actor, "prepare", source, {"amount_minor": eq["amount_minor"]})
        identifier, entries = "IC1-" + uuid4().hex, []
        req, precision = source["request"], source["monetary_policy"]["currency_precision"]
        for book, lines in sorted(eq["books"].items()):
            entry = self.owner.finance.create_entry(entry_number=identifier.upper() + "-" + SUFFIXES[book], organization_code=req["organization_code"],
                entity_code=req[book + "_entity_code"], period_id=period_id, journal_code=req["journal_code"], posting_date=posting_date,
                description=reason, workspace=req["workspace_id"], external_reference="IC:" + source["id"] + ":" + kind,
                actor_label=actor.username, lines=[{"account_code": row["account_code"], "debit": exact_minor_text(row["debit_minor"], precision),
                    "credit": exact_minor_text(row["credit_minor"], precision), "description": reason} for row in lines])
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if any(snapshot["entry"][key] != value for key, value in source["monetary_policy"].items()):
                fail("Every native entry must retain the original monetary policy.", "intercompany_policy_mismatch")
            entries.append({"book": book, "entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot)})
        plan = {"schema_version": "intercompany-native-plan-v1", "id": identifier, "source_id": source["id"], **self._scope(source),
                "kind": kind, "sequence": state["sequence"], "period_id": period_id, "posting_date": posting_date, "reason": reason,
                "currency_code": source["monetary_policy"]["currency_code"], "currency_precision": precision,
                "source_digest": source["source_digest"], "amount_minor": eq["amount_minor"], "equation": eq,
                "entries": entries, "preparer_actor_id": actor.user_id, "command_request": dict(request)}
        plan["plan_digest"] = digest_payload(plan)
        audit, outbox = self._event(source, identifier, "intercompany_operation_prepared", actor, {"plan_digest": plan["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.intercompany_operation_plans
            (tenant_id,id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,source_id,sequence,kind,phase,payload,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""",
            (self.tenant_id, identifier, *self._scope(source).values(), source["id"], state["sequence"], kind, canonical_json(plan), audit, outbox))
        return self._remember(source, plan, "prepare", command_id, actor, digest, request)

    def prepare(self, request: IntercompanyPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        req = request.payload()
        envelope = {"kind": "recognize", **req}
        with self.owner._transaction():
            self._authorize(actor, "prepare", req)
            digest, replay = self._command(req["workspace_id"], "prepare", command_id, actor, envelope)
            self._parents(req, req["period_id"])
            if replay is not None:
                source = self._source(replay["source_id"])
                self._authorize(actor, "prepare", source, replay)
                self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            currency = records(self.connection.execute("""SELECT c.code,c.minor_units FROM reconforge.currencies c
                JOIN reconforge.legal_entities e ON e.tenant_id=c.tenant_id AND e.currency_code=c.code
                WHERE e.tenant_id=%s AND e.id=%s AND c.active FOR SHARE OF c""", (self.tenant_id, req["seller_entity_id"])))[0]
            policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(workspace_id=req["workspace_id"],
                currency_code=currency["code"], minor_units=currency["minor_units"], actor_label=actor.username)
            source = {"schema_version": "intercompany-native-source-v1", "id": "IC-" + uuid4().hex,
                      "request": req, "monetary_policy": {"currency_code": policy.currency_code, **policy.metadata()}, "preparer_actor_id": actor.user_id}
            self._authorize(actor, "prepare", source)
            source["source_digest"] = digest_payload(source)
            self.connection.execute("""INSERT INTO reconforge.intercompany_operation_sources
                (tenant_id,id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,reference,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (self.tenant_id, source["id"], *self._scope(source).values(), req["reference"], canonical_json(source)))
            return self._prepare(source, "recognize", amount_minor=0, period_id=req["period_id"], posting_date=req["posting_date"],
                reason=req["reason"], command_id=command_id, digest=digest, request=envelope, actor=actor)

    def _progress(self, kind: Kind, source_id: str, *, amount_minor: int, period_id: str, posting_date: str,
                  reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request: dict[str, Any] = {"kind": kind, "source_id": text(source_id, "source_id"), "amount_minor": amount_minor,
                   "period_id": text(period_id, "period_id"), "posting_date": business_date(posting_date), "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "prepare", source)
            digest, replay = self._command(source["request"]["workspace_id"], "prepare", command_id, actor, request)
            self._parents(source["request"], period_id)
            source = self._source(source_id)
            if replay is not None:
                self._authorize(actor, "prepare", source, replay)
                self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            return self._prepare(source, kind, amount_minor=amount_minor, period_id=period_id, posting_date=request["posting_date"],
                reason=request["reason"], command_id=command_id, digest=digest, request=request, actor=actor)

    def prepare_settlement(self, source_id: str, *, amount_minor: int, period_id: str, posting_date: str,
                           reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress("settle", source_id, amount_minor=amount_minor, period_id=period_id, posting_date=posting_date,
                              reason=reason, command_id=command_id, actor=actor)

    def prepare_elimination(self, source_id: str, *, period_id: str, posting_date: str, reason: str,
                            command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress("eliminate", source_id, amount_minor=0, period_id=period_id, posting_date=posting_date,
                              reason=reason, command_id=command_id, actor=actor)

    def _phase(self, operation: str, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": text(plan_id, "plan_id"), "expected_plan_digest": expected_plan_digest, "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            initial = self._peek("plan", plan_id)
            source = self._peek("source", initial["source_id"])
            self._authorize(actor, operation, source, initial)
            digest, replay = self._command(source["request"]["workspace_id"], operation, command_id, actor, request)
            self._parents(source["request"], initial["period_id"])
            plan = self._plan(plan_id)
            source = self._source(plan["source_id"])
            self._authorize(actor, operation, source, plan)
            if replay is not None:
                self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, plan_id))
                return replay
            state = self._state(source)
            if (plan["plan_digest"] != expected_plan_digest or plan["phase"] != (0 if operation == "review" else 1)
                    or state["closed"] or plan["sequence"] != state["sequence"]):
                fail("Use the retained current digest and complete expected phase.", "intercompany_state_conflict")
            if actor.user_id == plan["preparer_actor_id"]:
                fail("An independent reviewer and third posting human are required.", "intercompany_actor_denied")
            entries = sorted(plan["entries"], key=lambda row: row["entry_id"])
            if operation == "review":
                for entry in entries:
                    self.owner.finance.validate_entry(entry["entry_id"], reason=request["reason"], actor_label=actor.username)
                audit, outbox = self._event(source, plan_id, "intercompany_operation_reviewed", actor, {"plan_digest": plan["plan_digest"]})
                self.connection.execute("""INSERT INTO reconforge.intercompany_operation_reviews
                    (tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, plan_id, actor.user_id, request["reason"], audit, outbox))
            else:
                if actor.user_id == self._view(plan_id)["reviewer_actor_id"]:
                    fail("Posting requires a third distinct human.", "intercompany_actor_denied")
                for entry in entries:
                    self._participant = _IntercompanyPostingParticipant(self, entry["entry_id"])
                    try:
                        effect = self.owner.posting.post(entry["entry_id"], command_id="IC1:" + entry["book"] + ":" + command_id,
                            expected_validation_digest=entry["validation_digest"], reason=request["reason"], actor=actor, _source_owner=self._participant)
                    finally:
                        self._participant = None
                    self.connection.execute("""INSERT INTO reconforge.intercompany_operation_links
                        (tenant_id,plan_id,book,entry_id,posting_effect_id,posted_actor_id,reason) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                        (self.tenant_id, plan_id, entry["book"], entry["entry_id"], effect["id"], actor.user_id, request["reason"]))
                audit, outbox = self._event(source, plan_id, "intercompany_operation_posted", actor, {"plan_digest": plan["plan_digest"]})
                self.connection.execute("INSERT INTO reconforge.intercompany_operation_post_evidence(tenant_id,plan_id,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s)",
                                        (self.tenant_id, plan_id, audit, outbox))
            self.connection.execute("UPDATE reconforge.intercompany_operation_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
            return self._remember(source, plan, operation, command_id, actor, digest, request)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("review", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("post", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            initial = self._peek("plan", plan_id)
            source = self._peek("source", initial["source_id"])
            self._authorize(actor, "read", source, initial)
            self._parents(source["request"], initial["period_id"])
            source = self._source(source["id"])
            plan = self._view(plan_id)
            self._authorize(actor, "read", source, plan)
            self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, plan_id))
            return plan

    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "read", source)
            self._parents(source["request"], source["request"]["period_id"])
            source = self._source(source_id)
            rows = records(self.connection.execute("SELECT id FROM reconforge.intercompany_operation_plans WHERE tenant_id=%s AND source_id=%s ORDER BY sequence", (self.tenant_id, source_id)))
            plans = []
            for row in rows:
                plan = self._view(row["id"])
                self._authorize(actor, "read", source, plan)
                self.connection.execute("SELECT reconforge.ic_operation_close(%s,%s)", (self.tenant_id, plan["id"]))
                plans.append(plan)
            state = self._state(source)
            return {**source, **state, "outstanding_minor": source["request"]["amount_minor"] - state["settled_minor"], "plans": plans}

    def list_sources(self, *, workspace_id: str, organization_id: str, actor: PostingActor, after: str = "") -> list[dict[str, Any]]:
        with self.owner._transaction():
            rows = records(self.connection.execute("SELECT id FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND id>%s ORDER BY id LIMIT 25",
                                                   (self.tenant_id, workspace_id, organization_id, after)))
            return [self.get_source(row["id"], actor=actor) for row in rows]

    def evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self.get_plan(plan_id, actor=actor)
            source = self._source(plan["source_id"])
            originals = {key: value for key, value in plan.items() if key not in ("phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest")}
            effects = [self.owner.posting.get_effect(plan["posting_effect_ids"][entry["book"]], actor=actor)
                       for entry in plan["entries"]] if plan["phase"] == 2 else []
            phases = records(self.connection.execute("""SELECT a.action,a.actor_user_id AS actor_id,a.id AS audit_event_id,
                a.metadata_json,o.event_id AS outbox_event_id FROM reconforge.domain_audit_events a
                JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id AND o.aggregate_type=a.object_type
                 AND o.aggregate_id=a.object_id AND o.event_type=a.action AND o.payload->>'audit_event_id'=a.id
                WHERE a.tenant_id=%s AND a.object_type='operational_finance' AND a.object_id=%s ORDER BY a.sequence""", (self.tenant_id, plan_id)))
            return {"schema_version": "intercompany-native-evidence-v1", "source": source, "plan": plan,
                    "canonical_source_json": canonical_json({key: value for key, value in source.items() if key != "source_digest"}),
                    "canonical_plan_json": canonical_json(originals), "canonical_snapshot_jsons": [canonical_json(row["snapshot"]) for row in plan["entries"]],
                    "native_effects": effects, "phases": phases}

    def report(self, source_id: str, *, seller_map_id: str, buyer_map_id: str, adjustment_map_id: str,
               period_id: str, as_of_date: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self.get_source(source_id, actor=actor)
            if not source["closed"]:
                fail("Consolidated reporting requires its posted reviewed native group adjustment.", "intercompany_state_conflict")
            req = source["request"]
            self._parents(req, period_id)
            reports = []
            for book, map_id in zip(BOOKS, (seller_map_id, buyer_map_id, adjustment_map_id), strict=True):
                report = PostgresFinancialReportingRepository(self.connection, self.tenant_id).report(map_id=map_id,
                    period_id=period_id, as_of_date=as_of_date, organization_code=req["organization_code"], entity_code=req[book + "_entity_code"], actor=actor)
                if report["legal_entity_id"] != req[book + "_entity_id"] or report["currency_policy"] != source["monetary_policy"]:
                    fail("Each report must retain its explicit original entity and currency policy.", "intercompany_policy_mismatch")
                burden = max(report["trial_balance"]["totals"]["closing"]["turnover_totals"]["debit_minor"], req["amount_minor"])
                for permission in ("intercompany_operations.read", "finance_core.read"):
                    self.owner._actor(actor, permission, {"workspace_id": req["workspace_id"], "organization_id": req["organization_id"],
                        "legal_entity_id": req[book + "_entity_id"], "amount_minor": burden, "currency_precision": source["monetary_policy"]["currency_precision"]}, mutation=False)
                reports.append(report)
            closing = source["plans"][-1]
            included = {p["effect_id"] for report in reports for row in report["trial_balance"]["accounts"] for p in row["postings"]}
            required = {effect for plan in source["plans"] for effect in plan["posting_effect_ids"].values()}
            if not required <= included:
                fail("Reporting cutoff must include every original paired and group adjustment effect.", "intercompany_evidence_invalid")
            return consolidate_reports(reports, source_digest=source["source_digest"], adjustment_plan_digest=closing["plan_digest"])
