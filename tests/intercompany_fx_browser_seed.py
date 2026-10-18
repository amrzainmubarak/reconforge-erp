"""Empty native ICFX2 masters; each financial effect must come from real Studio."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from reconforge.domain.finance_posting import PostingActor, digest_payload
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_intercompany_fx import ENTITIES, FxRuntime, seed_intercompany_fx_masters
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

INTERCOMPANY_FX_BROWSER_TABLES = ("intercompany_fx_sources", "intercompany_fx_plans", "intercompany_fx_reviews", "intercompany_fx_links", "intercompany_fx_post_evidence", "intercompany_fx_commands")
INTERCOMPANY_FX_RESTORE_TAMPER = ("UPDATE reconforge.intercompany_fx_sources SET reference='TAMPER' WHERE tenant_id=%s",
    "UPDATE reconforge.intercompany_fx_links SET reason='TAMPER' WHERE tenant_id=%s", "UPDATE reconforge.intercompany_fx_commands SET request_digest='TAMPER' WHERE tenant_id=%s")


def seed_intercompany_fx_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_receipt_browser(admin_dsn, app_dsn)
    seed_intercompany_fx_masters(base)
    seed_erp_browser_principals(base)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("erp-maker", "erp-checker", "erp-poster"):
            for entity in sorted(ENTITIES):
                authority.grant(tenant_id=base.tenant, grant_id="ic2-browser-" + person + "-" + entity, principal_type="user", principal_id=person,
                    scope_type="legal_entity", scope_id=entity, actor_id=person)
        assert connection.execute("SELECT count(*) n FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] == 0
    return base


@contextmanager
def intercompany_fx_restore_tamper_actor(base: ReceiptRuntime) -> Iterator[tuple[Any, Any, PostingActor]]:
    with FxRuntime(base).actor("browser-poster") as (connection, repository, actor):
        sources = connection.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s", (base.tenant,)).fetchall()
        assert len(sources) == 1 and repository.get_source(sources[0]["id"], actor=actor)["state"]["closed"]
        yield connection, repository, actor


def verify_intercompany_fx_browser(base: ReceiptRuntime) -> dict[str, Any]:
    with FxRuntime(base).actor("browser-poster") as (connection, repository, actor):
        rows = connection.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s", (base.tenant,)).fetchall()
        assert len(rows) == 1
        source = repository.get_source(rows[0]["id"], actor=actor)
        assert source["request"]["reference"] == "BROWSER-ICFX2" and source["request"]["transaction_minor"] == 10001
        assert source["state"]["transaction_paid_minor"] == 3000 and source["state"]["closed"]
        assert [plan["kind"] for plan in source["plans"]] == ["recognize", "settle", "revalue", "eliminate"]
        stages = [repository.evidence(plan["id"], actor=actor) for plan in source["plans"]]
        assert all((stage["plan"]["preparer_actor_id"], stage["plan"]["reviewer_actor_id"], stage["plan"]["posted_actor_id"]) == ("erp-maker", "erp-checker", "erp-poster") for stage in stages)
        assert sum(len(stage["native_effects"]) for stage in stages) == 7
        report = repository.report(source["id"], actor=actor)
        assert report["cash_net_movement_minor"] == 101 and report["cta_minor"] == -291
        assert report["income_statement"] == {"income_minor": 563, "expense_minor": 171, "result_minor": 392}
        return {"schema_version": "intercompany-fx-browser-native-verification-v2", "source_digest": source["source_digest"],
            "proof": {"schema_version": "intercompany-fx-original-cycle-proof-v2", "performance_measurement": False,
                "native_role": dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()), "stages": stages, "report": report},
            "source_evidence_hashes": {stage["plan"]["id"]: digest_payload(stage) for stage in stages}, "native_effect_count": 7,
            "source_count": 1, "operation_count": 4, "report_digest": report["report_digest"], "performance_measurement": False}
