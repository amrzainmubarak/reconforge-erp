"""Read-only captured source membership on the existing IC2 native owner."""

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_digest, evidence_size
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_cashflow import SourceCashOpening, classified_cashflow, refuse
from reconforge.domain.intercompany_fx import MAX_OPERATIONS
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_intercompany_fx import BOOKS, PostgresIntercompanyFxRepository


def primitive(value: Any) -> Any:
    """Native SQL date/time columns become explicit text; amounts stay integers."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if type(value) is dict:
        return {key: primitive(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [primitive(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    refuse("Original cash-flow evidence requires exact native primitives.")


class PostgresIntercompanyCashflowRepository:
    """One source SHARE lock retains the complete immutable owner population."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.ic2 = PostgresIntercompanyFxRepository(connection, tenant_id)

    def evidence(self, source_id: str, *, opening: SourceCashOpening, actor: PostingActor) -> dict[str, Any]:
        with self.ic2.owner._transaction():
            current = self.ic2.get_source(source_id, actor=actor)
            if not current["state"]["closed"] or not 2 <= len(current["plans"]) <= MAX_OPERATIONS:
                refuse("A complete posted IC2 source and native elimination are required.")
            source = {key: value for key, value in current.items() if key not in {"plans", "state"}}
            stages = []
            for plan in current["plans"]:
                if plan["phase"] != 2:
                    refuse("Unposted source operations cannot be included in a native cash-flow view.")
                self.connection.execute("SELECT reconforge.icfx_close(%s,%s)", (self.tenant_id, plan["id"]))
                stage = self.ic2.evidence(plan["id"], actor=actor)
                stages.append(stage)
                for entry in stage["plan"]["entries"]:
                    native = posting_entry(self.connection, self.tenant_id, entry["entry_id"])
                    # Core keeps the reviewed header Validated; the immutable
                    # posting effect and source phase are its posting evidence.
                    if native["status"] != "Validated":
                        refuse("Actual native GL status differs from its original posted source.")
                    if native["validator_actor_id"] != plan["reviewer_actor_id"]:
                        refuse("Actual native GL reviewer differs from its original reviewed source.")
                    if posting_snapshot(self.connection, self.tenant_id, native) != entry["snapshot"]:
                        refuse("Actual native GL snapshot differs from its original reviewed source effect.")
            report = self.ic2.report(source_id, actor=actor)
            context = self.ic2._context(source)
            result = classified_cashflow(source, report, stages, opening=opening, context=context)
            plan_ids = [stage["plan"]["id"] for stage in stages]
            effect_ids = result["source_effect_ids"] + result["native_adjustment_effect_ids"]
            effects = records(self.connection.execute("""SELECT * FROM reconforge.finance_posting_effects
                WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id""", (self.tenant_id, effect_ids)))
            if len(effects) != len(effect_ids):
                refuse("The complete original native effect population is required.")
            effect_by_id = {effect["id"]: effect for effect in effects}
            for stage in stages:
                for book, effect_id in stage["plan"]["posting_effect_ids"].items():
                    effect = effect_by_id[effect_id]
                    expected = {"tenant_id": self.tenant_id, "workspace_id": source["request"]["workspace_id"],
                        "organization_id": source["request"]["organization_id"],
                        "legal_entity_id": source["request"][book]["legal_entity_id"], "purpose": "operational_posting",
                        **source["policies"][book]}
                    reverse = stage["plan"]["kind"] == "reverse_revaluation"
                    original = stage["plan"]["equation"].get("original_posting_effect_ids", {}).get(book)
                    if (any(effect[key] != value for key, value in expected.items())
                            or effect["source_kind"] != ("Reversal" if reverse else "Manual")
                            or effect["source_id"] != (original if reverse else effect["entry_id"])
                            or effect["reverses_effect_id"] != (original if reverse else None)
                            or effect["validation_contract_version"] != "finance-entry-review-v1"):
                        refuse("Original effect tenant, native source and captured currency policy differ.")
            entry_ids = [effect["entry_id"] for effect in effects]
            audit_ids = [effect["audit_event_id"] for effect in effects] + [row["audit_event_id"] for stage in stages for row in stage["phases"]]
            outbox_ids = [effect["outbox_event_id"] for effect in effects] + [row["outbox_event_id"] for stage in stages for row in stage["phases"]]
            original_rows = {
                "effects": effects,
                "entries": records(self.connection.execute("SELECT * FROM reconforge.finance_entries WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id", (self.tenant_id, entry_ids))),
                "lines": records(self.connection.execute("SELECT * FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=ANY(%s) ORDER BY entry_id,line_number", (self.tenant_id, entry_ids))),
                "dimensions": records(self.connection.execute("""SELECT d.* FROM reconforge.finance_entry_line_dimensions d
                    JOIN reconforge.finance_entry_lines l ON l.tenant_id=d.tenant_id AND l.id=d.entry_line_id
                    WHERE l.tenant_id=%s AND l.entry_id=ANY(%s) ORDER BY d.entry_line_id,d.dimension_id""", (self.tenant_id, entry_ids))),
                "plans": records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_plans WHERE tenant_id=%s AND source_id=%s ORDER BY sequence", (self.tenant_id, source_id))),
                "source": records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s AND id=%s", (self.tenant_id, source_id))),
                "links": records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_links WHERE tenant_id=%s AND plan_id=ANY(%s) ORDER BY plan_id,book", (self.tenant_id, plan_ids))),
                "reviews": records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_reviews WHERE tenant_id=%s AND plan_id=ANY(%s) ORDER BY plan_id", (self.tenant_id, plan_ids))),
                "commands": records(self.connection.execute("SELECT * FROM reconforge.intercompany_fx_commands WHERE tenant_id=%s AND plan_id=ANY(%s) ORDER BY command_id", (self.tenant_id, plan_ids))),
                "audit": records(self.connection.execute("SELECT * FROM reconforge.domain_audit_events WHERE tenant_id=%s AND id=ANY(%s) ORDER BY sequence", (self.tenant_id, audit_ids))),
                "outbox": records(self.connection.execute("SELECT * FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id=ANY(%s) ORDER BY event_id", (self.tenant_id, outbox_ids))),
            }
            qualified_scope = {"tenant_id": self.tenant_id, "workspace_id": source["request"]["workspace_id"],
                "organization_id": source["request"]["organization_id"],
                "legal_entity_ids": {book: source["request"][book]["legal_entity_id"] for book in BOOKS}}
            evidence = primitive({"schema_version": "intercompany-source-cashflow-evidence-v1", "qualified_scope": qualified_scope,
                "registry_snapshot": context.snapshot(), "source": source, "stages": stages, "report": report,
                "opening": asdict(opening), "cashflow": result, "original_rows": original_rows,
                "native_role": dict(self.connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()),
                "native_execution_proven": True, "performance_measurement": False,
                "audit_chain_recomputed": False, "financial_writes": False})
            evidence_size(evidence)
            return {**evidence, "evidence_digest": evidence_digest(evidence)}
