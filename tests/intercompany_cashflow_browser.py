"""Reviewed native synthetic IC2 fixture for a strictly read-only Studio view.

The four financial operations are provisioned through the existing native owner
with three distinct test human principals. They are not browser financial writes.
The browser only selects, verifies and downloads this complete original source.
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_chunks
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository
from tests.intercompany_fx_browser_seed import INTERCOMPANY_FX_BROWSER_TABLES, seed_intercompany_fx_browser
from tests.test_postgres_intercompany_fx import FxRuntime, cash, eliminate, preparation, publish, revalue
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

INTERCOMPANY_CASHFLOW_BROWSER_TABLES = INTERCOMPANY_FX_BROWSER_TABLES
INTERCOMPANY_CASHFLOW_WORKSPACE_PROBE_TABLES = INTERCOMPANY_FX_BROWSER_TABLES
INTERCOMPANY_CASHFLOW_RESTORE_TAMPER = (
    "UPDATE reconforge.intercompany_fx_sources SET reference='TAMPER' WHERE tenant_id=%s",
    "UPDATE reconforge.intercompany_fx_links SET reason='TAMPER' WHERE tenant_id=%s",
    "UPDATE reconforge.intercompany_fx_commands SET request_digest=repeat('0',64) WHERE tenant_id=%s",
)
# Memory-only original financial seal, shared by original/restored verification.
# No credentials or source rows are stored in this index.
_ORIGINAL_SHA: dict[str, str] = {}


def source_evidence(base: ReceiptRuntime) -> dict[str, Any]:
    with FxRuntime(base).actor("browser-poster") as (connection, repository, actor):
        rows = connection.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s", (base.tenant,)).fetchall()
        if len(rows) != 1:
            raise ValueError("Exactly one complete synthetic source is required")
        source = repository.get_source(rows[0]["id"], actor=actor)
        origin = source["plans"][0]
        opening = SourceCashOpening(source["id"], source["source_digest"], origin["id"], origin["plan_digest"], 0, 0,
            "complete-native-source-origin-membership")
        return PostgresIntercompanyCashflowRepository(connection, base.tenant).evidence(source["id"], opening=opening, actor=actor)


def seed_intercompany_cashflow_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_intercompany_fx_browser(admin_dsn, app_dsn)
    runtime = FxRuntime(base)
    with runtime.actor("maker") as (_, repository, actor):
        prepared = repository.prepare(replace(preparation(), reference="BROWSER-CASHFLOW-NATIVE-SOURCE"),
            command_id="browser-cashflow-native-origin", actor=actor)
    original = publish(runtime, prepared, "browser-cashflow-native-origin")
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    _ORIGINAL_SHA[base.tenant] = hashlib.sha256(b"".join(evidence_chunks(source_evidence(base)))).hexdigest()
    return base


@contextmanager
def intercompany_cashflow_restore_tamper_actor(base: ReceiptRuntime):
    with FxRuntime(base).actor("browser-poster") as context:
        yield context


def verify_intercompany_cashflow_browser(base: ReceiptRuntime) -> dict[str, Any]:
    proof = source_evidence(base)
    original = b"".join(evidence_chunks(proof))
    raw_sha = hashlib.sha256(original).hexdigest()
    if _ORIGINAL_SHA.get(base.tenant) != raw_sha:
        raise ValueError("Browser reads or restore changed the complete original source membership")
    if proof["source"]["request"]["reference"] != "BROWSER-CASHFLOW-NATIVE-SOURCE":
        raise ValueError("The original fixture source identity differs")
    if [stage["plan"]["kind"] for stage in proof["stages"]] != ["recognize", "settle", "revalue", "eliminate"]:
        raise ValueError("Exactly four original governed source operations are required")
    if any((stage["plan"]["preparer_actor_id"], stage["plan"]["reviewer_actor_id"], stage["plan"]["posted_actor_id"])
            != ("maker", "checker", "poster") for stage in proof["stages"]):
        raise ValueError("The three distinct original human principals differ")
    if proof["native_role"] != {"rolsuper": False, "rolbypassrls": False} or len(proof["original_rows"]["effects"]) != 7:
        raise ValueError("The actual native effects or ordinary runtime differ")
    flow = proof["cashflow"]
    if (flow["operating_inflow_minor"], flow["operating_outflow_minor"], flow["operating_net_minor"],
            flow["fx_on_cash_minor"], flow["closing_minor"]) != (3000, 3000, 0, 101, 101):
        raise ValueError("Original source operating and FX-on-Cash equation differs")
    script = Path(__file__).resolve().parents[1] / ".github/scripts/verify_intercompany_cashflow_oracle.py"
    spec = spec_from_file_location("cashflow_browser_original_oracle", script)
    if spec is None or spec.loader is None:
        raise ValueError("The independent original source oracle is absent")
    oracle = module_from_spec(spec)
    spec.loader.exec_module(oracle)
    independent = oracle.verify(json.loads(original))
    return {"schema_version": "intercompany-source-cashflow-browser-native-verification-v1",
        "original_evidence": proof, "original_evidence_bytes": len(original), "original_evidence_sha256": raw_sha,
        "oracle_source_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "independent_oracle": independent,
        "source_count": 1, "native_effect_count": 7, "native_operation_count": 4,
        "financial_source_provisioned_by": "governed-native-fixture-three-distinct-test-human-principals",
        "browser_financial_writes": False, "runtime_superuser": False, "runtime_bypassrls": False,
        "country_statutory_packs": 0, "bank_execution_proven": False, "performance_comparison_accepted": False}
