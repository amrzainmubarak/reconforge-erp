"""Source-owned project and intercompany commands composed over Finance Core."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Literal

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.intercompany_elimination import (
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
)
from reconforge.domain.models import utc_now_text
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_enterprise_finance_bridge_schema import (
    DOWNGRADE_SQL as POSTGRES_ENTERPRISE_FINANCE_BRIDGE_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_enterprise_finance_bridge_schema import (
    UPGRADE_SQL as POSTGRES_ENTERPRISE_FINANCE_BRIDGE_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository

SourceKind = Literal["ProjectMilestone", "ProfitInStock"]
SCOPE_FIELDS = ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code")
__all__ = ["PostgresEnterpriseFinanceBridge", "POSTGRES_ENTERPRISE_FINANCE_BRIDGE_UPGRADE_SQL", "POSTGRES_ENTERPRISE_FINANCE_BRIDGE_DOWNGRADE_SQL"]


def fail(message: str, code: str = "enterprise_finance_invalid") -> None:
    raise FinancePostingError(code, message)


class _EnterpriseFinancePostingParticipant:
    """Finite live capability, bound to one source owner, connection and entry."""

    def __init__(self, owner: PostgresEnterpriseFinanceBridge, binding: Mapping[str, Any]) -> None:
        self.owner, self.binding = owner, binding

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.binding["entry_id"] == entry_id)

    def admits_reversal(self, connection: Any, tenant_id: str, entry_id: str, effect_id: str, number: str) -> bool:
        return (self.admits(connection, tenant_id, entry_id) and self.binding["phase"] == "Posted"
                and self.binding["effect_id"] == effect_id and number.startswith(("PMIR1-", "PISR1-")))


class PostgresEnterpriseFinanceBridge:
    """Prepare, independently review, publish and reverse immutable native sources.

    The bridge owns no ledger. Every accounting entry, validation and effect is
    produced by the existing Finance Core/Finance Posting repositories on the
    same caller-owned transaction and connection.
    """

    def __init__(self, connection: Any, tenant_id: str, *, allowed_kind: SourceKind | None = None) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.finance, self.posting = self.owner.finance, self.owner.posting
        self.policy = FinancePolicyStore(connection, tenant_id=tenant_id)
        self._participant: _EnterpriseFinancePostingParticipant | None = None
        self.allowed_kind = allowed_kind

    def _authorize(self, actor: PostingActor, action: str, value: Mapping[str, Any]) -> None:
        kind = value.get("origin_source_kind", value.get("source_kind"))
        finance = {"read": "read", "prepare": "manage", "review": "validate", "post": "post", "reverse": "reverse"}[action]
        permissions = {"finance_core." + finance}
        if action == "reverse":
            permissions.add("finance_core.manage")
        if value.get("source_kind") == "Reversal" and action in {"review", "post"}:
            permissions.add("finance_core.reverse")
        if kind == "ProjectMilestone":
            project = {"read": "read", "prepare": "manage", "review": "review", "post": "post", "reverse": "manage"}[action]
            permissions.add("project_time_billing." + project)
        for permission in sorted(permissions):
            self.owner._actor(actor, permission, value, mutation=action != "read")
            # This existing native admission holds the actual persisted role /
            # hierarchy grants through commit, including concurrent revocation.
            self.connection.execute("SELECT reconforge.hc_actor(%s,%s,%s,%s,%s,%s)", (
                self.tenant_id, value["workspace_id"], value["organization_id"], value["legal_entity_id"], actor.user_id, permission))

    def _command(self, scope: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "command_id", maximum=140)
        digest = digest_payload({"operation": action, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "enterprise-finance-command", command_id]),))
        prior = records(self.connection.execute("""SELECT operation,actor_id,request_digest,response_json
            FROM reconforge.enterprise_finance_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""",
            (self.tenant_id, scope["workspace_id"], command_id)))
        if prior:
            item = prior[0]
            if (item["operation"], item["actor_id"], item["request_digest"]) != (action, actor.user_id, digest):
                fail("Command belongs to another actor or exact request.", "enterprise_finance_command_conflict")
            return digest, dict(item["response_json"])
        return digest, None

    def _remember(self, row: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                  digest: str) -> dict[str, Any]:
        response = self._view(row)
        self.connection.execute("""INSERT INTO reconforge.enterprise_finance_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,binding_id,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""", (
            self.tenant_id, row["workspace_id"], row["organization_id"], row["legal_entity_id"], command_id,
            action, actor.user_id, digest, row["id"], canonical_json(response)))
        return response

    def _source_lock(self, value: Mapping[str, Any]) -> None:
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (canonical_json([
            self.tenant_id, value["workspace_id"], "enterprise-finance-source",
            value.get("origin_source_kind", value["source_kind"]), value.get("origin_source_id", value["source_id"])]),))

    def _row(self, binding_id: str, *, lock: bool = False) -> dict[str, Any]:
        statement = """SELECT * FROM reconforge.enterprise_finance_bindings WHERE tenant_id=%s AND id=%s"""
        rows = records(self.connection.execute("".join((statement, " FOR UPDATE" if lock else "")),
            (self.tenant_id, text(binding_id, "binding_id"))))
        if not rows:
            fail("Financial source binding was not found in the authorized scope.", "enterprise_finance_not_found")
        if self.allowed_kind is not None and rows[0]["payload"]["origin_source_kind"] != self.allowed_kind:
            fail("Financial source binding was not found for this application.", "enterprise_finance_not_found")
        return rows[0]

    @staticmethod
    def _view(row: Mapping[str, Any]) -> dict[str, Any]:
        payload = row["payload"]
        return {"binding_id": row["id"], "source_kind": row["source_kind"], "source_id": row["source_id"],
            "phase": row["phase"], "entry_id": row["entry_id"], "source_digest": row["source_digest"],
            "validation_digest": payload["validation_digest"], "amount_minor": str(payload["amount_minor"]),
            "currency_code": payload["currency_code"], "currency_precision": payload["currency_precision"],
            "monetary_policy": payload["monetary_policy"], "preparer_id": row["preparer_id"],
            "reviewer_id": row["reviewer_id"], "poster_id": row["poster_id"], "effect_id": row["effect_id"],
            "reverses_binding_id": row["reverses_binding_id"]}

    def _source(self, kind: SourceKind, source_id: str, scope: Mapping[str, Any]) -> dict[str, Any]:
        params = (self.tenant_id, scope["workspace_id"], source_id)
        if kind == "ProjectMilestone":
            invoices = records(self.connection.execute("""SELECT * FROM reconforge.project_milestone_invoices
                WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s FOR UPDATE""", params))
            if not invoices:
                fail("A persisted milestone invoice is required.", "enterprise_finance_source_missing")
            invoice = invoices[0]
            milestones = records(self.connection.execute("""SELECT * FROM reconforge.project_milestones
                WHERE tenant_id=%s AND workspace_id=%s AND milestone_id=%s FOR SHARE""",
                (self.tenant_id, scope["workspace_id"], invoice["milestone_id"])))
            if not milestones:
                fail("The original milestone is missing.")
            milestone = milestones[0]
            if (milestone["status"] != "billed" or not milestone["verified_by"] or not milestone["verified_at"]
                    or (invoice["project_id"], invoice["currency"], invoice["billed_amount_minor"])
                    != (milestone["project_id"], milestone["currency"], milestone["milestone_amount_minor"])):
                fail("Invoice must retain the exact independently verified milestone amount and currency.")
            source = {"invoice": {key: invoice[key] for key in ("invoice_id", "project_id", "milestone_id", "customer_code",
                "billed_amount_minor", "currency", "issued_at", "gl_debit_account", "gl_credit_account", "organization_id", "legal_entity_id")},
                "milestone": {key: milestone[key] for key in ("milestone_id", "project_id", "contract_line_id", "title", "milestone_amount_minor",
                    "currency", "due_date", "status", "verified_by", "verified_at", "organization_id", "legal_entity_id")}}
        elif kind == "ProfitInStock":
            eliminations = records(self.connection.execute("""SELECT * FROM reconforge.intercompany_profit_in_stock_eliminations
                WHERE tenant_id=%s AND workspace_id=%s AND elimination_id=%s FOR UPDATE""", params))
            if not eliminations:
                fail("A persisted profit-in-stock elimination is required.", "enterprise_finance_source_missing")
            elimination = eliminations[0]
            rules = records(self.connection.execute("""SELECT * FROM reconforge.intercompany_profit_in_stock_rules
                WHERE tenant_id=%s AND workspace_id=%s AND rule_id=%s FOR SHARE""",
                (self.tenant_id, scope["workspace_id"], elimination["rule_id"])))
            if not rules:
                fail("The original profit-in-stock rule is missing.")
            rule = rules[0]
            raw_rule = {key: rule[key] for key in ("rule_id", "selling_entity", "buying_entity", "inventory_item_code",
                "margin_basis_points", "ending_inventory_cost_minor", "nci_share_basis_points", "currency")}
            expected = calculate_profit_in_stock_elimination(IntercompanyProfitInStockRule(**raw_rule),
                debit_account=elimination["debit_account"], credit_account=elimination["credit_account"])
            if any(elimination[key] != expected.to_dict()[key] for key in expected.to_dict()):
                fail("Stored elimination does not conserve its original rule and parent/NCI calculation.")
            source = {"rule": {**raw_rule, "organization_id": rule["organization_id"], "legal_entity_id": rule["legal_entity_id"]},
                "elimination": {**expected.to_dict(), "organization_id": elimination["organization_id"], "legal_entity_id": elimination["legal_entity_id"]}}
        else:
            fail("Unsupported native financial source kind.")
        for component in source.values():
            if (not component["organization_id"] or not component["legal_entity_id"]
                    or component["organization_id"] != scope["organization_id"] or component["legal_entity_id"] != scope["legal_entity_id"]):
                fail("Original source hierarchy is missing or differs; no historical scope is inferred.", "enterprise_finance_source_scope")
        return source

    @staticmethod
    def _money_source(kind: SourceKind, source: Mapping[str, Any]) -> tuple[int, str, str, str]:
        row = source["invoice"] if kind == "ProjectMilestone" else source["elimination"]
        amount = row["billed_amount_minor"] if kind == "ProjectMilestone" else row["unrealized_profit_minor"]
        if type(amount) is not int or not 1 <= amount <= 9_000_000_000_000_000_000:
            fail("Financial publication requires bounded positive exact minor units.")
        return amount, row["currency"], row["gl_debit_account"] if kind == "ProjectMilestone" else row["debit_account"], row["gl_credit_account"] if kind == "ProjectMilestone" else row["credit_account"]

    def _event(self, row: Mapping[str, Any], action: str, actor: PostingActor) -> None:
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="enterprise_finance_binding", object_id=row["id"],
            action="enterprise_finance_" + action, after_hash=row["source_digest"], metadata={
                "schema_version": 1, "workspace_id": row["workspace_id"], "source_kind": row["source_kind"],
                "source_id": row["source_id"], "entry_id": row["entry_id"], "effect_id": row["effect_id"],
                "source_digest": row["source_digest"], "phase": row["phase"]})

    @contextmanager
    def _admission(self, row: Mapping[str, Any]) -> Iterator[_EnterpriseFinancePostingParticipant]:
        participant = _EnterpriseFinancePostingParticipant(self, row)
        previous = self._participant
        self._participant = participant
        self.connection.execute("SELECT set_config('app.enterprise_finance_binding',%s,true)", (row["id"],))
        try:
            yield participant
        finally:
            self._participant = previous
            self.connection.execute("SELECT set_config('app.enterprise_finance_binding',%s,true)", ("" if previous is None else previous.binding["id"],))

    def _verify(self, row: Mapping[str, Any]) -> None:
        payload = row["payload"]
        kind = payload["origin_source_kind"]
        source = self._source(kind, payload["origin_source_id"], payload)
        if source != payload["source_snapshot"] or digest_payload(source) != row["source_digest"]:
            fail("The original persisted financial source has changed.", "enterprise_finance_source_changed")
        entry = posting_entry(self.connection, self.tenant_id, row["entry_id"])
        snapshot = posting_snapshot(self.connection, self.tenant_id, entry)
        expected_reference = payload["reverses_effect_id"] if row["source_kind"] == "Reversal" else row["id"]
        if (validation_digest(snapshot) != payload["validation_digest"] or entry["external_reference"] != expected_reference
                or any(row[key] != payload[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))):
            fail("Canonical ledger contents differ from the sealed source.", "enterprise_finance_source_changed")
        if row["source_kind"] != "Reversal":
            table = "project_milestone_invoices" if kind == "ProjectMilestone" else "intercompany_profit_in_stock_eliminations"
            statement = ("SELECT finance_entry_id FROM reconforge.project_milestone_invoices WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s"
                if table == "project_milestone_invoices" else
                "SELECT finance_entry_id FROM reconforge.intercompany_profit_in_stock_eliminations WHERE tenant_id=%s AND workspace_id=%s AND elimination_id=%s")
            linked = self.connection.execute(statement, (self.tenant_id, row["workspace_id"], row["source_id"])).fetchone()
            if not linked or linked[0] != row["entry_id"]:
                fail("Original financial source must retain its canonical entry link.")

    def prepare(self, kind: SourceKind, source_id: str, *, scope: Mapping[str, str], period_id: str,
                posting_date: str, journal_code: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        if kind not in {"ProjectMilestone", "ProfitInStock"}:
            fail("Unsupported native financial source kind.")
        request: dict[str, Any] = {key: text(scope.get(key), key) for key in SCOPE_FIELDS}
        request.update(source_kind=kind, source_id=text(source_id, "source_id"),
            period_id=text(period_id, "period_id"), posting_date=text(posting_date, "posting_date"), journal_code=text(journal_code, "journal_code"))
        with self.owner._transaction():
            self._authorize(actor, "prepare", request)
            request_digest, replay = self._command(request, "prepare", command_id, actor, request)
            if replay is not None:
                self._authorize(actor, "prepare", self._row(replay["binding_id"])["payload"])
                return replay
            self.posting._period(period_id, request["workspace_id"], posting_date)
            self.policy.lock_binding(request["workspace_id"])
            self._source_lock(request)
            source = self._source(kind, source_id, request)
            if kind == "ProjectMilestone" and source["invoice"]["issued_at"][:10] != posting_date:
                fail("Posting date must retain the original invoice business date.")
            amount, currency, debit, credit = self._money_source(kind, source)
            currency_row = self.connection.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE", (self.tenant_id, currency)).fetchone()
            if not currency_row:
                fail("The original currency requires an active canonical registry reference.")
            policy, _ = self.policy.capture(workspace_id=request["workspace_id"], currency_code=currency,
                minor_units=int(currency_row[0]), actor_label=actor.username)
            scope_value = {**request, "amount_minor": amount, "currency_precision": policy.precision}
            self._authorize(actor, "prepare", scope_value)
            prior = records(self.connection.execute("""SELECT * FROM reconforge.enterprise_finance_bindings
                WHERE tenant_id=%s AND workspace_id=%s AND source_kind=%s AND source_id=%s FOR UPDATE""",
                (self.tenant_id, request["workspace_id"], kind, source_id)))
            if prior:
                old = prior[0]
                if old["payload"]["prepare_request"] != request or old["preparer_id"] != actor.user_id:
                    fail("The source already belongs to a different immutable preparation.", "enterprise_finance_source_conflict")
                self._verify(old)
                return self._remember(old, "prepare", command_id, actor, request_digest)
            source_digest = digest_payload(source)
            identifier = "EFB1-" + digest_payload([self.tenant_id, request["workspace_id"], kind, source_id])[:32]
            number = ("PMI1-" if kind == "ProjectMilestone" else "PIS1-") + identifier[5:]
            amount_text = exact_minor_text(amount, policy.precision)
            entry = self.finance.create_entry(entry_number=number, organization_code=request["organization_code"],
                entity_code=request["entity_code"], period_id=period_id, journal_code=journal_code, posting_date=posting_date,
                description="Original " + kind + " financial source", lines=[
                    {"account_code": debit, "debit": amount_text, "credit": "0", "description": kind + " debit"},
                    {"account_code": credit, "debit": "0", "credit": amount_text, "description": kind + " credit"}],
                workspace=request["workspace_id"], external_reference=identifier, actor_label=actor.username)
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if snapshot["entry"]["currency_code"] != currency or snapshot["entry"]["currency_precision"] != policy.precision:
                fail("Source currency and canonical journal currency policy differ.")
            payload = {"schema_version": "enterprise-finance-source-v1", **request, "origin_source_kind": kind,
                "origin_source_id": source_id, "prepare_request": request, "source_snapshot": source,
                "amount_minor": amount, "currency_code": currency, "currency_precision": policy.precision,
                "monetary_policy": {"currency_code": currency, **policy.metadata()}, "snapshot": snapshot,
                "validation_digest": validation_digest(snapshot)}
            statement = ("UPDATE reconforge.project_milestone_invoices SET finance_entry_id=%s WHERE tenant_id=%s AND workspace_id=%s AND invoice_id=%s AND finance_entry_id IS NULL"
                if kind == "ProjectMilestone" else
                "UPDATE reconforge.intercompany_profit_in_stock_eliminations SET finance_entry_id=%s WHERE tenant_id=%s AND workspace_id=%s AND elimination_id=%s AND finance_entry_id IS NULL")
            if self.connection.execute(statement, (entry["id"], self.tenant_id, request["workspace_id"], source_id)).rowcount != 1:
                fail("Source is already linked or changed concurrently.", "enterprise_finance_source_conflict")
            self.connection.execute("""INSERT INTO reconforge.enterprise_finance_bindings
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_kind,source_id,source_digest,payload,entry_id,phase,preparer_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'Draft',%s,%s)""", (
                self.tenant_id, identifier, request["workspace_id"], request["organization_id"], request["legal_entity_id"], kind,
                source_id, source_digest, canonical_json(payload), entry["id"], actor.user_id, utc_now_text()))
            row = self._row(identifier)
            self._event(row, "prepared", actor)
            return self._remember(row, "prepare", command_id, actor, request_digest)

    def get(self, binding_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            row = self._row(binding_id)
            self._authorize(actor, "read", row["payload"])
            self._source_lock(row["payload"])
            row = self._row(binding_id)
            self._verify(row)
            return self._view(row)

    def review(self, binding_id: str, *, expected_source_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"binding_id": binding_id, "expected_source_digest": expected_source_digest}
        with self.owner._transaction():
            preview = self._row(binding_id)
            self._authorize(actor, "review", preview["payload"])
            digest, replay = self._command(preview, "review", command_id, actor, request)
            if replay is not None:
                return replay
            self.posting._period(preview["payload"]["period_id"], preview["workspace_id"], preview["payload"]["posting_date"])
            self._source_lock(preview["payload"])
            row = self._row(binding_id, lock=True)
            if row["phase"] != "Draft" or row["preparer_id"] == actor.user_id or row["source_digest"] != expected_source_digest:
                fail("Review requires an unchanged source and a distinct current human.", "enterprise_finance_review_denied")
            self._verify(row)
            with self._admission(row):
                self.finance.validate_entry(row["entry_id"], reason="Independent review of original financial source", actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.enterprise_finance_bindings SET phase='Reviewed',reviewer_id=%s WHERE tenant_id=%s AND id=%s AND phase='Draft'", (actor.user_id, self.tenant_id, binding_id))
            row = self._row(binding_id)
            self._event(row, "reviewed", actor)
            return self._remember(row, "review", command_id, actor, digest)

    def post(self, binding_id: str, *, expected_source_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"binding_id": binding_id, "expected_source_digest": expected_source_digest}
        with self.owner._transaction():
            preview = self._row(binding_id)
            self._authorize(actor, "post", preview["payload"])
            digest, replay = self._command(preview, "post", command_id, actor, request)
            if replay is not None:
                return replay
            self.posting._period(preview["payload"]["period_id"], preview["workspace_id"], preview["payload"]["posting_date"])
            self._source_lock(preview["payload"])
            row = self._row(binding_id, lock=True)
            if (row["phase"] != "Reviewed" or actor.user_id in {row["preparer_id"], row["reviewer_id"]}
                    or row["source_digest"] != expected_source_digest):
                fail("Posting requires the unchanged reviewed source and a third distinct human.", "enterprise_finance_post_denied")
            self._verify(row)
            with self._admission(row) as participant:
                effect = self.posting.post(row["entry_id"], command_id="EFB1:" + command_id,
                    expected_validation_digest=row["payload"]["validation_digest"], reason="Original reviewed financial source",
                    actor=actor, _source_owner=participant)
                self.connection.execute("UPDATE reconforge.enterprise_finance_bindings SET phase='Posted',poster_id=%s,effect_id=%s WHERE tenant_id=%s AND id=%s AND phase='Reviewed'", (actor.user_id, effect["id"], self.tenant_id, binding_id))
            row = self._row(binding_id)
            self._event(row, "posted", actor)
            return self._remember(row, "post", command_id, actor, digest)

    def reverse(self, binding_id: str, *, expected_source_digest: str, period_id: str, posting_date: str,
                reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"binding_id": binding_id, "expected_source_digest": expected_source_digest,
            "period_id": period_id, "posting_date": posting_date, "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            preview = self._row(binding_id)
            self._authorize(actor, "reverse", preview["payload"])
            digest, replay = self._command(preview, "reverse", command_id, actor, request)
            if replay is not None:
                return replay
            self.posting._period(period_id, preview["workspace_id"], posting_date)
            self._source_lock(preview["payload"])
            original = self._row(binding_id, lock=True)
            if original["phase"] != "Posted" or original["source_kind"] == "Reversal" or original["source_digest"] != expected_source_digest:
                fail("Only an unchanged posted original source can prepare a full inverse.")
            self._verify(original)
            if self.connection.execute("SELECT 1 FROM reconforge.enterprise_finance_bindings WHERE tenant_id=%s AND reverses_binding_id=%s", (self.tenant_id, binding_id)).fetchone():
                fail("A full inverse already exists for the original source.", "enterprise_finance_source_conflict")
            identifier = "EFB1R-" + digest_payload([self.tenant_id, binding_id])[:32]
            number = ("PMIR1-" if original["source_kind"] == "ProjectMilestone" else "PISR1-") + identifier[6:]
            with self._admission(original) as participant:
                inverse = self.posting.prepare_reversal(original["effect_id"], command_id="EFB1R:" + command_id,
                    entry_number=number, period_id=period_id, posting_date=posting_date,
                    reason=request["reason"], actor=actor, _source_owner=participant)
            # prepare_reversal deliberately preserves canonical reversal provenance;
            # external_reference remains the original effect, and is sealed below.
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, inverse["entry_id"]))
            payload = {**original["payload"], "source_kind": "Reversal", "source_id": binding_id,
                "period_id": period_id, "posting_date": posting_date, "snapshot": snapshot,
                "validation_digest": validation_digest(snapshot), "reverses_effect_id": original["effect_id"]}
            self.connection.execute("""INSERT INTO reconforge.enterprise_finance_bindings
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_kind,source_id,source_digest,payload,entry_id,phase,preparer_id,reverses_binding_id,created_at)
                VALUES(%s,%s,%s,%s,%s,'Reversal',%s,%s,%s::jsonb,%s,'Draft',%s,%s,%s)""", (
                self.tenant_id, identifier, original["workspace_id"], original["organization_id"], original["legal_entity_id"],
                binding_id, original["source_digest"], canonical_json(payload), inverse["entry_id"], actor.user_id, binding_id, utc_now_text()))
            row = self._row(identifier)
            self._event(row, "reversal_prepared", actor)
            return self._remember(row, "reverse", command_id, actor, digest)
