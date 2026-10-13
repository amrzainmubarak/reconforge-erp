"""Real source read/price authorization against the captured exact monetary policy."""
from decimal import Decimal

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.people_project_payroll import TimeLine, TimeSubmission
from reconforge.domain.project_time_billing import ProjectPriceAgreement
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository
from tests.test_postgres_people_project_payroll import SCOPE, PeopleRuntime
from tests.test_postgres_project_time_billing import prepare, sources

pytest_plugins = ("tests.test_postgres_project_time_billing",)


def ceiling(monkeypatch, permission: str) -> list[Decimal]:
    import reconforge.infrastructure.postgres_operational_finance as core

    amounts = []
    def bound(principal, **context):
        if context["required_permission"] == permission and context.get("amount") is not None:
            amounts.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal("20"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(core, "evaluate_principal_access", bound)
    return amounts


def test_native_get_refuses_lower_finance_read_ceiling_with_module_read_allowed(billing: PeopleRuntime, monkeypatch) -> None:
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    observed = ceiling(monkeypatch, "finance_core.read")
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresProjectTimeBillingRepository(connection, billing.base.tenant).get(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("62.36")]


def test_price_catalog_refuses_lower_hourly_read_ceiling_without_any_invoice(billing: PeopleRuntime, monkeypatch) -> None:
    sources(billing)
    observed = ceiling(monkeypatch, "project_time_billing.read")
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresProjectTimeBillingRepository(connection, billing.base.tenant).catalog(SCOPE, actor=actor)
    assert "denied" in refused.value.code and len(observed) == 1 and observed[0] in (Decimal("20.01"), Decimal("30.01"))


@pytest.mark.parametrize("read", ["get", "catalog"])
@pytest.mark.parametrize("permission", ["finance_core.read", "people_project_payroll.read", "receivables.read"])
def test_each_financial_plan_read_uses_captured_amount_for_every_cross_permission(billing: PeopleRuntime,
        monkeypatch, read: str, permission: str) -> None:
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    observed = ceiling(monkeypatch, permission)
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        repository.catalog(SCOPE, actor=actor) if read == "catalog" else repository.get(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("62.36")]


@pytest.mark.parametrize("read", ["get", "catalog"])
@pytest.mark.parametrize("permission", ["finance_core.read", "people_project_payroll.read", "receivables.read"])
def test_cached_reader_refuses_current_cross_permission_revocation(billing: PeopleRuntime, read: str,
        permission: str) -> None:
    import psycopg

    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    with billing.actor("maker", private=False) as (connection, _, actor):
        with psycopg.connect(billing.base.admin_dsn) as admin:
            admin.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change'
                WHERE tenant_id=%s AND permission_name=%s""", (billing.base.tenant, permission))
        with pytest.raises(FinancePostingError) as refused:
            repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
            repository.catalog(SCOPE, actor=actor) if read == "catalog" else repository.get(plan["id"], actor=actor)
        assert "denied" in refused.value.code


@pytest.mark.parametrize("action", ["manage", "manage_replay", "approve_price"])
def test_price_mutations_apply_hourly_amount_and_preserve_original_source(billing: PeopleRuntime, monkeypatch,
        action: str) -> None:
    sources(billing)
    with billing.actor("maker", private=False) as (connection, _, actor):
        project = connection.execute("SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s AND project_code='P2'", (billing.base.tenant,)).fetchone()["id"]
        request = ProjectPriceAgreement(SCOPE, "CUSTOMER", project, "2026-11-01", "2026-11-30", "USD", 3001, "Future original customer price")
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        pending = repository.register_price(request, command_id="pending-price", actor=actor) if action != "manage" else None
        before = repository.catalog(SCOPE, actor=actor)
    observed = ceiling(monkeypatch, "project_time_billing." + ("manage" if action.startswith("manage") else action))
    with billing.actor("maker" if action.startswith("manage") else "checker", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        with pytest.raises(FinancePostingError) as refused:
            if action.startswith("manage"):
                repository.register_price(request, command_id="pending-price" if action == "manage_replay" else "refused-price", actor=actor)
            else:
                repository.approve_price(pending["id"], expected_digest=pending["source_digest"], command_id="refused-approval", actor=actor)
        assert "denied" in refused.value.code and observed == [Decimal("30.01")]
        assert repository.catalog(SCOPE, actor=actor) == before


@pytest.mark.parametrize("read", ["get", "evidence"])
@pytest.mark.parametrize("permission", ["project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read"])
def test_small_invoice_cannot_disclose_retained_hourly_price_above_current_read_ceiling(billing: PeopleRuntime,
        monkeypatch, read: str, permission: str) -> None:
    sources(billing)
    with billing.actor("maker") as (connection, repository, actor):
        employee = connection.execute("SELECT id FROM reconforge.hc_employees WHERE tenant_id=%s AND employee_code='E2'", (billing.base.tenant,)).fetchone()["id"]
        project = connection.execute("SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s AND project_code='P2'", (billing.base.tenant,)).fetchone()["id"]
        price = connection.execute("SELECT id FROM reconforge.pb_prices WHERE tenant_id=%s AND project_id=%s", (billing.base.tenant, project)).fetchone()["id"]
        time = repository.submit_time(TimeSubmission(employee, "2026-10-04", (TimeLine(project, 0, 1),), "One real approved service minute"), command_id="one-minute", actor=actor)
    with billing.actor("checker", private=False) as (_, repository, actor):
        repository.approve_time(time["id"], expected_digest=time["source_digest"], command_id="one-minute-approval", actor=actor)
    plan = prepare(billing, [time["id"]], [price], "one-minute-invoice")
    assert plan["amount_minor"] == 50 and plan["calculation"]["sources"][0]["hourly_price_minor"] == 3001
    observed = ceiling(monkeypatch, permission)
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        getattr(PostgresProjectTimeBillingRepository(connection, billing.base.tenant), read)(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == (
        [Decimal("0.50"), Decimal("0.50"), Decimal("30.01")]
        if permission == "project_time_billing.read" else [Decimal("0.50"), Decimal("30.01")])


def test_queued_role_retirement_blocks_authority_before_any_retained_source_lock(billing: PeopleRuntime) -> None:
    """The blocked revoker cannot form a reader/price-approver lock cycle."""
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from time import monotonic, sleep

    import psycopg

    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    with billing.actor("maker", private=False) as (connection, _, actor):
        project = connection.execute("SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s AND project_code='P2'",
            (billing.base.tenant,)).fetchone()["id"]
        pending = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).register_price(
            ProjectPriceAgreement(SCOPE, "CUSTOMER", project, "2026-11-01", "2026-11-30", "USD", 3001,
                "Original queued approval price"), command_id="queued-price", actor=actor)
    started: Queue[int] = Queue()

    def worker(operation: str) -> str:
        with billing.actor("checker" if operation == "approve_price" else "maker", private=False) as (connection, _, actor):
            connection.execute("SET LOCAL statement_timeout='8s'")
            started.put(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
            try:
                if operation == "approve_price":
                    repository.approve_price(pending["id"], expected_digest=pending["source_digest"],
                        command_id="queued-approval", actor=actor)
                elif operation == "catalog":
                    repository.catalog(SCOPE, actor=actor)
                else:
                    getattr(repository, operation)(plan["id"], actor=actor)
            except FinancePostingError as exc:
                assert "denied" in exc.code
                return exc.code
            pytest.fail("A retired role cannot read or approve the retained source.")

    with psycopg.connect(billing.base.admin_dsn) as revoker, ThreadPoolExecutor(max_workers=4) as pool:
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.execute("""UPDATE reconforge.identity_roles SET active=FALSE,lifecycle_version=lifecycle_version+1,
            retired_at=now(),retired_by='poster' WHERE tenant_id=%s AND name='receipt-operator'""", (billing.base.tenant,))
        futures = [pool.submit(worker, operation) for operation in ("approve_price", "catalog", "get", "evidence")]
        try:
            pids = [started.get(timeout=5) for _ in futures]
            deadline = monotonic() + 5
            with psycopg.connect(billing.base.admin_dsn) as probe:
                while True:
                    blockers = [probe.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0] for pid in pids]
                    if all(revoker_pid in blocked for blocked in blockers):
                        break
                    assert monotonic() < deadline, "Every worker must wait on the retained current-authority lock."
                    sleep(0.02)
                # NOWAIT independently proves that none of the four blocked
                # requests retained a price or plan row lock before authority.
                probe.execute("SELECT id FROM reconforge.pb_prices WHERE tenant_id=%s ORDER BY id FOR UPDATE NOWAIT",
                    (billing.base.tenant,)).fetchall()
                probe.execute("SELECT id FROM reconforge.pb_plans WHERE tenant_id=%s ORDER BY id FOR UPDATE NOWAIT",
                    (billing.base.tenant,)).fetchall()
        finally:
            revoker.commit()
        assert all("denied" in future.result(timeout=8) for future in futures)
    with psycopg.connect(billing.base.admin_dsn) as audit:
        retained = audit.execute("SELECT phase,payload FROM reconforge.pb_plans WHERE tenant_id=%s AND id=%s",
            (billing.base.tenant, plan["id"])).fetchone()
        assert retained[0] == 0 and retained[1]["plan_digest"] == plan["plan_digest"]
        assert audit.execute("SELECT approver_id,source_json FROM reconforge.pb_prices WHERE tenant_id=%s AND id=%s",
            (billing.base.tenant, pending["id"])).fetchone() == (None, {key: value for key, value in pending.items()
                if key not in {"source_digest", "approver_id", "status"}})
