"""Two governed native originals; browser activity is strictly read-only."""

import hashlib
import json
import runpy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_chunks
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.domain.intercompany_group_diagnostic import IntercompanyDiagnosticSelection, IntercompanyReportPin
from reconforge.infrastructure.postgres_intercompany_group_diagnostic import (
    PostgresIntercompanyGroupDiagnosticRepository,
)
from tests.intercompany_fx_browser_seed import INTERCOMPANY_FX_BROWSER_TABLES, seed_intercompany_fx_browser
from tests.test_postgres_intercompany_fx import FxRuntime
from tests.test_postgres_intercompany_group_diagnostic import closed_source, selection
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

INTERCOMPANY_GROUP_DIAGNOSTIC_BROWSER_TABLES = (*INTERCOMPANY_FX_BROWSER_TABLES,
    "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
    "finance_posting_commands", "fiscal_periods")
INTERCOMPANY_GROUP_DIAGNOSTIC_WORKSPACE_PROBE_TABLES = INTERCOMPANY_GROUP_DIAGNOSTIC_BROWSER_TABLES
INTERCOMPANY_GROUP_DIAGNOSTIC_RESTORE_TAMPER = (
    """UPDATE reconforge.intercompany_fx_sources SET payload=jsonb_set(payload,'{request,transaction_minor}',
        to_jsonb((payload#>>'{request,transaction_minor}')::BIGINT+1),false) WHERE tenant_id=%s""",
    "UPDATE reconforge.intercompany_fx_links SET reason='Tamper original native link reason' WHERE tenant_id=%s",
    "UPDATE reconforge.intercompany_fx_commands SET request_digest=repeat('0',64) WHERE tenant_id=%s",
)
# Only a raw original seal is kept here; no credentials or source rows.
_ORIGINAL_SHA: dict[str, str] = {}


def original_evidence(base: ReceiptRuntime) -> dict[str, Any]:
    with FxRuntime(base).actor("browser-poster") as (connection, repository, actor):
        ids = connection.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s ORDER BY id",
                                 (base.tenant,)).fetchall()
        if len(ids) != 2:
            raise ValueError("Exactly two original synthetic source cycles are required")
        pins = []
        for row in ids:
            source = repository.get_source(row["id"], actor=actor)
            origin, final = source["plans"][0], source["plans"][-1]
            report = repository.report(source["id"], actor=actor)
            pins.append(IntercompanyReportPin(SourceCashOpening(source["id"], source["source_digest"], origin["id"],
                origin["plan_digest"], 0, 0, "complete-native-source-origin-membership"), final["id"],
                final["plan_digest"], report["report_digest"]))
        return PostgresIntercompanyGroupDiagnosticRepository(connection, base.tenant).evidence(
            IntercompanyDiagnosticSelection(tuple(pins)), actor=actor)


def seed_intercompany_group_diagnostic_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_intercompany_fx_browser(admin_dsn, app_dsn)
    runtime = FxRuntime(base)
    selected = selection(closed_source(runtime, "BROWSER-GROUP-ONE"), closed_source(runtime, "BROWSER-GROUP-TWO"))
    proof = original_evidence(base)
    if proof["selection"]["pins"] != [
        {"opening": {"source_id": pin.opening.source_id, "source_digest": pin.opening.source_digest,
            "origin_plan_id": pin.opening.origin_plan_id, "origin_plan_digest": pin.opening.origin_plan_digest,
            "seller_minor": 0, "buyer_minor": 0, "basis": pin.opening.basis}, "elimination_plan_id": pin.elimination_plan_id,
            "elimination_plan_digest": pin.elimination_plan_digest, "report_digest": pin.report_digest} for pin in selected.pins]:
        raise ValueError("Seeded sources differ from their original exact selected pins")
    _ORIGINAL_SHA[base.tenant] = hashlib.sha256(b"".join(evidence_chunks(proof))).hexdigest()
    return base


@contextmanager
def intercompany_group_diagnostic_restore_tamper_actor(base: ReceiptRuntime):
    with FxRuntime(base).actor("browser-poster") as context:
        yield context


def verify_intercompany_group_diagnostic_browser(base: ReceiptRuntime) -> dict[str, Any]:
    proof = original_evidence(base)
    raw = b"".join(evidence_chunks(proof))
    sha = hashlib.sha256(raw).hexdigest()
    if _ORIGINAL_SHA.get(base.tenant) != sha:
        raise ValueError("Browser or restore changed the complete original source/period evidence")
    captures = proof["source_captures"]
    if {capture["source"]["request"]["reference"] for capture in captures} != {
            "DIAGNOSTIC-BROWSER-GROUP-ONE", "DIAGNOSTIC-BROWSER-GROUP-TWO"}:
        raise ValueError("Original browser fixture source identities differ")
    if any([stage["plan"]["kind"] for stage in capture["stages"]] != ["recognize", "settle", "revalue", "eliminate"]
           for capture in captures):
        raise ValueError("Two complete four-operation original source cycles are required")
    if any((stage["plan"]["preparer_actor_id"], stage["plan"]["reviewer_actor_id"], stage["plan"]["posted_actor_id"])
           != ("maker", "checker", "poster") for capture in captures for stage in capture["stages"]):
        raise ValueError("Original three-person publication membership differs")
    if any(capture["native_role"] != {"rolsuper": False, "rolbypassrls": False} for capture in captures):
        raise ValueError("Ordinary nonowner, nonbypass runtime is required")
    helper = Path(__file__).resolve().parents[1] / ".github/scripts/verify_intercompany_group_diagnostic.py"
    independent = runpy.run_path(str(helper))["verify"](json.loads(raw))
    if independent["sources"] != 2 or independent["native_effects"] != 14 or independent["cash_equation"] != {
            "opening_minor": 0, "operating_net_minor": 0, "fx_on_cash_minor": 202, "closing_minor": 202}:
        raise ValueError("Original selected source membership or independent Cash equation differs")
    return {"schema_version": "intercompany-group-diagnostic-browser-native-verification-v1",
        "original_evidence": proof, "original_evidence_bytes": len(raw), "original_evidence_sha256": sha,
        "oracle_source_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(), "independent_oracle": independent,
        "source_count": 2, "native_effect_count": 14, "native_operation_count": 8,
        "financial_sources_provisioned_by": "governed-native-fixture-three-distinct-test-human-principals",
        "browser_financial_writes": False, "runtime_superuser": False, "runtime_bypassrls": False,
        "formal_close_workflow_assessed": False, "whole_group_membership_proven": False,
        "country_statutory_packs": 0, "performance_comparison_accepted": False}
