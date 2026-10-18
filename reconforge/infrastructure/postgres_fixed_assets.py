"""Source-owned acquisition, depreciation and disposal on the native GL."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.fixed_assets import (
    AssetAcquisition,
    accounting_lines,
    cumulative_depreciation,
    eligible_months,
    exact_minor,
)
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository


class _AssetPostingParticipant:
    def __init__(self, owner: "PostgresFixedAssetsRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresFixedAssetsRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _AssetPostingParticipant | None = None

    def _asset(self, identifier: str) -> dict[str, Any]:
        rows = records(self.connection.execute(
            "SELECT payload FROM reconforge.fixed_assets WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, text(identifier, "asset_id"))))
        if not rows:
            raise FinancePostingError("asset_not_found", "Asset is absent or outside current scope.")
        return dict(rows[0]["payload"])

    def _plan(self, identifier: str) -> dict[str, Any]:
        # Detail reads already hold the asset before visiting its plans. Resolve
        # the immutable RLS-scoped owner first so evidence/review/post use that
        # same lock order instead of deadlocking an automatic detail refresh.
        identifier = text(identifier, "plan_id")
        owners = records(self.connection.execute(
            "SELECT asset_id FROM reconforge.fixed_asset_plans WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, identifier)))
        if not owners:
            raise FinancePostingError("asset_not_found", "Asset plan is absent or outside current scope.")
        self._asset(str(owners[0]["asset_id"]))
        rows = records(self.connection.execute(
            "SELECT payload,phase FROM reconforge.fixed_asset_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, identifier)))
        if not rows:
            raise FinancePostingError("asset_not_found", "Asset plan is absent or outside current scope.")
        return {**rows[0]["payload"], "phase": rows[0]["phase"]}

    def _authorize_plan(self, actor: PostingActor, permission: str, plan: Mapping[str, Any], *, mutation: bool = True) -> None:
        # Fully depreciated disposals have zero carrying value and positive native
        # turnover. ABAC evaluates the complete retained debit, not that zero basis.
        turnover = sum(row["debit_minor"] for row in plan["snapshot"]["lines"])
        self.owner._actor(actor, permission, {**plan, "amount_minor": turnover}, mutation=mutation)

    def _state(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        rows = records(self.connection.execute(
            """SELECT sequence,kind,payload FROM reconforge.fixed_asset_plans
            WHERE tenant_id=%s AND asset_id=%s AND phase=2 ORDER BY sequence""", (self.tenant_id, asset["id"])))
        return {"acquired": bool(rows), "disposed": bool(rows and rows[-1]["kind"] == "dispose"),
                "accumulated_minor": sum(row["payload"]["amount_minor"] for row in rows if row["kind"] == "depreciate"),
                "months": max((row["payload"]["months_after"] for row in rows), default=0),
                "sequence": len(rows), "last_posting_date": rows[-1]["payload"]["posting_date"] if rows else asset["posting_date"]}

    def _command(self, scope: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(envelope)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, scope["workspace_id"], "fixed-assets", command_id]),))
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.fixed_asset_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            raise FinancePostingError("asset_command_conflict", "Command identifies another actor or request.")
        self.connection.execute("SELECT reconforge.asset_close(%s,%s)", (self.tenant_id, row["plan_id"]))
        return digest, row["response_json"]

    def _view_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self._plan(plan_id)
        review = records(self.connection.execute(
            "SELECT * FROM reconforge.fixed_asset_reviews WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        link = records(self.connection.execute(
            "SELECT * FROM reconforge.fixed_asset_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        return {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
                "posting_effect_id": link[0]["posting_effect_id"] if link else None}

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view_plan(str(plan["id"]))
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self.connection.execute("""INSERT INTO reconforge.fixed_asset_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["id"],
             operation, command, actor.user_id, digest, canonical_json(envelope), canonical_json(result)))
        return result

    def _prepare(self, asset: Mapping[str, Any], request: Mapping[str, Any], state: Mapping[str, Any],
                 actor: PostingActor, digest: str, command: str,
                 command_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self.connection.execute("SELECT 1 FROM reconforge.fixed_asset_plans WHERE tenant_id=%s AND asset_id=%s AND phase<2",
                                   (self.tenant_id, asset["id"])).fetchone() is not None:
            raise FinancePostingError("asset_state_conflict", "Complete the pending reviewed asset operation first.")
        kind = str(request["kind"])
        if kind != "acquire" and (not state["acquired"] or state["disposed"]):
            raise FinancePostingError("asset_state_invalid", "An acquired, undisposed asset is required.")
        if request["posting_date"] < state["last_posting_date"]:
            raise FinancePostingError("asset_date_invalid", "Asset accounting dates cannot regress.")
        accumulated, months, amount = state["accumulated_minor"], state["months"], asset["cost_minor"]
        if kind == "depreciate":
            months = eligible_months(str(asset["in_service_date"]), str(request["through_month"]), str(request["posting_date"]), int(asset["useful_life_months"]))
            amount = cumulative_depreciation(int(asset["cost_minor"]), int(asset["salvage_minor"]), int(asset["useful_life_months"]), months) - accumulated
            if months <= state["months"] or amount <= 0:
                raise FinancePostingError("asset_state_invalid", "No new positive cumulative depreciation is due.")
        elif kind == "dispose":
            exact_minor(request["proceeds_minor"], "proceeds", zero=True)
            amount = asset["cost_minor"] - accumulated
        identifier = "FA1-" + uuid4().hex
        lines = accounting_lines(dict(asset), kind, accumulated=accumulated,
                                 depreciation=amount if kind == "depreciate" else 0, proceeds=int(request["proceeds_minor"]))
        self.owner._actor(actor, "finance_core.manage", {
            **asset, "amount_minor": sum(row["debit_minor"] for row in lines),
        })
        entry = self.owner.finance.create_entry(entry_number=identifier.upper(), organization_code=str(asset["organization_code"]),
            entity_code=str(asset["entity_code"]), period_id=str(request["period_id"]), journal_code=str(asset["journal_code"]),
            posting_date=str(request["posting_date"]), description=str(request["reason"]), workspace=str(asset["workspace_id"]),
            external_reference="FA:" + str(asset["id"]) + ":" + kind, actor_label=actor.username,
            lines=[{"account_code": row["account_code"], "debit": exact_minor_text(int(row["debit_minor"]), int(asset["currency_precision"])) if row["debit_minor"] else "0",
                    "credit": exact_minor_text(int(row["credit_minor"]), int(asset["currency_precision"])) if row["credit_minor"] else "0",
                    "description": request["reason"]} for row in lines])
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
        if snapshot["entry"]["currency_code"] != asset["currency_code"]:
            raise FinancePostingError("asset_currency_invalid", "Asset and native GL require the same functional currency.")
        payload = {"schema_version": "fixed-asset-plan-v1", "id": identifier, "asset_id": asset["id"],
                   **{key: asset[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code", "currency_code", "currency_precision")},
                   **dict(request), "sequence": state["sequence"], "asset_digest": asset["asset_digest"], "entry_id": entry["id"],
                   "amount_minor": amount, "accumulated_before_minor": accumulated, "months_before": state["months"],
                   "months_after": months, "snapshot": snapshot, "preparer_actor_id": actor.user_id}
        payload["command_request"] = dict(command_request or request)
        payload.update(plan_digest=digest_payload(payload), validation_digest=validation_digest(snapshot))
        audit, outbox = self.owner._event(payload, "fixed_asset_prepared", actor, {"plan_digest": payload["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.fixed_asset_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,asset_id,entry_id,sequence,kind,phase,payload,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""",
            (self.tenant_id, identifier, asset["workspace_id"], asset["organization_id"], asset["legal_entity_id"], asset["id"], entry["id"],
             state["sequence"], kind, canonical_json(payload), audit, outbox))
        return self._remember(payload, "prepare", command, actor, digest, command_request or request)

    def acquire(self, request: AssetAcquisition, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            scope = records(self.connection.execute(
                """SELECT c.code AS currency_code,c.minor_units AS currency_precision FROM reconforge.legal_entities e
                JOIN reconforge.currencies c ON c.tenant_id=e.tenant_id AND c.code=e.currency_code AND c.active
                WHERE e.tenant_id=%s AND e.id=%s AND e.organization_id=%s FOR SHARE OF e,c""",
                (self.tenant_id, request.legal_entity_id, request.organization_id)))
            if not scope:
                raise FinancePostingError("asset_scope_denied", "Current functional currency and asset hierarchy are required.")
            self.owner._actor(actor, "finance_core.manage", {**args, **scope[0], "amount_minor": request.cost_minor})
            digest, replay = self._command(args, "prepare", command_id, actor, {"kind": "acquire", **args})
            if replay is not None:
                self._authorize_plan(actor, "finance_core.manage", replay)
                return replay
            asset = {"schema_version": "fixed-asset-v1", "id": "FA-" + uuid4().hex, **args, **scope[0], "preparer_actor_id": actor.user_id}
            asset["asset_digest"] = digest_payload(asset)
            self.owner._actor(actor, "finance_core.manage", {**asset, "amount_minor": asset["cost_minor"]})
            self.connection.execute("""INSERT INTO reconforge.fixed_assets
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,asset_number,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (self.tenant_id, asset["id"], request.workspace_id, request.organization_id, request.legal_entity_id,
                 request.asset_number, canonical_json(asset)))
            operation = {"kind": "acquire", "period_id": request.period_id, "posting_date": request.posting_date,
                         "through_month": "", "proceeds_minor": 0, "reason": request.reason}
            return self._prepare(asset, operation, {"acquired": False, "disposed": False, "accumulated_minor": 0,
                                                    "months": 0, "sequence": 0, "last_posting_date": request.posting_date},
                                 actor, digest, command_id, {"kind": "acquire", **args})

    def prepare(self, asset_id: str, *, kind: str, period_id: str, posting_date: str, reason: str,
                command_id: str, actor: PostingActor, through_month: str = "", proceeds_minor: int = 0) -> dict[str, Any]:
        if kind not in {"depreciate", "dispose"}:
            raise FinancePostingError("asset_request_invalid", "Use depreciation or disposal for an existing asset.")
        from datetime import date
        try:
            date.fromisoformat(posting_date)
        except ValueError as exc:
            raise FinancePostingError("asset_date_invalid", "A valid posting date is required.") from exc
        request = {"asset_id": text(asset_id, "asset_id"), "kind": kind, "period_id": text(period_id, "period_id"),
                   "posting_date": posting_date, "reason": text(reason, "reason", maximum=500), "through_month": through_month,
                   "proceeds_minor": exact_minor(proceeds_minor, "proceeds", zero=True)}
        if (kind == "depreciate" and proceeds_minor != 0) or (kind == "dispose" and through_month != ""):
            raise FinancePostingError("asset_request_invalid", "Only operation-specific values may be supplied.")
        with self.owner._transaction():
            asset = self._asset(asset_id)
            digest, replay = self._command(asset, "prepare", command_id, actor, request)
            if replay is not None:
                self._authorize_plan(actor, "finance_core.manage", replay)
                return replay
            return self._prepare(asset, request, self._state(asset), actor, digest, command_id)

    def _current(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        asset = self._asset(str(plan["asset_id"]))
        state = self._state(asset)
        if (state["sequence"], state["accumulated_minor"], state["months"]) != (
            plan["sequence"], plan["accumulated_before_minor"], plan["months_before"]):
            raise FinancePostingError("asset_state_conflict", "Asset basis changed after preparation.")
        return asset

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            plan = self._plan(plan_id)
            self._authorize_plan(actor, "finance_core.validate", plan)
            digest, replay = self._command(plan, "review", command_id, actor, request)
            if replay is not None:
                return replay
            if plan["phase"] != 0 or plan["plan_digest"] != expected_plan_digest or actor.user_id == plan["preparer_actor_id"]:
                raise FinancePostingError("asset_review_invalid", "An independent reviewer and current prepared digest are required.")
            self._current(plan)
            self.owner.finance.validate_entry(plan["entry_id"], reason=request["reason"], actor_label=actor.username)
            audit, outbox = self.owner._event(plan, "fixed_asset_reviewed", actor, {"plan_digest": plan["plan_digest"]})
            self.connection.execute("""INSERT INTO reconforge.fixed_asset_reviews
                (tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, actor.user_id, request["reason"], audit, outbox))
            self.connection.execute("UPDATE reconforge.fixed_asset_plans SET phase=1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
            return self._remember(plan, "review", command_id, actor, digest, request)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            plan = self._plan(plan_id)
            self._authorize_plan(actor, "finance_core.post", plan)
            digest, replay = self._command(plan, "post", command_id, actor, request)
            if replay is not None:
                return replay
            if plan["phase"] != 1 or plan["plan_digest"] != expected_plan_digest:
                raise FinancePostingError("asset_review_invalid", "A current reviewed asset operation is required.")
            if actor.user_id in {plan["preparer_actor_id"], self._view_plan(plan_id)["reviewer_actor_id"]}:
                raise FinancePostingError("asset_posting_denied", "Posting requires a third independently authorized human.")
            self._current(plan)
            self._participant = _AssetPostingParticipant(self, str(plan["entry_id"]))
            try:
                effect = self.owner.posting.post(plan["entry_id"], command_id="FA1:" + command_id,
                    expected_validation_digest=plan["validation_digest"], reason=request["reason"], actor=actor, _source_owner=self._participant)
            finally:
                self._participant = None
            audit, outbox = self.owner._event(plan, "fixed_asset_posted", actor,
                {"plan_digest": plan["plan_digest"], "posting_effect_id": effect["id"]})
            self.connection.execute("""INSERT INTO reconforge.fixed_asset_links
                (tenant_id,plan_id,posting_effect_id,posted_actor_id,reason,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, effect["id"], actor.user_id, request["reason"], audit, outbox))
            self.connection.execute("UPDATE reconforge.fixed_asset_plans SET phase=2 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
            return self._remember(plan, "post", command_id, actor, digest, request)

    def get(self, asset_id: str, *, actor: PostingActor, before_sequence: int | None = None) -> dict[str, Any]:
        with self.owner._transaction():
            asset = self._asset(asset_id)
            self.owner._actor(actor, "finance_core.read", {**asset, "amount_minor": asset["cost_minor"]}, mutation=False)
            state = self._state(asset)
            ids = records(self.connection.execute("""SELECT id,sequence FROM reconforge.fixed_asset_plans
                WHERE tenant_id=%s AND asset_id=%s AND (%s::integer IS NULL OR sequence<%s)
                ORDER BY sequence DESC LIMIT 25""", (self.tenant_id, asset_id, before_sequence, before_sequence)))
            plans = [self._view_plan(row["id"]) for row in reversed(ids)]
            for plan in plans:
                self._authorize_plan(actor, "finance_core.read", plan, mutation=False)
            for row in ids:
                self.connection.execute("SELECT reconforge.asset_close(%s,%s)", (self.tenant_id, row["id"]))
            return {**asset, **state, "status": "Disposed" if state["disposed"] else "Active" if state["acquired"] else "PendingAcquisition",
                    "carrying_minor": 0 if state["disposed"] else asset["cost_minor"] - state["accumulated_minor"] if state["acquired"] else 0,
                    "plans": plans,
                    "history_before": ids[-1]["sequence"] if ids and ids[-1]["sequence"] > 0 else None}

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._plan(plan_id)
            self._authorize_plan(actor, "finance_core.read", plan, mutation=False)
            self.connection.execute("SELECT reconforge.asset_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view_plan(plan_id)

    def plan_evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        """Verify source, review and native effect before exposing bounded proof.

        This is a projection of retained evidence, not a new financial effect.
        Canonical JSON retains exact integer lexemes for independent browser or
        offline SHA-256 verification even above JavaScript's safe integer range.
        """
        with self.owner._transaction():
            plan = self._plan(plan_id)
            self._authorize_plan(actor, "finance_core.read", plan, mutation=False)
            self.connection.execute("SELECT reconforge.asset_close(%s,%s)", (self.tenant_id, plan_id))
            asset = self._asset(str(plan["asset_id"]))
            self.owner._actor(actor, "finance_core.read", {**asset, "amount_minor": asset["cost_minor"]}, mutation=False)
            view = self._view_plan(plan_id)
            phases = [{"action": "fixed_asset_prepared", "actor_id": plan["preparer_actor_id"], **row}
                      for row in records(self.connection.execute(
                          "SELECT audit_event_id,outbox_event_id FROM reconforge.fixed_asset_plans WHERE tenant_id=%s AND id=%s",
                          (self.tenant_id, plan_id)))]
            if plan["phase"] >= 1:
                phases.extend({"action": "fixed_asset_reviewed", **row} for row in records(self.connection.execute(
                    "SELECT reviewer_actor_id AS actor_id,audit_event_id,outbox_event_id FROM reconforge.fixed_asset_reviews WHERE tenant_id=%s AND plan_id=%s",
                    (self.tenant_id, plan_id))))
            native = None
            if plan["phase"] == 2:
                effect = self.owner.posting.get_effect(view["posting_effect_id"], actor=actor)
                if (effect["entry_id"] != plan["entry_id"] or effect["snapshot"] != plan["snapshot"]
                        or effect["validation_digest"] != plan["validation_digest"]):
                    raise FinancePostingError("asset_evidence_invalid", "Native effect differs from retained asset evidence.")
                native = {key: effect[key] for key in ("id", "entry_id", "validation_digest", "posted_actor_id",
                                                       "posted_at", "audit_event_id", "outbox_event_id")}
                phases.extend({"action": "fixed_asset_posted", **row} for row in records(self.connection.execute(
                    "SELECT posted_actor_id AS actor_id,audit_event_id,outbox_event_id FROM reconforge.fixed_asset_links WHERE tenant_id=%s AND plan_id=%s",
                    (self.tenant_id, plan_id))))
                phases.append({"action": "finance_entry_posted", "actor_id": native["posted_actor_id"],
                               "audit_event_id": native["audit_event_id"], "outbox_event_id": native["outbox_event_id"]})
            return {"schema_version": "fixed-asset-native-evidence-v1", "asset_definition": asset, "plan": view,
                    "canonical_asset_json": canonical_json({key: value for key, value in asset.items() if key != "asset_digest"}),
                    "canonical_plan_json": canonical_json({key: value for key, value in plan.items()
                                                           if key not in {"phase", "plan_digest", "validation_digest"}}),
                    "canonical_snapshot_json": canonical_json(plan["snapshot"]), "native_effect": native, "phases": phases,
                    "totals": {side + "_minor": str(sum(row[side + "_minor"] for row in plan["snapshot"]["lines"]))
                               for side in ("debit", "credit")}}

    def list_assets(self, scope: Mapping[str, Any], *, actor: PostingActor, after: str = "", limit: int = 25) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise FinancePostingError("asset_request_invalid", "Asset page size must be between 1 and 100.")
        with self.owner._transaction():
            self.owner._actor(actor, "finance_core.read", scope, mutation=False)
            rows = records(self.connection.execute("""SELECT id,payload FROM reconforge.fixed_assets
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s
                ORDER BY id COLLATE "C" LIMIT %s""", (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], after, limit + 1)))
            for row in rows[:limit]:
                self.owner._actor(actor, "finance_core.read", {**row["payload"], "amount_minor": row["payload"]["cost_minor"]}, mutation=False)
            return {"assets": [{**row["payload"], **self._state(row["payload"])} for row in rows[:limit]],
                    "next_after": rows[limit-1]["id"] if len(rows) > limit else None}
