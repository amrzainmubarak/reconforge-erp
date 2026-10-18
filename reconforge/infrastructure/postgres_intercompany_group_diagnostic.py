"""Bounded original IC2 captures and native period observations; no writes."""

from dataclasses import asdict
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_digest, evidence_size
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_group_diagnostic import (
    BOOKS,
    IntercompanyDiagnosticSelection,
    reconcile_intercompany_reports,
    require,
)
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository, primitive


class PostgresIntercompanyGroupDiagnosticRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.cashflow = PostgresIntercompanyCashflowRepository(connection, tenant_id)

    def evidence(self, selection: IntercompanyDiagnosticSelection, *, actor: PostingActor) -> dict[str, Any]:
        with self.cashflow.ic2.owner._transaction():
            ic2 = self.cashflow.ic2
            workspace: str | None = None
            # Current authority precedes metadata/source waits. Preview rows are
            # not exported; full source locks/captures are checked afterwards.
            for pin in selection.pins:
                source = ic2._peek("source", pin.opening.source_id)
                ic2._authorize(actor, "read", source, lock=True)
                requested = source["request"]["workspace_id"]
                require(workspace is None or workspace == requested, "Selected sources have different workspaces.")
                workspace = requested
            proofs = []
            for pin in selection.pins:
                proof = self.cashflow.evidence(pin.opening.source_id, opening=pin.opening, actor=actor)
                require(proof["evidence_digest"] == evidence_digest({key: value for key, value in proof.items() if key != "evidence_digest"}),
                        "A complete original source capture seal differs.")
                proofs.append(proof)
                # The whole envelope has one existing 64MiB/1M-node bound. It
                # never silently drops a selected member when that bound fails.
                evidence_size({"source_captures": proofs})
            period_ids = sorted({entry["snapshot"]["entry"]["period_id"] for proof in proofs
                for stage in proof["stages"] for entry in stage["plan"]["entries"]})
            # Source history is retained above in canonical source order. Period
            # status is only an observation in this one statement snapshot: no
            # new row lock or close-readiness/stable-period promise is introduced.
            observations = primitive(records(self.connection.execute("""SELECT tenant_id,id,application_workspace_id,name,
                start_date,end_date,status,status_reason,fiscal_year,period_number,updated_at
                FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s
                AND id=ANY(%s) ORDER BY id""", (self.tenant_id, workspace, period_ids))))
            diagnostic = reconcile_intercompany_reports(selection, proofs, observations)
            values = [abs(row[key]) for row in diagnostic["trial_balance_bridge"]
                      for key in ("translated_minor", "native_adjustment_minor", "combined_minor")]
            values.extend(abs(value) for value in diagnostic["income_statement"].values())
            values.extend(abs(value) for key, value in diagnostic["balance_sheet"].items() if key != "balanced")
            values.extend(abs(value) for value in diagnostic["cash_equation"].values())
            maximum = max(values)
            for book in BOOKS:
                scope = {"workspace_id": diagnostic["qualified_scope"]["workspace_id"],
                    "organization_id": diagnostic["qualified_scope"]["organization_id"],
                    "legal_entity_id": diagnostic["qualified_scope"]["legal_entity_ids"][book],
                    "amount_minor": maximum, "currency_precision": diagnostic["reporting_policy"]["currency_precision"]}
                for permission in ("intercompany_fx.read", "finance_core.read"):
                    ic2.owner._actor(actor, permission, scope, mutation=False)
            evidence = {"schema_version": "intercompany-group-diagnostic-evidence-v1",
                "selection": {"pins": [asdict(pin) for pin in selection.pins]},
                "diagnostic": diagnostic, "source_captures": proofs, "native_periods": observations,
                "native_execution_proven": True, "financial_writes": False,
                "native_period_capture_scope": "one-readonly-statement-snapshot-without-period-row-locks",
                "formal_close_workflow_assessed": False, "audit_chain_recomputed": False,
                "performance_comparison_accepted": False}
            evidence_size(evidence)
            return {**evidence, "evidence_digest": evidence_digest(evidence)}
