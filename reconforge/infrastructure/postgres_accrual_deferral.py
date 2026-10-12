"""One atomic AD1 source owner using native GL and original-effect coordination."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.application.accrual_deferral_evidence import evidence_digest
from reconforge.domain.accrual_deferral import (
    AccrualDeferralPreparation,
    attach_original,
    captured_policy,
    fail,
    reversal_equation,
    source_equation,
    tranche_equation,
)
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.operational_fx_tax import canonical_day
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import platform_id

PERMISSIONS = {"prepare": "finance_core.manage", "review": "finance_core.validate",
               "post": "finance_core.post", "read": "finance_core.read"}
MAX_PLANS = 160
RESERVED_ORIGINALS = ("IC1-", "IC2-", "IC2S-", "IC2R-", "IC2E-", "FX1-", "ME1-", "ME1C-", "ME2-", "ME2C-", "HC1-", "HC1P-",
                      "OPS1-", "OB1-", "FI1-", "CA1-", "LC1-", "FA1-", "CR1-", "CRF1-", "SR1-", "AD1-", "AD1R-")


class _AccrualDeferralPostingParticipant:
    def __init__(self, owner: PostgresAccrualDeferralRepository, entry_id: str,
                 reversal: Mapping[str, Any] | None = None) -> None:
        self.owner, self.entry_id, self.reversal = owner, entry_id, reversal

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)

    def admits_reversal(self, connection: Any, tenant_id: str, entry_id: str,
                        original_effect_id: str, target_number: str) -> bool:
        value = self.reversal
        if (not self.admits(connection, tenant_id, entry_id) or not value
                or value["original_effect_id"] != original_effect_id or value["target_number"] != target_number
                or not target_number.startswith("AD1R-")
                or value["target_entry_id"] != platform_id("GLE", value["workspace_id"], target_number)):
            return False
        return self.owner.connection.execute("""SELECT 1 FROM reconforge.accrual_deferral_plans p
            JOIN reconforge.accrual_deferral_claim_heads h ON h.tenant_id=p.tenant_id AND h.source_id=p.source_id
             AND h.tranche_id=p.payload->>'tranche_id'
            JOIN reconforge.accrual_deferral_phase_events z ON z.tenant_id=p.tenant_id AND z.plan_id=p.id AND z.operation='post'
            JOIN reconforge.finance_posting_effects f ON f.tenant_id=z.tenant_id AND f.id=z.posting_effect_id
            WHERE p.tenant_id=%s AND p.id=%s AND p.source_id=%s AND p.phase=2 AND p.kind IN('release','accrue')
             AND p.payload->>'entry_id'=%s AND p.payload->>'plan_digest'=%s AND f.id=%s AND f.reverses_effect_id IS NULL
             AND h.state='Consumed' AND h.plan_id=p.id
             AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects r WHERE r.tenant_id=f.tenant_id AND r.reverses_effect_id=f.id)""",
            (tenant_id, value["original_plan_id"], value["source_id"], entry_id,
             value["original_plan_digest"], original_effect_id)).fetchone() is not None


class PostgresAccrualDeferralRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _AccrualDeferralPostingParticipant | None = None

    @contextmanager
    def _reference_locks(self, source: Mapping[str, Any], actor: PostingActor) -> Iterator[None]:
        """Lock exact shared chart references without changing business scope.

        Finance reference UPDATE policies intentionally forbid entity-selected
        mutations. FOR SHARE also needs that policy. Only metadata SELECTs
        belong in this savepoint; rollback restores aliases on failure.
        """
        self._authorize(actor, "prepare", source, lock=True)
        scope = self.connection.execute("SELECT current_setting('app.entity_id',true) AS entity,current_setting('app.legal_entity_id',true) AS legal_entity").fetchone()
        if any(scope[key] != self._scope(source)["legal_entity_id"] for key in ("entity", "legal_entity")):
            fail("Shared references require the unchanged original source entity selectors.")
        with self.connection.transaction():
            self.connection.execute("SELECT set_config('app.entity_id','',true),set_config('app.legal_entity_id','',true)")
            yield
            self.connection.execute("SELECT set_config('app.entity_id',%s,true),set_config('app.legal_entity_id',%s,true)",
                (scope["entity"] or "", scope["legal_entity"] or ""))
        self._authorize(actor, "prepare", source, lock=True)

    @staticmethod
    def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
        request = value.get("request", value)
        return {key: request[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}

    def _peek(self, kind: str, identifier: str, *, lock: bool = False, share: bool = False) -> dict[str, Any]:
        from psycopg import sql

        table = {"source": "accrual_deferral_sources", "plan": "accrual_deferral_plans"}[kind]
        query = sql.SQL("SELECT {} FROM {} WHERE tenant_id=%s AND id=%s{}").format(
            sql.SQL(",").join(sql.Identifier(column) for column in (("payload", "phase") if kind == "plan" else ("payload",))),
            sql.Identifier("reconforge", table), sql.SQL(" FOR UPDATE" if lock else " FOR SHARE" if share else ""))
        rows = records(self.connection.execute(query, (self.tenant_id, text(identifier, kind + "_id"))))
        if not rows:
            fail("The voucher schedule is absent or outside current scope.", "accrual_deferral_not_found")
        return {**rows[0]["payload"], **({"phase": rows[0]["phase"]} if kind == "plan" else {})}

    def _authorize(self, actor: PostingActor, operation: str, source: Mapping[str, Any],
                   plan: Mapping[str, Any] | None = None, *, lock: bool = False) -> None:
        from psycopg import sql

        scope = self._scope(source)
        request = source.get("request", source)
        if "policy" in source:
            scope.update(amount_minor=request["amount_minor"], currency_precision=source["policy"]["currency_precision"])
        for permission in ("accrual_deferral." + operation, PERMISSIONS[operation]):
            self.owner._actor(actor, permission, scope, mutation=operation != "read")
        if operation != "read" and plan and plan["kind"] == "reverse":
            self.owner._actor(actor, "finance_core.reverse", scope, mutation=True)
        grants = records(self.connection.execute(sql.SQL("""SELECT scope_type,scope_id FROM reconforge.principal_scope_grants
            WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
             AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
              OR(scope_type='legal_entity' AND scope_id=%s)) ORDER BY scope_type,scope_id{}""").format(sql.SQL(" FOR SHARE" if lock else "")),
            (self.tenant_id, actor.user_id, *self._scope(source).values())))
        if len({(row["scope_type"], row["scope_id"]) for row in grants}) != 3:
            fail("Current persisted workspace, organization and native entity grants are required.", "accrual_deferral_scope_denied")

    def _parents(self, request: Mapping[str, Any], period_id: str, day: str, *, require_open: bool) -> None:
        periods = {request["period_id"], period_id}
        periods.update(item["period_id"] for item in request["tranches"])
        periods.update(item["reversal_period_id"] for item in request["tranches"] if "reversal_period_id" in item)
        # All period locks precede the currency binding and original-effect gate.
        for identifier in sorted(periods):
            row = self.connection.execute("SELECT id,status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                (self.tenant_id, identifier, request["workspace_id"])).fetchone()
            if row is None or identifier == period_id and (not str(row["start_date"]) <= day <= str(row["end_date"])
                    or require_open and row["status"] != "Open"):
                fail("The retained native fiscal period is absent, closed or outside the exact posting date.", "accrual_deferral_period_locked")
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(request["workspace_id"])
        binding = self.connection.execute("SELECT registry_version,registry_digest FROM reconforge.currency_registry_bindings WHERE tenant_id=%s AND workspace_id=%s FOR SHARE",
            (self.tenant_id, request["workspace_id"])).fetchone()
        if binding is None:
            fail("Bind and review the workspace currency registry through native master data before a voucher schedule.", "accrual_deferral_policy_missing")
        row = self.connection.execute("""SELECT e.entity_code,e.currency_code,e.active,o.organization_code,o.active AS org_active
            FROM reconforge.legal_entities e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id
            WHERE e.tenant_id=%s AND e.id=%s AND e.organization_id=%s AND o.application_workspace_id=%s FOR SHARE OF e,o""",
            (self.tenant_id, request["legal_entity_id"], request["organization_id"], request["workspace_id"])).fetchone()
        if row is None or not row["active"] or not row["org_active"] or any(row[field] != request[field] for field in
                ("entity_code", "currency_code", "organization_code")):
            fail("The current native legal entity, organization and declared functional currency must match the source.")

    def _accounts(self, request: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        with self._reference_locks(request, actor):
            rows = records(self.connection.execute("""SELECT a.id,a.account_code,a.account_type,a.chart_id FROM reconforge.finance_accounts a
                JOIN reconforge.finance_journals j ON j.tenant_id=a.tenant_id AND j.chart_id=a.chart_id
                JOIN reconforge.finance_charts c ON c.tenant_id=a.tenant_id AND c.id=a.chart_id
                WHERE a.tenant_id=%s AND a.workspace_id=%s AND j.journal_code=%s AND j.organization_code=%s
                 AND j.workspace_id=a.workspace_id AND c.workspace_id=a.workspace_id AND c.organization_code IN('',j.organization_code)
                 AND j.currency_code=%s AND j.active AND a.active AND c.active AND a.account_code=ANY(%s) ORDER BY a.id FOR SHARE OF a,j,c""",
                (self.tenant_id, request["workspace_id"], request["journal_code"], request["organization_code"],
                 request["currency_code"], list(request["accounts"].values()))))
        by_code = {row["account_code"]: row for row in rows}
        if len(by_code) != 4:
            fail("Four captured active native account roles in the original journal chart are required.")
        result = {}
        for role, account in request["accounts"].items():
            expected = "Asset" if role in {"prepaid", "cash"} else "Expense" if role == "expense" else "Liability"
            if by_code[account]["account_type"] != expected:
                fail("Prepaid, expense, accrued liability and cash must retain their distinct native account types.")
            result[role] = by_code[account]
        return result

    def _period_snapshot(self, identifier: str, workspace: str) -> dict[str, Any]:
        row = self.connection.execute("""SELECT id,start_date,end_date,fiscal_year,period_number,application_workspace_id
            FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE""",
            (self.tenant_id, identifier, workspace)).fetchone()
        if row is None:
            fail("The captured original native fiscal period is absent or outside the source workspace.")
        return {key: str(value) if key in {"start_date", "end_date"} else value for key, value in dict(row).items()}

    def _calendar(self, request: Mapping[str, Any]) -> dict[str, Any]:
        periods = {request["period_id"], *(item["period_id"] for item in request["tranches"]),
                   *(item["reversal_period_id"] for item in request["tranches"] if "reversal_period_id" in item)}
        return {identifier: self._period_snapshot(identifier, request["workspace_id"]) for identifier in sorted(periods)}

    def _pin_period(self, source_id: str, period: Mapping[str, Any]) -> None:
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_period_pins
            (tenant_id,source_id,period_id,start_date,end_date,fiscal_year,period_number,application_workspace_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,source_id,period_id) DO NOTHING""",
            (self.tenant_id, source_id, period["id"], period["start_date"], period["end_date"], period["fiscal_year"],
             period["period_number"], period["application_workspace_id"]))

    def _command(self, source: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "command_id", maximum=140)
        payload = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest, scope = digest_payload(payload), self._scope(source)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "accrual-deferral-v1", command_id]),))
        rows = records(self.connection.execute("SELECT * FROM reconforge.accrual_deferral_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            fail("Command identity already binds another actor, source scope or exact request.", "accrual_deferral_command_conflict")
        return digest, dict(row["response_json"])

    def _view(self, plan_id: str) -> dict[str, Any]:
        plan = self._peek("plan", plan_id)
        phases = {row["operation"]: row for row in records(self.connection.execute(
            "SELECT operation,actor_id,posting_effect_id FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=%s AND plan_id=%s",
            (self.tenant_id, plan_id)))}
        return {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
            "reviewer_actor_id": phases.get("review", {}).get("actor_id"),
            "posted_actor_id": phases.get("post", {}).get("actor_id"),
            "posting_effect_id": phases.get("post", {}).get("posting_effect_id")}

    def _remember(self, source: Mapping[str, Any], plan_id: str, operation: str, command_id: str, actor: PostingActor,
                  request: Mapping[str, Any], digest: str) -> dict[str, Any]:
        result = self._view(plan_id)
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, *self._scope(source).values(), plan_id, operation, command_id, actor.user_id, digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        self.connection.execute("SELECT reconforge.ad1_close(%s,%s)", (self.tenant_id, plan_id))
        return result

    def _phase_event(self, source: Mapping[str, Any], plan_id: str, operation: str, actor: PostingActor,
                     reason: str, digest: str, effect_id: str | None = None) -> None:
        scope = self._scope(source)
        audit, outbox = self.owner._event({"id": plan_id, **scope}, "accrual_deferral_" + operation,
            actor, {"plan_digest": digest})
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_phase_events
            (tenant_id,plan_id,operation,actor_id,reason,posting_effect_id,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, plan_id, operation, actor.user_id, reason, effect_id, audit, outbox))

    def _claim_event(self, source_id: str, tranche_id: str, plan_id: str, operation: str) -> None:
        row = self.connection.execute("SELECT sequence FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=%s AND source_id=%s AND tranche_id=%s FOR UPDATE",
            (self.tenant_id, source_id, tranche_id)).fetchone()
        sequence = int(row["sequence"]) + 1 if row is not None else 1
        if sequence > 16:
            fail("A tranche has reached its retained 16-event correction bound.")
        state = "Reserved" if operation == "Claim" else "Consumed" if operation == "Consume" else "Available"
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_claim_events
            (tenant_id,source_id,tranche_id,sequence,plan_id,operation,state) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, source_id, tranche_id, sequence, plan_id, operation, state))
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_claim_heads(tenant_id,source_id,tranche_id,sequence,plan_id,state)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,source_id,tranche_id) DO UPDATE
            SET sequence=EXCLUDED.sequence,plan_id=EXCLUDED.plan_id,state=EXCLUDED.state""",
            (self.tenant_id, source_id, tranche_id, sequence, plan_id, state))

    def _dimensions(self, source: Mapping[str, Any], dimensions: Mapping[str, str], actor: PostingActor) -> dict[str, str]:
        result = {}
        for dimension, value in sorted(dimensions.items()):
            with self._reference_locks(source, actor):
                row = self.connection.execute("""SELECT d.dimension_code,v.value_code FROM reconforge.finance_dimensions d
                    JOIN reconforge.finance_dimension_values v ON v.tenant_id=d.tenant_id AND v.dimension_id=d.id
                    WHERE d.tenant_id=%s AND d.id=%s AND v.id=%s AND d.workspace_id=%s AND v.workspace_id=d.workspace_id AND d.active AND v.active
                     AND d.organization_code IN('',%s) FOR SHARE OF d,v""",
                    (self.tenant_id, dimension, value, source["request"]["workspace_id"], source["request"]["organization_code"])).fetchone()
            if row is None:
                fail("Original accounting dimensions are absent, inactive or outside the native source scope.")
            result[row["dimension_code"]] = row["value_code"]
        return result

    def _create_plan(self, source: Mapping[str, Any], request: Mapping[str, Any], equation: Mapping[str, Any],
                     actor: PostingActor, *, command_id: str, digest: str) -> dict[str, Any]:
        cfg, kind = source["request"], request["kind"]
        if self.connection.execute("SELECT count(*) AS n FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s",
                (self.tenant_id, source["id"])).fetchone()["n"] >= MAX_PLANS:
            fail("A schedule has reached its 160-plan correction bound.")
        identifier = ("AD1R-" if kind == "reverse" else "AD1-") + uuid4().hex
        entry_id, snapshot, native_digest = None, None, None
        if equation["native_effect_required"]:
            if kind == "reverse":
                original = self._view(request["original_plan_id"])
                number = identifier.upper()
                self._participant = _AccrualDeferralPostingParticipant(self, original["entry_id"], {
                    "source_id": source["id"], "original_plan_id": original["id"], "original_plan_digest": original["plan_digest"],
                    "original_effect_id": original["posting_effect_id"], "workspace_id": cfg["workspace_id"],
                    "target_number": number, "target_entry_id": platform_id("GLE", cfg["workspace_id"], number)})
                try:
                    inverse = self.owner.posting.prepare_reversal(original["posting_effect_id"], command_id="AD1R:" + digest,
                        entry_number=number, period_id=request["period_id"], posting_date=request["posting_date"],
                        reason=request["reason"], actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                entry_id = inverse["entry_id"]
            else:
                precision = source["policy"]["currency_precision"]
                native = self.owner.finance.create_entry(entry_number=identifier.upper(), organization_code=cfg["organization_code"],
                    entity_code=cfg["entity_code"], journal_code=cfg["journal_code"], period_id=request["period_id"],
                    posting_date=request["posting_date"], description=request["reason"], workspace=cfg["workspace_id"],
                    external_reference="AD1:" + source["id"] + ":" + kind, actor_label=actor.username,
                    lines=[{"account_code": row["account_code"], "debit": exact_minor_text(row["debit_minor"], precision) if row["debit_minor"] else "0",
                        "credit": exact_minor_text(row["credit_minor"], precision) if row["credit_minor"] else "0", "description": request["reason"],
                        "dimensions": self._dimensions(source, row["dimensions"], actor)} for row in equation["lines"]])
                entry_id = native["id"]
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
            if any(snapshot["entry"][field] != value for field, value in source["policy"].items()):
                fail("The native voucher must retain its exact captured functional currency policy.")
            native_digest = validation_digest(snapshot)
        plan = {"schema_version": "accrual-deferral-plan-v1", "id": identifier, "source_id": source["id"], **self._scope(source),
            "kind": kind, "tranche_id": request.get("tranche_id"), "original_plan_id": request.get("original_plan_id"),
            "period_id": request["period_id"], "posting_date": request["posting_date"], "reason": request["reason"],
            "native_period": self._period_snapshot(request["period_id"], cfg["workspace_id"]),
            "entry_id": entry_id, "snapshot": snapshot, "validation_digest": native_digest,
            "source_digest": source["source_digest"], "preparer_actor_id": actor.user_id,
            "equation": dict(equation), "command_request": dict(request)}
        plan["plan_digest"] = digest_payload(plan)
        self._pin_period(source["id"], plan["native_period"])
        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_plans(tenant_id,id,source_id,kind,phase,payload)
            VALUES(%s,%s,%s,%s,0,%s::jsonb)""", (self.tenant_id, identifier, source["id"], kind, canonical_json(plan)))
        if kind == "source":
            for item in cfg["tranches"]:
                self._claim_event(source["id"], item["id"], identifier, "Initialize")
        elif kind in {"release", "accrue"}:
            self._claim_event(source["id"], request["tranche_id"], identifier, "Claim")
        self._phase_event(source, identifier, "prepare", actor, request["reason"], plan["plan_digest"])
        return self._remember(source, identifier, "prepare", command_id, actor, request, digest)

    def prepare_source(self, request: AccrualDeferralPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        cfg = request.payload()
        envelope = {"kind": "source", "period_id": cfg["period_id"], "posting_date": cfg["posting_date"],
                    "reason": cfg["reason"], "original_request": cfg}
        with self.owner._transaction():
            self._authorize(actor, "prepare", cfg)
            digest, replay = self._command(cfg, "prepare", command_id, actor, envelope)
            self._parents(cfg, cfg["period_id"], cfg["posting_date"], require_open=replay is None)
            if replay is not None:
                source = self._peek("source", replay["source_id"], lock=True)
                self._authorize(actor, "prepare", source, replay, lock=True)
                self.connection.execute("SELECT reconforge.ad1_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            accounts = self._accounts(cfg, actor)
            master = self.connection.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                (self.tenant_id, cfg["currency_code"])).fetchone()
            if master is None:
                fail("The declared functional currency needs its active canonical native master.")
            _, context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(workspace_id=cfg["workspace_id"],
                currency_code=cfg["currency_code"], minor_units=master["minor_units"], actor_label=actor.username)
            attached = None
            if cfg["mode"].startswith("attach_"):
                effect = self.owner.posting._get_effect(cfg["original_effect_id"])
                self.connection.execute("SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)", (self.tenant_id, effect["id"]))
                if self.connection.execute("""SELECT 1 FROM reconforge.financial_effect_ownership_guards g
                    WHERE g.tenant_id=%s AND g.source_effect_id=%s AND NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_releases r
                     WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id)""", (self.tenant_id, effect["id"])).fetchone():
                    fail("The whole original voucher is already owned by an active operating source.", "accrual_deferral_original_claimed")
                if self.connection.execute("SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND reverses_effect_id=%s",
                        (self.tenant_id, effect["id"])).fetchone():
                    fail("The attached original voucher has already been reversed.")
                reviewed = posting_entry(self.connection, self.tenant_id, effect["entry_id"])
                # All operational entries use reserved namespaces even when
                # their native effect kind is Manual. Their owner is preserved.
                if reviewed["id"].upper().startswith(RESERVED_ORIGINALS) or reviewed["entry_number"].upper().startswith(RESERVED_ORIGINALS):
                    fail("An operating source voucher must stay with its original source owner.")
                attached = attach_original(cfg, effect, reviewed, {role: row["id"] for role, row in accounts.items()}, context)
            equation = source_equation(cfg, context, attached)
            source = {"schema_version": "accrual-deferral-source-v1", "id": "AD1S-" + uuid4().hex,
                "request": cfg, "policy": captured_policy(cfg["currency_code"], context), "equation": equation,
                "native_accounts": accounts, "native_periods": self._calendar(cfg), "preparer_actor_id": actor.user_id}
            source["source_digest"] = digest_payload(source)
            self._authorize(actor, "prepare", source, lock=True)
            self.connection.execute("""INSERT INTO reconforge.accrual_deferral_sources
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,reference,payload) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (self.tenant_id, source["id"], *self._scope(source).values(), cfg["reference"], canonical_json(source)))
            for period in source["native_periods"].values():
                self._pin_period(source["id"], period)
            for role, account in accounts.items():
                self.connection.execute("""INSERT INTO reconforge.accrual_deferral_account_pins
                    (tenant_id,source_id,role,account_id,workspace_id,chart_id,account_code,account_type)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, source["id"], role, account["id"],
                    cfg["workspace_id"], account["chart_id"], account["account_code"], account["account_type"]))
            if attached is not None:
                claim_id = "AD1C-" + uuid4().hex
                self.connection.execute("""INSERT INTO reconforge.accrual_deferral_original_claims
                    (tenant_id,id,source_id,workspace_id,organization_id,legal_entity_id,effect_id,state) VALUES(%s,%s,%s,%s,%s,%s,%s,'Reserved')""",
                    (self.tenant_id, claim_id, source["id"], *self._scope(source).values(), cfg["original_effect_id"]))
                self.connection.execute("""INSERT INTO reconforge.financial_effect_ownership_guards
                    (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_effect_id,owner_namespace,owner_claim_id)
                    VALUES(%s,%s,%s,%s,%s,%s,'AD1',%s)""",
                    (self.tenant_id, claim_id, *self._scope(source).values(), cfg["original_effect_id"], claim_id))
            return self._create_plan(source, envelope, equation, actor, command_id=command_id, digest=digest)

    def _progress(self, source_id: str, request: Mapping[str, Any], *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id)
            cfg = source["request"]
            kind = request["kind"]
            if kind in {"release", "accrue"}:
                initial = self.connection.execute("SELECT id FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s AND kind='source'",
                    (self.tenant_id, source_id)).fetchone()
                if initial is None:
                    fail("The original voucher approval is missing.")
                equation = tranche_equation({**source, "phase": self._peek("plan", initial["id"])["phase"]}, request["tranche_id"])
                command_request = {"kind": equation["operation"], "source_id": source_id, "tranche_id": request["tranche_id"],
                    "period_id": equation["period_id"], "posting_date": equation["posting_date"], "reason": cfg["reason"]}
            elif kind == "reverse":
                original = self._view(request["original_plan_id"])
                if original["source_id"] != source_id:
                    fail("The tranche inverse must bind this exact original schedule.")
                equation = reversal_equation(original)
                command_request = {**request, "source_id": source_id, "tranche_id": original["tranche_id"]}
                if cfg["mode"] == "expense_accrual":
                    tranche = next(row for row in cfg["tranches"] if row["id"] == original["tranche_id"])
                    if (request["period_id"], request["posting_date"]) != (tranche["reversal_period_id"], tranche["reversal_date"]):
                        fail("Accrual inverse must retain its explicit original next-period date and identity.")
                if request["posting_date"] < original["posting_date"]:
                    fail("An inverse cannot precede its approved original tranche.")
            else:
                command_request = {"kind": "cancel", "source_id": source_id, "period_id": cfg["period_id"],
                    "posting_date": cfg["posting_date"], "reason": request["reason"]}
                equation = {"schema_version": "accrual-deferral-source-v1", "operation": "cancel", "lines": [],
                    "policy": source["policy"], "cash_changed_minor": 0, "native_effect_required": False}
            preliminary = {"kind": kind, "equation": equation}
            self._authorize(actor, "prepare", source, preliminary)
            digest, replay = self._command(source, "prepare", command_id, actor, command_request)
            self._parents(cfg, command_request["period_id"], command_request["posting_date"], require_open=replay is None)
            source = self._peek("source", source_id, lock=True)
            self._authorize(actor, "prepare", source, preliminary, lock=True)
            if replay is not None:
                self.connection.execute("SELECT reconforge.ad1_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            if self.connection.execute("SELECT 1 FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s AND kind='cancel'",
                    (self.tenant_id, source_id)).fetchone():
                fail("A cancellation is already retained for this original schedule.")
            if kind == "cancel":
                if self.connection.execute("""SELECT 1 FROM reconforge.accrual_deferral_phase_events e
                    JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=e.tenant_id AND p.id=e.plan_id
                    WHERE p.tenant_id=%s AND p.source_id=%s AND e.posting_effect_id IS NOT NULL""", (self.tenant_id, source_id)).fetchone():
                    fail("A financially consumed voucher requires a complete explicit source correction; cancellation is refused.")
            else:
                if self.connection.execute("SELECT 1 FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s AND phase<2",
                        (self.tenant_id, source_id)).fetchone():
                    fail("Complete the retained pending tranche before another schedule operation.")
                if kind in {"release", "accrue"}:
                    head = self.connection.execute("SELECT state FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=%s AND source_id=%s AND tranche_id=%s",
                        (self.tenant_id, source_id, request["tranche_id"])).fetchone()
                    if head is None or head["state"] != "Available":
                        fail("A tranche already has an active native financial claim.")
            return self._create_plan(source, command_request, equation, actor, command_id=command_id, digest=digest)

    def prepare_tranche(self, source_id: str, *, tranche_id: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "release", "tranche_id": text(tranche_id, "tranche_id", maximum=40)},
            command_id=command_id, actor=actor)

    def prepare_reversal(self, source_id: str, *, original_plan_id: str, period_id: str,
                         posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "reverse", "original_plan_id": text(original_plan_id, "original_plan_id"),
            "period_id": text(period_id, "period_id"), "posting_date": canonical_day(posting_date, "posting_date"),
            "reason": text(reason, "reason", maximum=500)}, command_id=command_id, actor=actor)

    def prepare_cancellation(self, source_id: str, *, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "cancel", "reason": text(reason, "reason", maximum=500)}, command_id=command_id, actor=actor)

    def _phase(self, operation: str, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": text(plan_id, "plan_id"), "expected_plan_digest": expected_plan_digest,
                   "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            initial = self._peek("plan", plan_id)
            source = self._peek("source", initial["source_id"])
            self._authorize(actor, operation, source, initial)
            digest, replay = self._command(source, operation, command_id, actor, request)
            self._parents(source["request"], initial["period_id"], initial["posting_date"], require_open=replay is None)
            source = self._peek("source", source["id"], lock=True)
            plan = self._view(plan_id)
            self._authorize(actor, operation, source, plan, lock=True)
            if replay is not None:
                self.connection.execute("SELECT reconforge.ad1_close(%s,%s)", (self.tenant_id, plan_id))
                return replay
            cancelled = self.connection.execute("SELECT 1 FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s AND kind='cancel' AND id<>%s",
                (self.tenant_id, source["id"], plan_id)).fetchone()
            if (cancelled or plan["plan_digest"] != expected_plan_digest or plan["phase"] != (0 if operation == "review" else 1)
                    or actor.user_id == plan["preparer_actor_id"] or operation == "post" and actor.user_id == plan["reviewer_actor_id"]):
                fail("The exact current source phase/digest and three distinct human identities are required.", "accrual_deferral_state_conflict")
            effect_id = None
            if operation == "review" and plan["entry_id"]:
                self.owner.finance.validate_entry(plan["entry_id"], reason=request["reason"], actor_label=actor.username)
            if operation == "post":
                if plan["entry_id"]:
                    self._participant = _AccrualDeferralPostingParticipant(self, plan["entry_id"])
                    try:
                        effect = self.owner.posting.post(plan["entry_id"], command_id="AD1:" + digest,
                            expected_validation_digest=plan["validation_digest"], reason=request["reason"], actor=actor,
                            _source_owner=self._participant)
                    finally:
                        self._participant = None
                    effect_id = effect["id"]
                # A directory cancellation release is admitted against the
                # exact third-human posted cancellation in this transaction.
                self._phase_event(source, plan_id, operation, actor, request["reason"], plan["plan_digest"], effect_id)
                self.connection.execute("UPDATE reconforge.accrual_deferral_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
                if plan["kind"] in {"release", "accrue"}:
                    self._claim_event(source["id"], plan["tranche_id"], plan_id, "Consume")
                elif plan["kind"] == "reverse":
                    original = self._view(plan["original_plan_id"])
                    self._claim_event(source["id"], original["tranche_id"], plan_id, "Reverse")
                if effect_id and plan["kind"] != "reverse":
                    self.connection.execute("UPDATE reconforge.accrual_deferral_original_claims SET state='Consumed' WHERE tenant_id=%s AND source_id=%s AND state='Reserved'",
                        (self.tenant_id, source["id"]))
                if plan["kind"] == "cancel":
                    if self.connection.execute("""SELECT 1 FROM reconforge.accrual_deferral_phase_events e
                        JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=e.tenant_id AND p.id=e.plan_id
                        WHERE p.tenant_id=%s AND p.source_id=%s AND e.posting_effect_id IS NOT NULL""", (self.tenant_id, source["id"])).fetchone():
                        fail("A financially consumed original cannot release its ownership through cancellation.")
                    for head in records(self.connection.execute("SELECT tranche_id FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=%s AND source_id=%s ORDER BY tranche_id",
                            (self.tenant_id, source["id"]))):
                        self._claim_event(source["id"], head["tranche_id"], plan_id, "Cancel")
                    claim = self.connection.execute("SELECT * FROM reconforge.accrual_deferral_original_claims WHERE tenant_id=%s AND source_id=%s FOR UPDATE",
                        (self.tenant_id, source["id"])).fetchone()
                    if claim is not None:
                        release_id = "AD1L-" + uuid4().hex
                        self.connection.execute("UPDATE reconforge.accrual_deferral_original_claims SET state='Released' WHERE tenant_id=%s AND id=%s AND state='Reserved'",
                            (self.tenant_id, claim["id"]))
                        self.connection.execute("""INSERT INTO reconforge.accrual_deferral_original_releases
                            (tenant_id,id,claim_id,source_id,workspace_id,organization_id,legal_entity_id,cancellation_plan_id)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, release_id, claim["id"], source["id"], *self._scope(source).values(), plan_id))
                        self.connection.execute("INSERT INTO reconforge.financial_effect_ownership_releases(tenant_id,guard_id,release_id) VALUES(%s,%s,%s)",
                            (self.tenant_id, claim["id"], release_id))
            else:
                self._phase_event(source, plan_id, operation, actor, request["reason"], plan["plan_digest"])
                self.connection.execute("UPDATE reconforge.accrual_deferral_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
            return self._remember(source, plan_id, operation, command_id, actor, request, digest)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("review", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("post", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._view(plan_id)
            source = self._peek("source", plan["source_id"], share=True)
            self._authorize(actor, "read", source, plan, lock=True)
            return plan

    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id, share=True)
            self._authorize(actor, "read", source, lock=True)
            plans = [self._view(row["id"]) for row in records(self.connection.execute(
                "SELECT id FROM reconforge.accrual_deferral_plans WHERE tenant_id=%s AND source_id=%s ORDER BY id LIMIT 161", (self.tenant_id, source_id)))]
            for plan in plans:
                self._authorize(actor, "read", source, plan, lock=True)
            heads = records(self.connection.execute("SELECT tenant_id,source_id,tranche_id,sequence,plan_id,state FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=%s AND source_id=%s ORDER BY tranche_id",
                (self.tenant_id, source_id)))
            return {**source, "plans": plans, "claims": heads, "cancelled": any(plan["kind"] == "cancel" and plan["phase"] == 2 for plan in plans)}

    def plan_evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._view(plan_id)
            return self.evidence(plan["source_id"], actor=actor, plan_id=plan_id)

    def evidence(self, source_id: str, *, actor: PostingActor, plan_id: str | None = None) -> dict[str, Any]:
        with self.owner._transaction():
            if plan_id is None:
                source = self.get_source(source_id, actor=actor)
            else:
                source = self._peek("source", source_id, share=True)
                plan = self._view(plan_id)
                if plan["source_id"] != source_id:
                    fail("Evidence member does not belong to the original source.", "accrual_deferral_plan_not_found")
                plans = [plan]
                if plan.get("original_plan_id"):
                    plans.append(self._view(plan["original_plan_id"]))
                self._authorize(actor, "read", source, lock=True)
                for member in plans:
                    self._authorize(actor, "read", source, member, lock=True)
                tranche_ids = [member["tranche_id"] for member in plans if member.get("tranche_id")]
                heads = records(self.connection.execute("""SELECT tenant_id,source_id,tranche_id,sequence,plan_id,state
                    FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=%s AND source_id=%s AND tranche_id=ANY(%s) ORDER BY tranche_id""",
                    (self.tenant_id, source_id, tranche_ids)))
                source = {**source, "plans": plans, "claims": heads}
            member_ids = [plan["id"] for plan in source["plans"]]
            tranche_filter = None if plan_id is None else [plan["tranche_id"] for plan in source["plans"] if plan.get("tranche_id")]
            identifiers = [plan["posting_effect_id"] for plan in source["plans"] if plan["posting_effect_id"]]
            attached = source["equation"]["external_original_membership"].get("original_effect_id")
            if attached:
                identifiers.append(attached)
            effects = [{"tenant_id": self.tenant_id, **effect} for effect in self.owner.posting.iter_verified_posting_effects(effect_ids=identifiers, actor=actor)]
            claims = records(self.connection.execute("""SELECT tenant_id,source_id,tranche_id,sequence,plan_id,operation,state
                FROM reconforge.accrual_deferral_claim_events WHERE tenant_id=%s AND source_id=%s
                AND (%s::text[] IS NULL OR tranche_id=ANY(%s)) ORDER BY tranche_id,sequence""",
                (self.tenant_id, source_id, tranche_filter, tranche_filter)))
            phases = records(self.connection.execute("""SELECT e.* FROM reconforge.accrual_deferral_phase_events e
                JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=e.tenant_id AND p.id=e.plan_id
                WHERE p.tenant_id=%s AND p.source_id=%s AND p.id=ANY(%s) ORDER BY p.id,e.operation""", (self.tenant_id, source_id, member_ids)))
            value = {"schema_version": "accrual-deferral-native-evidence-v1" if plan_id is None else "accrual-deferral-plan-evidence-v1",
                "qualified_scope": {"tenant_id": self.tenant_id, **self._scope(source)},
                "source": source, "native_effects": effects,
                "claims": claims, "phases": phases, "financial_directory": records(self.connection.execute("""SELECT g.* FROM reconforge.financial_effect_ownership_guards g
                    JOIN reconforge.accrual_deferral_original_claims c ON c.tenant_id=g.tenant_id AND c.id=g.owner_claim_id
                    WHERE c.tenant_id=%s AND c.source_id=%s AND g.owner_namespace='AD1'""", (self.tenant_id, source_id))),
                "original_claims": records(self.connection.execute("SELECT * FROM reconforge.accrual_deferral_original_claims WHERE tenant_id=%s AND source_id=%s", (self.tenant_id, source_id))),
                "original_releases": records(self.connection.execute("SELECT * FROM reconforge.accrual_deferral_original_releases WHERE tenant_id=%s AND source_id=%s", (self.tenant_id, source_id))),
                "calendar_pins": records(self.connection.execute("""SELECT tenant_id,source_id,period_id,start_date::text AS start_date,end_date::text AS end_date,
                    fiscal_year,period_number,application_workspace_id FROM reconforge.accrual_deferral_period_pins WHERE tenant_id=%s AND source_id=%s ORDER BY period_id""",
                    (self.tenant_id, source_id))),
                "account_pins": records(self.connection.execute("SELECT * FROM reconforge.accrual_deferral_account_pins WHERE tenant_id=%s AND source_id=%s ORDER BY role",
                    (self.tenant_id, source_id))),
                "financial_directory_releases": records(self.connection.execute("""SELECT r.* FROM reconforge.financial_effect_ownership_releases r
                    JOIN reconforge.accrual_deferral_original_claims c ON c.tenant_id=r.tenant_id AND c.id=r.guard_id WHERE c.tenant_id=%s AND c.source_id=%s""", (self.tenant_id, source_id))),
                "commands": records(self.connection.execute("""SELECT c.* FROM reconforge.accrual_deferral_commands c JOIN reconforge.accrual_deferral_plans p
                    ON p.tenant_id=c.tenant_id AND p.id=c.plan_id WHERE p.tenant_id=%s AND p.source_id=%s AND p.id=ANY(%s)
                    ORDER BY c.plan_id,c.operation""", (self.tenant_id, source_id, member_ids)))}
            if plan_id is not None:
                value["member_manifest"] = {"selected_plan_id": plan_id, "whole_source": False,
                    "source_digest": source["source_digest"],
                    "plans": [{"id": plan["id"], "plan_digest": plan["plan_digest"]} for plan in source["plans"]]}
            value["evidence_digest"] = evidence_digest(value)
            return value

    def list_sources(self, *, workspace_id: str, organization_id: str, legal_entity_id: str,
                     after: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            scope = {"workspace_id": text(workspace_id, "workspace_id"), "organization_id": text(organization_id, "organization_id"),
                "legal_entity_id": text(legal_entity_id, "legal_entity_id")}
            rows = records(self.connection.execute("""SELECT id,payload FROM reconforge.accrual_deferral_sources WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s ORDER BY id LIMIT 51""",
                (self.tenant_id, *scope.values(), after)))
            result = []
            for row in rows[:50]:
                self._authorize(actor, "read", row["payload"])
                request = row["payload"]["request"]
                result.append({"id": row["id"], **scope, "reference": request["reference"], "mode": request["mode"],
                    "currency_code": request["currency_code"], "amount_minor": request["amount_minor"],
                    "posting_date": request["posting_date"], "source_digest": row["payload"]["source_digest"]})
            return {"items": result, "next_cursor": rows[49]["id"] if len(rows) > 50 else None}
