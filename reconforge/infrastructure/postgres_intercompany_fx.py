"""Atomic native paired foreign trade with reviewed exact translation membership."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.intercompany_fx import (
    MAX_EFFECT_LINES,
    MAX_OPERATIONS,
    MAX_SETTLEMENTS,
    PARTIES,
    IntercompanyFxPreparation,
    elimination_equation,
    fail,
    group_report,
    recognition_equation,
    revaluation_equation,
    reversal_equation,
    settlement_equation,
    translate_book,
)
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import platform_id
from reconforge.utils.money import CurrencyRegistryContext

BOOKS = (*PARTIES, "adjustment")
SUFFIX = {"seller": "A", "buyer": "B", "adjustment": "G"}
PREFIX = {"recognize": "IC2-", "settle": "IC2S-", "revalue": "IC2R-", "reverse_revaluation": "IC2R-", "eliminate": "IC2E-"}
PERMISSIONS = {"prepare": "finance_core.manage", "review": "finance_core.validate", "post": "finance_core.post", "read": "finance_core.read"}


class _IntercompanyFxPostingParticipant:
    """Live source admission binds exact connection, owner, entry and inverse."""

    def __init__(self, owner: PostgresIntercompanyFxRepository, entry_id: str, *, reversal: dict[str, Any] | None = None) -> None:
        self.owner, self.entry_id, self.reversal = owner, entry_id, reversal

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)

    def admits_reversal(self, connection: Any, tenant_id: str, entry_id: str, original_effect_id: str, target_number: str) -> bool:
        value = self.reversal
        if (not self.admits(connection, tenant_id, entry_id) or not value
                or value["original_effect_id"] != original_effect_id or value["target_number"] != target_number
                or not target_number.startswith("IC2R-")
                or value["target_entry_id"] != platform_id("GLE", value["workspace_id"], target_number)):
            return False
        return self.owner.connection.execute("""SELECT 1 FROM reconforge.intercompany_fx_plans p
            JOIN reconforge.intercompany_fx_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id
            JOIN reconforge.finance_posting_effects f ON f.tenant_id=l.tenant_id AND f.id=l.posting_effect_id
            WHERE p.tenant_id=%s AND p.id=%s AND p.source_id=%s AND p.phase=2 AND p.kind='revalue'
            AND l.book=%s AND l.entry_id=%s AND f.id=%s AND f.reverses_effect_id IS NULL
            AND p.payload->>'plan_digest'=%s AND NOT EXISTS(SELECT 1 FROM reconforge.intercompany_fx_plans inverse
            WHERE inverse.tenant_id=p.tenant_id AND inverse.source_id=p.source_id AND inverse.phase=2
            AND inverse.kind='reverse_revaluation' AND inverse.payload->'equation'->>'original_revaluation_id'=p.id)""",
            (tenant_id, value["original_plan_id"], value["source_id"], value["book"], entry_id,
             original_effect_id, value["original_plan_digest"])).fetchone() is not None


class PostgresIntercompanyFxRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _IntercompanyFxPostingParticipant | None = None

    def _peek(self, kind: str, identifier: str, *, lock: bool = False, share: bool = False) -> dict[str, Any]:
        statement = {
            ("source", False): "SELECT payload FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s AND id=%s",
            ("source", True): "SELECT payload FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s AND id=%s FOR UPDATE",
            ("plan", False): "SELECT payload,phase FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND id=%s",
            ("plan", True): "SELECT payload,phase FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
        }[(kind, lock)] + (" FOR SHARE" if share and not lock else "")
        rows = records(self.connection.execute(statement, (self.tenant_id, text(identifier, kind + "_id"))))
        if not rows:
            fail("Paired FX source is absent or outside the complete authorized entity group.", "intercompany_fx_not_found")
        return {**rows[0]["payload"], **({"phase": rows[0]["phase"]} if kind == "plan" else {})}

    @staticmethod
    def _scope(source: Mapping[str, Any]) -> dict[str, str]:
        request = source.get("request", source)
        return {"workspace_id": request["workspace_id"], "organization_id": request["organization_id"],
                **{book + "_entity_id": request[book]["legal_entity_id"] for book in BOOKS}}

    def _authorize_reporting(self, actor: PostingActor, operation: str, source: Mapping[str, Any], amount: int) -> None:
        """A whole-source response exposes reporting values across all three books."""
        if amount <= 0:
            return
        request = source["request"]
        for book in BOOKS:
            scope = {"workspace_id": request["workspace_id"], "organization_id": request["organization_id"],
                "legal_entity_id": request[book]["legal_entity_id"], "amount_minor": amount,
                "currency_precision": source["policies"]["adjustment"]["currency_precision"]}
            for permission in ("intercompany_fx." + operation, PERMISSIONS[operation]):
                self.owner._actor(actor, permission, scope, mutation=operation != "read")

    def _authorize(self, actor: PostingActor, operation: str, source: Mapping[str, Any], plan: Mapping[str, Any] | None = None, *, lock: bool = False) -> None:
        request = source.get("request", source)
        for book in BOOKS:
            scope: dict[str, Any] = {"workspace_id": request["workspace_id"], "organization_id": request["organization_id"],
                                    "legal_entity_id": request[book]["legal_entity_id"]}
            if "policies" in source:
                original = source["original_positions"].get(book, {}).get("original_functional_minor", 0)
                position = (plan or {}).get("equation", {}).get("positions", {}).get(book, {})
                amount = max(original, position.get("amount_minor", 0), position.get("valued_outstanding_minor", 0),
                             position.get("historical_outstanding_minor", 0))
                translated = (plan or {}).get("equation", {}).get("translations", {}).get(book, {})
                amount = max([amount, *(abs(row["native_balance_minor"]) for row in translated.get("accounts", [])
                                       if row["native_balance_minor"] is not None)])
                if amount > 0:
                    scope.update(amount_minor=amount, currency_precision=source["policies"][book]["currency_precision"])
            for permission in ("intercompany_fx." + operation, PERMISSIONS[operation]):
                self.owner._actor(actor, permission, scope, mutation=operation != "read")
            if "policies" in source:
                self.owner._actor(actor, PERMISSIONS[operation], {**scope, "amount_minor": request["transaction_minor"],
                    "currency_precision": source["policies"]["transaction"]["currency_precision"]}, mutation=operation != "read")
            if operation != "read" and plan and plan["kind"] == "reverse_revaluation":
                self.owner._actor(actor, "finance_core.reverse", scope, mutation=True)
        from psycopg import sql

        grant_query = sql.SQL("""SELECT scope_type,scope_id FROM reconforge.principal_scope_grants
            WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL
            AND((scope_type='workspace' AND scope_id=%s) OR(scope_type='organization' AND scope_id=%s)
            OR(scope_type='legal_entity' AND scope_id=ANY(%s))) ORDER BY scope_type,scope_id{lock}""").format(
                lock=sql.SQL(" FOR SHARE" if lock else ""))
        grants = records(self.connection.execute(grant_query,
            (self.tenant_id, actor.user_id, request["workspace_id"], request["organization_id"],
             [request[book]["legal_entity_id"] for book in BOOKS])))
        if len({(row["scope_type"], row["scope_id"]) for row in grants}) != 5:
            fail("Current persisted workspace, organization and three entity grants are required.", "intercompany_fx_scope_denied")
        translations = (plan or {}).get("equation", {}).get("translations", {})
        reporting_amount = max([0, *(abs(row["balance_minor"]) for translation in translations.values()
            for row in translation["accounts"])])
        self._authorize_reporting(actor, operation, source, reporting_amount)

    def _parents(self, request: Mapping[str, Any], period_ids: Mapping[str, str], *, require_open: bool = True) -> None:
        if set(period_ids) != set(BOOKS):
            fail("Retain explicit seller, buyer and adjustment period identities.")
        for period_id in sorted(set(period_ids.values())):
            row = self.connection.execute("SELECT id,status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                (self.tenant_id, text(period_id, "period_id"), request["workspace_id"])).fetchone()
            if row is None or require_open and row["status"] != "Open":
                fail("Every retained native period must be present and open for mutation.", "intercompany_fx_period_locked")
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(request["workspace_id"])
        entities = records(self.connection.execute("""SELECT e.id,e.entity_code,e.currency_code,e.active,o.organization_code,o.active AS organization_active
            FROM reconforge.legal_entities e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id
            WHERE e.tenant_id=%s AND e.organization_id=%s AND o.application_workspace_id=%s AND e.id=ANY(%s)
            ORDER BY e.id FOR SHARE OF e,o""", (self.tenant_id, request["organization_id"], request["workspace_id"],
            sorted(request[book]["legal_entity_id"] for book in BOOKS))))
        by_id = {row["id"]: row for row in entities}
        for book in BOOKS:
            cfg = request[book]
            row = by_id.get(cfg["legal_entity_id"])
            if (row is None or not row["active"] or not row["organization_active"]
                    or row["organization_code"] != request["organization_code"]
                    or row["entity_code"] != cfg["entity_code"] or row["currency_code"] != cfg["currency_code"]):
                fail("Current active native entity identity and its own functional currency must match the source.", "intercompany_fx_scope_denied")

    def _account_maps(self, request: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for book in BOOKS:
            cfg = request[book]
            rows = records(self.connection.execute("""SELECT a.id,a.account_code,a.account_type,a.chart_id FROM reconforge.finance_accounts a
                JOIN reconforge.finance_journals j ON j.tenant_id=a.tenant_id AND j.chart_id=a.chart_id
                WHERE a.tenant_id=%s AND a.workspace_id=%s AND j.organization_code=%s AND j.journal_code=%s
                AND j.currency_code=%s AND j.active AND a.active AND a.account_code=ANY(%s) ORDER BY a.account_code FOR SHARE OF a,j""",
                (self.tenant_id, request["workspace_id"], request["organization_code"], cfg["journal_code"], cfg["currency_code"],
                 list(cfg["accounts"].values()))))
            by_code = {row["account_code"]: row for row in rows}
            if len(by_code) != len(cfg["accounts"]):
                fail("Every frozen native role must resolve to its active journal chart.")
            result[book] = {}
            for role, account in cfg["accounts"].items():
                expected = ("Asset" if role in {"cash", "receivable"} or role == "party" and book == "seller"
                    else "Liability" if role == "payable" or role == "party" and book == "buyer"
                    else "Income" if role in {"revenue", "realized_gain", "unrealized_gain"} or role == "trade" and book == "seller"
                    else "Equity" if role == "cta" else "Expense")
                if by_code[account]["account_type"] != expected:
                    fail("Native party, income, expense, FX and CTA roles must retain their explicit account semantics.")
                result[book][role] = by_code[account]
        return result

    def _context(self, source: Mapping[str, Any]) -> CurrencyRegistryContext:
        store = FinancePolicyStore(self.connection, tenant_id=self.tenant_id)
        contexts = [store.entry(source["policies"][book])[1] for book in ("transaction", *BOOKS)]
        if len({context.registry_manifest.digest for context in contexts}) != 1:
            fail("All currencies must retain their source workspace registry snapshot.")
        return contexts[0]

    def _state(self, source_id: str) -> dict[str, Any]:
        rows = records(self.connection.execute("SELECT payload FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND source_id=%s AND phase=2 ORDER BY sequence LIMIT 65",
            (self.tenant_id, source_id)))
        if len(rows) > MAX_OPERATIONS:
            fail("Paired FX operation history reached its declared bound.")
        plans = [row["payload"] for row in rows]
        active = None
        for plan in plans:
            if plan["kind"] == "revalue":
                active = plan["id"]
            elif plan["kind"] == "reverse_revaluation":
                active = None
        return {"sequence": len(plans), "recognized": bool(plans), "closed": bool(plans and plans[-1]["kind"] == "eliminate"),
            "settlements": sum(plan["kind"] == "settle" for plan in plans),
            "transaction_paid_minor": sum(plan["equation"]["transaction_minor"] for plan in plans if plan["kind"] == "settle"),
            "active_revaluation_id": active, "last_posting_date": plans[-1]["posting_date"] if plans else None}

    def _command(self, source: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        scope = self._scope(source)
        text(command_id, "command_id", maximum=140)
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(envelope)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "intercompany-fx-v2", command_id]),))
        rows = records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            fail("Command identity already binds another exact actor, scope or request.", "intercompany_fx_command_conflict")
        return digest, dict(row["response_json"])

    def _event(self, source: Mapping[str, Any], identifier: str, action: str, actor: PostingActor,
               metadata: dict[str, Any]) -> tuple[str, str]:
        scope = self._scope(source)
        return self.owner._event({"id": identifier, "workspace_id": scope["workspace_id"], "organization_id": scope["organization_id"],
            "legal_entity_id": scope["adjustment_entity_id"]}, action, actor, metadata)

    def _view(self, plan_id: str) -> dict[str, Any]:
        plan = self._peek("plan", plan_id)
        reviews = records(self.connection.execute("SELECT reviewer_actor_id FROM reconforge.intercompany_fx_reviews WHERE tenant_id=%s AND plan_id=%s",
            (self.tenant_id, plan_id)))
        links = records(self.connection.execute("SELECT book,posting_effect_id,posted_actor_id FROM reconforge.intercompany_fx_links WHERE tenant_id=%s AND plan_id=%s ORDER BY book",
            (self.tenant_id, plan_id)))
        return {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
            "reviewer_actor_id": reviews[0]["reviewer_actor_id"] if reviews else None,
            "posted_actor_id": links[0]["posted_actor_id"] if links else None,
            "posting_effect_ids": {row["book"]: row["posting_effect_id"] for row in links}}

    def _remember(self, source: Mapping[str, Any], plan_id: str, operation: str, command_id: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result, scope = self._view(plan_id), self._scope(source)
        self.connection.execute("""INSERT INTO reconforge.intercompany_fx_commands
            (tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, *scope.values(), plan_id, operation, command_id, actor.user_id, digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, plan_id))
        return result

    def _native_contributions(self, source: Mapping[str, Any], income_rates: Mapping[str, Mapping[str, Mapping[str, str]]], *,
                              adjustment: bool = False) -> dict[str, list[dict[str, Any]]]:
        selected = ["adjustment"] if adjustment else list(PARTIES)
        result: dict[str, list[dict[str, Any]]] = {book: [] for book in selected}
        cursor = self.connection.execute("""SELECT l.book,l.posting_effect_id AS effect_id,l.entry_id,p.payload->>'posting_date' AS posting_date,
            e.entity_code,n.line_number,n.account_id,a.account_code,n.debit_minor,n.credit_minor
            FROM reconforge.intercompany_fx_links l JOIN reconforge.intercompany_fx_plans p ON p.tenant_id=l.tenant_id AND p.id=l.plan_id
            JOIN reconforge.finance_posting_effects f ON f.tenant_id=l.tenant_id AND f.id=l.posting_effect_id
            JOIN reconforge.finance_entries e ON e.tenant_id=l.tenant_id AND e.id=l.entry_id
            CROSS JOIN LATERAL jsonb_to_recordset(f.snapshot_json->'lines')
                AS n(line_number INTEGER,account_id TEXT,debit_minor BIGINT,credit_minor BIGINT)
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=n.account_id
            WHERE p.tenant_id=%s AND p.source_id=%s AND p.phase=2 AND l.book=ANY(%s)
            ORDER BY p.sequence,l.book,n.line_number""", (self.tenant_id, source["id"], selected))
        for count, row in enumerate(cursor, 1):
            if count > MAX_EFFECT_LINES:
                fail("Native source statement membership exceeded its declared line bound.")
            book = row["book"]
            value = {key: row[key] for key in ("effect_id", "entry_id", "line_number", "account_id", "account_code", "posting_date", "debit_minor", "credit_minor")}
            value["legal_entity_id"] = source["request"][book]["legal_entity_id"]
            if not adjustment:
                if row["posting_date"] not in income_rates[book]:
                    fail("Every native effect date requires an independently captured reporting historical rate.")
                value["income_rate"] = dict(income_rates[book][row["posting_date"]])
            result[book].append(value)
        return result

    def _prepare(self, source: Mapping[str, Any], request: Mapping[str, Any], *, command_id: str,
                 digest: str, actor: PostingActor) -> dict[str, Any]:
        kind, state, context = request["kind"], self._state(source["id"]), self._context(source)
        if (state["closed"] or state["sequence"] >= MAX_OPERATIONS
                or request["posting_date"] < (state["last_posting_date"] or source["request"]["posting_date"])
                or (kind == "recognize") != (not state["recognized"])
                or self.connection.execute("SELECT 1 FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND source_id=%s AND phase<2",
                    (self.tenant_id, source["id"])).fetchone() is not None):
            fail("Complete the original open, contiguous and date-ordered paired operation.", "intercompany_fx_state_conflict")
        if state["active_revaluation_id"] and kind not in {"reverse_revaluation", "eliminate"}:
            fail("Governed reversal of the exact active closing observation is required before another trade operation.")
        if kind == "recognize":
            equation = recognition_equation(source["request"], context)
        elif kind == "settle":
            if state["settlements"] >= MAX_SETTLEMENTS:
                fail("The paired trade has reached its32-settlement bound.")
            equation = settlement_equation(source, transaction_before_minor=state["transaction_paid_minor"],
                transaction_minor=request["transaction_minor"], posting_date=request["posting_date"], rates=request["rates"], context=context)
        elif kind == "revalue":
            equation = revaluation_equation(source, transaction_before_minor=state["transaction_paid_minor"],
                posting_date=request["posting_date"], rates=request["rates"], context=context)
        elif kind == "reverse_revaluation":
            if request["original_revaluation_id"] != state["active_revaluation_id"]:
                fail("Inverse must bind the exact active original closing valuation.")
            equation = reversal_equation(self._view(request["original_revaluation_id"]))
        elif kind == "eliminate":
            contributions = self._native_contributions(source, request["income_rates"])
            translations = {book: translate_book(source, book, contributions[book], closing_rate=request["closing_rates"][book],
                as_of_date=request["posting_date"], context=context) for book in PARTIES}
            equation = {**elimination_equation(source, translations), "translations": translations}
        else:
            fail("Unsupported versioned paired FX operation.")
        preliminary = {"kind": kind, "equation": equation}
        self._authorize(actor, "prepare", source, preliminary, lock=True)
        identifier = PREFIX[kind] + uuid4().hex
        entries = []
        for book, lines in sorted(equation["books"].items()):
            cfg, original = source["request"][book], None
            number = identifier.upper() + "-" + SUFFIX[book]
            if kind == "reverse_revaluation":
                original = self._view(request["original_revaluation_id"])
                original_entry = next(item for item in original["entries"] if item["book"] == book)
                effect_id = original["posting_effect_ids"][book]
                self._participant = _IntercompanyFxPostingParticipant(self, original_entry["entry_id"], reversal={
                    "source_id": source["id"], "book": book, "workspace_id": source["request"]["workspace_id"],
                    "original_plan_id": original["id"], "original_plan_digest": original["plan_digest"],
                    "original_effect_id": effect_id, "target_number": number,
                    "target_entry_id": platform_id("GLE", source["request"]["workspace_id"], number)})
                try:
                    inverse = self.owner.posting.prepare_reversal(effect_id, command_id="IC2R:" + digest_payload([command_id, book]),
                        entry_number=number, period_id=request["period_ids"][book], posting_date=request["posting_date"],
                        reason=request["reason"], actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                entry_id = inverse["entry_id"]
            else:
                precision = source["policies"][book]["currency_precision"]
                native = self.owner.finance.create_entry(entry_number=number, organization_code=source["request"]["organization_code"],
                    entity_code=cfg["entity_code"], journal_code=cfg["journal_code"], period_id=request["period_ids"][book],
                    posting_date=request["posting_date"], description=request["reason"], workspace=source["request"]["workspace_id"],
                    external_reference="IC2:" + source["id"] + ":" + kind, actor_label=actor.username,
                    lines=[{"account_code": row["account_code"], "debit": exact_minor_text(row["debit_minor"], precision) if row["debit_minor"] else "0",
                            "credit": exact_minor_text(row["credit_minor"], precision) if row["credit_minor"] else "0", "description": request["reason"]} for row in lines])
                entry_id = native["id"]
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
            if any(snapshot["entry"][key] != value for key, value in source["policies"][book].items()):
                fail("Each native book must retain its exact original functional policy.")
            entries.append({"book": book, "entry_id": entry_id, "snapshot": snapshot, "validation_digest": validation_digest(snapshot),
                "reverses_effect_id": original["posting_effect_ids"][book] if original else None})
        scope = self._scope(source)
        plan = {"schema_version": "intercompany-fx-plan-v2", "id": identifier, "source_id": source["id"], **scope,
            "kind": kind, "sequence": state["sequence"], "period_ids": dict(request["period_ids"]),
            "posting_date": request["posting_date"], "reason": request["reason"], "source_digest": source["source_digest"],
            "equation": equation, "entries": entries, "preparer_actor_id": actor.user_id, "command_request": dict(request)}
        plan["plan_digest"] = digest_payload(plan)
        audit, outbox = self._event(source, identifier, "intercompany_fx_prepared", actor, {"plan_digest": plan["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.intercompany_fx_plans
            (tenant_id,id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,source_id,sequence,kind,phase,payload,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""",
            (self.tenant_id, identifier, *scope.values(), source["id"], state["sequence"], kind, canonical_json(plan), audit, outbox))
        return self._remember(source, identifier, "prepare", command_id, actor, digest, request)

    def prepare(self, request: IntercompanyFxPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        cfg = request.payload()
        envelope = {"kind": "recognize", "posting_date": cfg["posting_date"], "reason": cfg["reason"],
            "period_ids": {book: cfg[book]["period_id"] for book in BOOKS}, "original_request": cfg}
        with self.owner._transaction():
            self._authorize(actor, "prepare", cfg)
            digest, replay = self._command(cfg, "prepare", command_id, actor, envelope)
            self._parents(cfg, envelope["period_ids"], require_open=replay is None)
            if replay is not None:
                source = self._peek("source", replay["source_id"], lock=True)
                self._authorize(actor, "prepare", source, replay)
                self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            accounts = self._account_maps(cfg)
            store = FinancePolicyStore(self.connection, tenant_id=self.tenant_id)
            for currency in sorted({cfg["transaction_currency_code"], *(cfg[book]["currency_code"] for book in BOOKS)}):
                master = self.connection.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE", (self.tenant_id, currency)).fetchone()
                if master is None:
                    fail("Each transaction, functional and reporting currency requires its active exact master.")
                _, context = store.capture(workspace_id=cfg["workspace_id"], currency_code=currency,
                    minor_units=master["minor_units"], actor_label=actor.username)
            initial = recognition_equation(cfg, context)
            source = {"schema_version": "intercompany-fx-source-v2", "id": "IC2S-" + uuid4().hex,
                "request": cfg, "policies": initial["policies"], "original_positions": initial["positions"],
                "native_accounts": accounts, "preparer_actor_id": actor.user_id}
            source["source_digest"] = digest_payload(source)
            self._authorize(actor, "prepare", source)
            self.connection.execute("""INSERT INTO reconforge.intercompany_fx_sources
                (tenant_id,id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,reference,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (self.tenant_id, source["id"], *self._scope(source).values(), cfg["reference"], canonical_json(source)))
            return self._prepare(source, envelope, command_id=command_id, digest=digest, actor=actor)

    def _progress(self, source_id: str, request: dict[str, Any], *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {**request, "source_id": text(source_id, "source_id"), "posting_date": canonical_day(request["posting_date"], "posting_date"),
                   "reason": text(request["reason"], "reason", maximum=500)}
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "prepare", source)
            digest, replay = self._command(source, "prepare", command_id, actor, request)
            self._parents(source["request"], request["period_ids"], require_open=replay is None)
            source = self._peek("source", source_id, lock=True)
            self._authorize(actor, "prepare", source, replay, lock=True)
            if replay is not None:
                self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            return self._prepare(source, request, command_id=command_id, digest=digest, actor=actor)

    def prepare_settlement(self, source_id: str, *, transaction_minor: int, rates: Mapping[str, HistoricalRate],
                           period_ids: Mapping[str, str], posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "settle", "transaction_minor": transaction_minor,
            "rates": {book: rates[book].payload(posting_date) for book in PARTIES}, "period_ids": dict(period_ids),
            "posting_date": posting_date, "reason": reason}, command_id=command_id, actor=actor)

    def prepare_revaluation(self, source_id: str, *, rates: Mapping[str, HistoricalRate], period_ids: Mapping[str, str],
                            posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "revalue", "rates": {book: rates[book].payload(posting_date) for book in PARTIES},
            "period_ids": dict(period_ids), "posting_date": posting_date, "reason": reason}, command_id=command_id, actor=actor)

    def prepare_revaluation_reversal(self, source_id: str, *, original_revaluation_id: str, period_ids: Mapping[str, str],
                                     posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._progress(source_id, {"kind": "reverse_revaluation", "original_revaluation_id": original_revaluation_id,
            "period_ids": dict(period_ids), "posting_date": posting_date, "reason": reason}, command_id=command_id, actor=actor)

    def prepare_elimination(self, source_id: str, *, closing_rates: Mapping[str, HistoricalRate],
                            income_rates: Mapping[str, Mapping[str, HistoricalRate]], period_ids: Mapping[str, str],
                            posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        if set(income_rates) != set(PARTIES) or any(not 1 <= len(income_rates[book]) <= MAX_OPERATIONS for book in PARTIES):
            fail("Translation needs a bounded complete per-party historical date/rate map.")
        return self._progress(source_id, {"kind": "eliminate", "closing_rates": {book: closing_rates[book].payload(posting_date) for book in PARTIES},
            "income_rates": {book: {canonical_day(day, "income date"): retained.payload(day) for day, retained in income_rates[book].items()} for book in PARTIES},
            "period_ids": dict(period_ids), "posting_date": posting_date, "reason": reason}, command_id=command_id, actor=actor)

    def _phase(self, operation: str, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": text(plan_id, "plan_id"), "expected_plan_digest": expected_plan_digest,
                   "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            initial = self._peek("plan", plan_id)
            source = self._peek("source", initial["source_id"])
            self._authorize(actor, operation, source, initial)
            digest, replay = self._command(source, operation, command_id, actor, request)
            self._parents(source["request"], initial["period_ids"], require_open=replay is None)
            source = self._peek("source", source["id"], lock=True)
            plan = self._peek("plan", plan_id, lock=True)
            self._authorize(actor, operation, source, plan, lock=True)
            if replay is not None:
                self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, plan_id))
                return replay
            state = self._state(source["id"])
            if (plan["plan_digest"] != expected_plan_digest or plan["phase"] != (0 if operation == "review" else 1)
                    or plan["sequence"] != state["sequence"] or state["closed"] or actor.user_id == plan["preparer_actor_id"]):
                fail("Retain the current whole-source phase/digest and independent maker/checker identity.", "intercompany_fx_state_conflict")
            if operation == "review":
                for entry in sorted(plan["entries"], key=lambda row: row["entry_id"]):
                    self.owner.finance.validate_entry(entry["entry_id"], reason=request["reason"], actor_label=actor.username)
                audit, outbox = self._event(source, plan_id, "intercompany_fx_reviewed", actor, {"plan_digest": plan["plan_digest"]})
                self.connection.execute("INSERT INTO reconforge.intercompany_fx_reviews(tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)",
                    (self.tenant_id, plan_id, actor.user_id, request["reason"], audit, outbox))
            else:
                if actor.user_id == self._view(plan_id)["reviewer_actor_id"]:
                    fail("Publication requires a third independently authorized human.")
                for entry in sorted(plan["entries"], key=lambda row: row["entry_id"]):
                    self._participant = _IntercompanyFxPostingParticipant(self, entry["entry_id"])
                    try:
                        effect = self.owner.posting.post(entry["entry_id"], command_id="IC2:" + entry["book"] + ":" + digest,
                            expected_validation_digest=entry["validation_digest"], reason=request["reason"], actor=actor, _source_owner=self._participant)
                    finally:
                        self._participant = None
                    self.connection.execute("INSERT INTO reconforge.intercompany_fx_links(tenant_id,plan_id,book,entry_id,posting_effect_id,posted_actor_id,reason) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (self.tenant_id, plan_id, entry["book"], entry["entry_id"], effect["id"], actor.user_id, request["reason"]))
                audit, outbox = self._event(source, plan_id, "intercompany_fx_posted", actor, {"plan_digest": plan["plan_digest"]})
                self.connection.execute("INSERT INTO reconforge.intercompany_fx_post_evidence(tenant_id,plan_id,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s)",
                    (self.tenant_id, plan_id, audit, outbox))
            self.connection.execute("UPDATE reconforge.intercompany_fx_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan_id))
            return self._remember(source, plan_id, operation, command_id, actor, digest, request)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("review", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("post", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id, share=True)
            self._authorize(actor, "read", source, lock=True)
            plans = [self._view(row["id"]) for row in records(self.connection.execute(
                "SELECT id FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND source_id=%s ORDER BY sequence LIMIT 65", (self.tenant_id, source_id)))]
            for plan in plans:
                self._authorize(actor, "read", source, plan, lock=True)
            return {**source, "state": self._state(source_id), "plans": plans}

    def list_sources(self, *, workspace_id: str, organization_id: str, after: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            rows = records(self.connection.execute("""SELECT id,payload FROM reconforge.intercompany_fx_sources
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND id>%s ORDER BY id LIMIT 51""",
                (self.tenant_id, text(workspace_id, "workspace_id"), text(organization_id, "organization_id"), after)))
            result = []
            for row in rows[:50]:
                source = row["payload"]
                self._authorize(actor, "read", source)
                request = source["request"]
                result.append({"id": row["id"], "reference": request["reference"], "posting_date": request["posting_date"],
                    "transaction_currency_code": request["transaction_currency_code"], "transaction_minor": request["transaction_minor"],
                    "seller_entity_id": request["seller"]["legal_entity_id"], "buyer_entity_id": request["buyer"]["legal_entity_id"],
                    "adjustment_entity_id": request["adjustment"]["legal_entity_id"], "source_digest": source["source_digest"],
                    "state": self._state(row["id"])})
            return {"items": result, "next_cursor": rows[49]["id"] if len(rows) > 50 else None}

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._peek("plan", plan_id)
            source = self._peek("source", plan["source_id"])
            self._authorize(actor, "read", source, plan)
            return self._view(plan_id)

    def evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self.get_plan(plan_id, actor=actor)
            source = self._peek("source", plan["source_id"])
            effects = records(self.connection.execute("""SELECT f.id,f.entry_id,f.validation_digest,f.snapshot_json AS snapshot,f.posted_actor_id,
                f.audit_event_id,f.outbox_event_id,f.reverses_effect_id FROM reconforge.finance_posting_effects f
                JOIN reconforge.intercompany_fx_links l ON l.tenant_id=f.tenant_id AND l.posting_effect_id=f.id WHERE l.tenant_id=%s AND l.plan_id=%s ORDER BY l.book""",
                (self.tenant_id, plan_id)))
            phases = records(self.connection.execute("""SELECT a.action,a.actor_user_id AS actor_id,a.id AS audit_event_id,
                o.event_id AS outbox_event_id,a.metadata_json FROM reconforge.domain_audit_events a
                JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id AND o.aggregate_type=a.object_type
                AND o.aggregate_id=a.object_id AND o.event_type=a.action
                WHERE a.tenant_id=%s AND a.object_type='operational_finance' AND a.object_id=%s ORDER BY a.sequence""", (self.tenant_id, plan_id)))
            return {"schema_version": "intercompany-fx-native-evidence-v2", "source": source, "plan": plan,
                "canonical_source_json": canonical_json({key: value for key, value in source.items() if key != "source_digest"}),
                "canonical_plan_json": canonical_json({key: value for key, value in plan.items() if key not in {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}}),
                "canonical_snapshot_jsons": [canonical_json(entry["snapshot"]) for entry in plan["entries"]],
                "native_effects": effects, "phases": phases}

    def report(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self.get_source(source_id, actor=actor)
            self._authorize(actor, "read", source)
            rows = records(self.connection.execute("SELECT id FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND source_id=%s AND kind='eliminate' AND phase=2", (self.tenant_id, source_id)))
            if len(rows) != 1:
                fail("A final management statement requires its whole reviewed native elimination.")
            plan = self.get_plan(rows[0]["id"], actor=actor)
            self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, plan["id"]))
            adjustment = self._native_contributions(source, {}, adjustment=True)["adjustment"]
            report = group_report(source, plan["equation"]["translations"], adjustment, plan_digest=plan["plan_digest"])
            result = {**report, "source_effect_ids": sorted({effect for ids in plan["equation"]["native_membership"].values() for effect in ids}),
                "native_adjustment_effect_ids": sorted({row["effect_id"] for row in adjustment})}
            result.pop("report_digest", None)
            reporting_amount = max([abs(result["cash_net_movement_minor"]), abs(result["cta_minor"]),
                *(abs(row["balance_minor"]) for row in result["trial_balance"]),
                *(abs(value) for key, value in result["balance_sheet"].items() if key.endswith("_minor")),
                *(abs(value) for value in result["income_statement"].values())])
            self._authorize_reporting(actor, "read", source, reporting_amount)
            return {**result, "report_digest": digest_payload(result)}
