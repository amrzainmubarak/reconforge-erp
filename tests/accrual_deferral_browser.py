"""Empty approved native masters; every AD1 financial source comes from Studio."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from reconforge.application.accrual_deferral_evidence import evidence_chunks
from tests.test_postgres_accrual_deferral import ScheduleRuntime, configure_runtime, native_balances
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime

ACCRUAL_DEFERRAL_BROWSER_TABLES = (
    "accrual_deferral_sources", "accrual_deferral_plans", "accrual_deferral_period_pins", "accrual_deferral_account_pins",
    "accrual_deferral_phase_events", "accrual_deferral_claim_events", "accrual_deferral_claim_heads",
    "accrual_deferral_original_claims", "accrual_deferral_original_releases", "accrual_deferral_commands",
)
ACCRUAL_DEFERRAL_WORKSPACE_PROBE_TABLES = ACCRUAL_DEFERRAL_BROWSER_TABLES
ACCRUAL_DEFERRAL_RESTORE_TAMPER = (
    "UPDATE reconforge.accrual_deferral_sources SET payload=jsonb_set(payload,'{request,amount_minor}',to_jsonb((payload#>>'{request,amount_minor}')::bigint+1)) WHERE tenant_id=%s",
    "DELETE FROM reconforge.accrual_deferral_claim_events WHERE tenant_id=%s",
    "UPDATE reconforge.accrual_deferral_commands SET request_digest=repeat('0',64) WHERE tenant_id=%s",
)


def seed_accrual_deferral_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = create_receipt_runtime((admin_dsn, app_dsn))
    configured = configure_runtime(base)
    with configured.actor("maker") as (connection, _, _):
        if connection.execute("SELECT count(*) AS n FROM reconforge.accrual_deferral_sources WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] != 0:
            raise ValueError("Every browser source must be created in Studio")
        if connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] != 0:
            raise ValueError("Every browser financial effect must come from Studio")
    return base


@contextmanager
def accrual_deferral_restore_tamper_actor(base: ReceiptRuntime) -> Iterator[tuple[Any, Any, Any]]:
    with ScheduleRuntime(base).actor("poster") as context:
        yield context


def verify_accrual_deferral_browser(base: ReceiptRuntime) -> dict[str, Any]:
    import hashlib
    import json

    with ScheduleRuntime(base).actor("poster") as (connection, repository, actor):
        rows = connection.execute("SELECT id FROM reconforge.accrual_deferral_sources WHERE tenant_id=%s", (base.tenant,)).fetchall()
        if len(rows) != 1:
            raise ValueError("Exactly one original browser source is required")
        proof = repository.evidence(rows[0]["id"], actor=actor)
        source = proof["source"]
        if source["request"]["reference"] != "BROWSER-AD1-PREPAID" or source["request"]["mode"] != "new_prepaid_voucher":
            raise ValueError("The source must be the actual Studio voucher")
        if len(source["plans"]) != 6 or len(proof["native_effects"]) != 6 or any(plan["phase"] != 2 for plan in source["plans"]):
            raise ValueError("Every original source, tranche, exact inverse and replacement must complete")
        if any((plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]) != ("maker", "checker", "poster") for plan in source["plans"]):
            raise ValueError("Independent three-human native publication differs")
        if native_balances(connection, base.tenant) != {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}:
            raise ValueError("Original cash/source conservation differs")
        flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
        if flags["rolsuper"] or flags["rolbypassrls"]:
            raise ValueError("Browser correctness requires an ordinary non-bypass runtime")
    original = b"".join(evidence_chunks(proof))
    script = Path(__file__).resolve().parents[1] / ".github/scripts/verify_accrual_deferral_cycle_oracle.py"
    spec = spec_from_file_location("ad1_browser_original_oracle", script)
    if spec is None or spec.loader is None:
        raise ValueError("The independent original financial oracle is absent")
    oracle = module_from_spec(spec)
    spec.loader.exec_module(oracle)
    independent = oracle.verify(json.loads(original))
    return {"schema_version": "accrual-deferral-browser-native-verification-v1", "original_evidence": proof,
        "original_evidence_bytes": len(original), "original_evidence_sha256": hashlib.sha256(original).hexdigest(),
        "oracle_source_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "independent_oracle": independent,
        "source_count": 1, "native_effects": 6, "runtime_superuser": False, "runtime_bypassrls": False,
        "country_statutory_packs": 0, "bank_execution_proven": False, "performance_comparison_accepted": False}
