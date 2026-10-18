"""Read-only public source capture; no personnel credential or financial writes."""

import hashlib
from dataclasses import asdict
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_digest, evidence_size
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.project_source_reconciliation import (
    ProjectSourceSelection,
    diagnose_project_source_close,
    reconcile_project_sources,
    require,
)
from reconforge.infrastructure.postgres_people_project_payroll import PostgresPeopleProjectPayrollRepository
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository

# All public rows below are captured by one statement snapshot. In particular,
# payroll cash cannot be appended between its source and native-line reads.
# No employee directory, private wages, rates or private command table is read.
CAPTURE_SQL = r"""
WITH payruns AS MATERIALIZED (
 SELECT * FROM reconforge.hc_payruns WHERE tenant_id=%(tenant)s AND id=%(payrun)s
), payments AS MATERIALIZED (
 SELECT * FROM reconforge.hc_payments WHERE tenant_id=%(tenant)s AND payrun_id=%(payrun)s ORDER BY id LIMIT 201
), plans AS MATERIALIZED (
 SELECT * FROM reconforge.pb_plans WHERE tenant_id=%(tenant)s AND(id=%(invoice)s OR parent_id=%(invoice)s) ORDER BY id LIMIT 201
), original_times AS MATERIALIZED (
 SELECT jsonb_array_elements_text(payload->'time_entry_ids') AS id FROM payruns
), entries AS MATERIALIZED (
 SELECT e.*,o.id AS organization_id,entity.id AS legal_entity_id FROM reconforge.finance_entries e
 JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.application_workspace_id=e.workspace_id AND o.organization_code=e.organization_code
 JOIN reconforge.legal_entities entity ON entity.tenant_id=o.tenant_id AND entity.organization_id=o.id AND entity.entity_code=e.entity_code
 WHERE e.tenant_id=%(tenant)s AND e.id IN(
 SELECT entry_id FROM payruns UNION SELECT entry_id FROM payments UNION SELECT entry_id FROM plans)
), lines AS MATERIALIZED (
 SELECT * FROM reconforge.finance_entry_lines WHERE tenant_id=%(tenant)s AND entry_id IN(SELECT id FROM entries)
), effects AS MATERIALIZED (
 SELECT * FROM reconforge.finance_posting_effects WHERE tenant_id=%(tenant)s AND entry_id IN(SELECT id FROM entries)
), projects AS MATERIALIZED (
 SELECT * FROM reconforge.hc_projects WHERE tenant_id=%(tenant)s AND id IN(
 SELECT jsonb_object_keys(payload->'project_minor') FROM payruns UNION
 SELECT jsonb_object_keys(payload->'calculation'->'project_minor') FROM plans WHERE kind='Invoice')
), prices AS MATERIALIZED (
 SELECT * FROM reconforge.pb_prices WHERE tenant_id=%(tenant)s AND id IN(
 SELECT jsonb_array_elements_text(payload->'calculation'->'price_ids') FROM plans WHERE kind='Invoice')
), ar AS MATERIALIZED (
 SELECT i.*,COALESCE((SELECT sum(a.amount_minor)::BIGINT FROM reconforge.ar_receipt_allocations a
  WHERE a.tenant_id=i.tenant_id AND a.invoice_id=i.id),0) AS allocated_minor
 FROM reconforge.ar_invoices i WHERE i.tenant_id=%(tenant)s AND i.id IN(SELECT ar_invoice_id FROM plans WHERE kind='Invoice')
), source_events AS MATERIALIZED (
 SELECT audit_id,review_audit_id,post_audit_id,outbox_id,review_outbox_id,post_outbox_id FROM payruns UNION ALL
 SELECT audit_id,review_audit_id,post_audit_id,outbox_id,review_outbox_id,post_outbox_id FROM payments UNION ALL
 SELECT audit_id,review_audit_id,post_audit_id,outbox_id,review_outbox_id,post_outbox_id FROM plans
 UNION ALL SELECT audit_id,approve_audit_id,NULL,outbox_id,approve_outbox_id,NULL FROM prices
)
SELECT jsonb_build_object(
 'qualified_scope',jsonb_build_object('tenant_id',%(tenant)s::TEXT,'workspace_id',%(workspace)s::TEXT,
  'organization_id',%(organization)s::TEXT,'legal_entity_id',%(entity)s::TEXT),
 'captured_at',statement_timestamp(),
 'payruns',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM payruns x),'[]'::JSONB),
 'payments',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM payments x),'[]'::JSONB),
 'plans',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM plans x),'[]'::JSONB),
 'projects',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM projects x),'[]'::JSONB),
 'prices',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM prices x),'[]'::JSONB),
 'times',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM(
  SELECT tenant_id,id,workspace_id,organization_id,legal_entity_id,business_date,lines,source_digest,approver_id,
   submitter_id,submit_audit_id,submit_outbox_id,audit_id,outbox_id FROM reconforge.hc_times
  WHERE tenant_id=%(tenant)s AND id IN(SELECT id FROM original_times))x),'[]'::JSONB),
 'hc_claim_heads',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY time_id) FROM reconforge.hc_claim_heads x
  WHERE tenant_id=%(tenant)s AND time_id IN(SELECT id FROM original_times)),'[]'::JSONB),
 'pb_claim_heads',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY time_id) FROM reconforge.pb_claim_heads x
  WHERE tenant_id=%(tenant)s AND time_id IN(SELECT id FROM original_times)),'[]'::JSONB),
 'hc_claim_events',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY time_id,sequence) FROM reconforge.hc_claim_events x
  WHERE tenant_id=%(tenant)s AND time_id IN(SELECT id FROM original_times)),'[]'::JSONB),
 'pb_claim_events',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY time_id,sequence) FROM reconforge.pb_claim_events x
  WHERE tenant_id=%(tenant)s AND time_id IN(SELECT id FROM original_times)),'[]'::JSONB),
 'entries',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM entries x),'[]'::JSONB),
 'entry_lines',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY entry_id,line_number) FROM lines x),'[]'::JSONB),
 'entry_dimensions',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY entry_line_id,dimension_id)
  FROM reconforge.finance_entry_line_dimensions x WHERE tenant_id=%(tenant)s AND entry_line_id IN(SELECT id FROM lines)),'[]'::JSONB),
 'effects',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM effects x),'[]'::JSONB),
 'accounts',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.finance_accounts x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT account_id FROM lines)),'[]'::JSONB),
 'journals',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.finance_journals x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT journal_id FROM entries)),'[]'::JSONB),
 'dimension_masters',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.finance_dimensions x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT dimension_id FROM projects)),'[]'::JSONB),
 'dimension_values',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.finance_dimension_values x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT value_id FROM projects)),'[]'::JSONB),
 'ar_invoice',(SELECT to_jsonb(x) FROM ar x),
 'ar_receipts',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.ar_receipts x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT receipt_id FROM plans WHERE kind='Collection')),'[]'::JSONB),
 'ar_allocations',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY receipt_id) FROM reconforge.ar_receipt_allocations x
  WHERE tenant_id=%(tenant)s AND invoice_id IN(SELECT id FROM ar)),'[]'::JSONB),
 'project_ledger',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM(
  SELECT l.id,l.tenant_id,l.entry_id,l.account_id,l.debit_minor,l.credit_minor FROM reconforge.finance_entry_lines l
  JOIN reconforge.finance_entries e ON e.tenant_id=l.tenant_id AND e.id=l.entry_id
  JOIN reconforge.finance_posting_effects f ON f.tenant_id=e.tenant_id AND f.entry_id=e.id
  JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
  JOIN reconforge.finance_entry_line_dimensions d ON d.tenant_id=l.tenant_id AND d.entry_line_id=l.id
  JOIN projects p ON p.tenant_id=d.tenant_id AND p.dimension_id=d.dimension_id AND p.value_id=d.dimension_value_id
  WHERE l.tenant_id=%(tenant)s AND p.id=%(project)s AND e.period_id=%(period)s AND e.workspace_id=%(workspace)s
   AND e.organization_code=%(organization_code)s AND e.entity_code=%(entity_code)s AND a.account_type IN('Expense','Income')
 )x),'[]'::JSONB),
 'native_post_commands',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY command_id) FROM reconforge.finance_posting_commands x
  WHERE tenant_id=%(tenant)s AND operation='post' AND result_json->>'id' IN(SELECT id FROM effects)),'[]'::JSONB),
 'audits',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY id) FROM reconforge.domain_audit_events x
  WHERE tenant_id=%(tenant)s AND id IN(SELECT audit_id FROM source_events UNION SELECT review_audit_id FROM source_events
   UNION SELECT post_audit_id FROM source_events UNION SELECT audit_event_id FROM effects)),'[]'::JSONB),
 'outbox',COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY event_id) FROM reconforge.outbox_events x
  WHERE tenant_id=%(tenant)s AND event_id IN(SELECT outbox_id FROM source_events UNION SELECT review_outbox_id FROM source_events
   UNION SELECT post_outbox_id FROM source_events UNION SELECT outbox_event_id FROM effects)),'[]'::JSONB),
 'native_role',(SELECT jsonb_build_object('rolsuper',rolsuper,'rolbypassrls',rolbypassrls,
  'personnel_member',pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER'))
  FROM pg_catalog.pg_roles WHERE rolname=current_user)
) AS original
"""


class PostgresProjectSourceReconciliationRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.people = PostgresPeopleProjectPayrollRepository(connection, tenant_id)
        self.billing = PostgresProjectTimeBillingRepository(connection, tenant_id)

    def report(self, selection: ProjectSourceSelection, *, actor: PostingActor) -> dict[str, Any]:
        with self.billing.owner._transaction():
            installed = self.connection.execute(
                "SELECT to_regclass('reconforge.hc_payruns') AS wage,to_regclass('reconforge.pb_plans') AS billing"
            ).fetchone()
            if installed["wage"] is None or installed["billing"] is None:
                raise FinancePostingError(
                    "project_reconciliation_backend_unavailable",
                    "Both governed PostgreSQL wage and project billing sources are required.",
                )
            # Existing source reads take current identity/scope admission. The
            # wage financial view additionally uses all four retained contexts.
            wage = self.people.get(selection.payrun_id, actor=actor, sensitive=False)
            self.billing._financial_read(actor, wage)
            self.billing.get(selection.invoice_id, actor=actor)
            params = {
                "tenant": self.tenant_id,
                "workspace": selection.scope.workspace_id,
                "organization": selection.scope.organization_id,
                "entity": selection.scope.legal_entity_id,
                "organization_code": selection.scope.organization_code,
                "entity_code": selection.scope.entity_code,
                "payrun": selection.payrun_id,
                "invoice": selection.invoice_id,
                "project": selection.project_id,
                "period": selection.period_id,
            }
            original = self.connection.execute(CAPTURE_SQL, params).fetchone()["original"]
            # Recheck every emitted captured financial source, including newly
            # observed whole-payrun payments. No sensitive read is requested.
            for source in [*original["payruns"], *original["payments"], *original["plans"]]:
                self.billing._financial_read(actor, source)
                if source["id"].startswith("HC1"):
                    self.people._authorize(actor, "read", source["payload"], mutation=False)
            for price in original["prices"]:
                self.billing._financial_read(actor, price)
            require(
                original["native_role"] == {"rolsuper": False, "rolbypassrls": False, "personnel_member": False},
                "Source reconciliation requires the ordinary nonowner, nonbypass runtime.",
            )
            report = reconcile_project_sources(selection, original)
            evidence = {
                "schema_version": "project-source-reconciliation-evidence-v1",
                "selection": asdict(selection),
                "report": report,
                "original_rows": original,
                "native_execution_proven": True,
                "capture_scope": "one-fixed-readonly-postgresql-statement-snapshot",
                "capture_query_sha256": hashlib.sha256(CAPTURE_SQL.encode("utf8")).hexdigest(),
                "financial_writes": False,
                "private_personnel_reads": False,
                "private_payroll_command_receipts_exported": False,
                "audit_chain_recomputed": False,
                "performance_comparison_accepted": False,
            }
            evidence_size(evidence)
            return {**evidence, "evidence_digest": evidence_digest(evidence)}

    def close_diagnostics(self, selection: ProjectSourceSelection, *, actor: PostingActor) -> dict[str, Any]:
        with self.billing.owner._transaction():
            source = self.report(selection, actor=actor)
            period_ids = sorted({row["period_id"] for row in source["original_rows"]["entries"]})
            # These are observed metadata, not stable/locked close readiness.
            # Existing current source admission completes before this SELECT.
            observations = self.connection.execute("""SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY id),'[]'::JSONB) AS periods
                FROM (SELECT tenant_id,id,application_workspace_id,name,start_date,end_date,status,updated_at
                FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s AND id=ANY(%s))p""",
                (self.tenant_id, selection.scope.workspace_id, period_ids)).fetchone()["periods"]
            diagnostic = diagnose_project_source_close(selection, source, observations)
            envelope = {"schema_version": "project-source-close-evidence-v1", "diagnostic": diagnostic,
                        "source_evidence": source, "source_original_sha256": evidence_digest(source),
                        "source_original_bytes": evidence_size(source), "native_periods": observations,
                        "native_execution_proven": True, "financial_writes": False,
                        "private_personnel_reads": False, "audit_chain_recomputed": False,
                        "performance_comparison_accepted": False}
            evidence_size(envelope)
            return {**envelope, "evidence_digest": evidence_digest(envelope)}
