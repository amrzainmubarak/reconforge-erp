"""Native read-only reconciliation over the same approved wage/billing time."""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection
from reconforge.infrastructure.postgres_project_source_reconciliation import (
    PostgresProjectSourceReconciliationRepository,
)
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository
from tests.test_postgres_people_project_payroll import SCOPE, PeopleRuntime, approved_budget, commit
from tests.test_postgres_people_project_payroll import prepare as prepare_wage
from tests.test_postgres_project_time_billing import post, prepare, sources

pytest_plugins = ("tests.test_postgres_project_time_billing",)


def collection(runtime: PeopleRuntime, invoice: dict[str, Any], amount: int, command: str) -> dict[str, Any]:
    with runtime.actor("maker", private=False) as (connection, _, actor):
        return PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).prepare_collection(
            invoice["id"],
            amount_minor=amount,
            period_id="period",
            posting_date="2026-10-06",
            command_id=command,
            actor=actor,
        )


def completed_pair(runtime: PeopleRuntime) -> tuple[str, str, str]:
    times, prices = sources(runtime)
    budget = approved_budget(runtime)
    wage = prepare_wage(runtime, times, budget, "report-wage")
    invoice = prepare(runtime, times, prices, "report-invoice")
    commit(runtime, wage, "report-wage")
    post(runtime, invoice, "report-invoice")
    with runtime.actor("maker") as (connection, repository, actor):
        people = repository.evidence(wage["id"], actor=actor)["payrun"]["private"]["employees"]
        first = next(row["employee_id"] for row in people if row["gross_minor"] == 1502)
        second = next(row["employee_id"] for row in people if row["gross_minor"] == 999)
        partial = repository.prepare_payment(
            wage["id"],
            employees_minor={first: 1000},
            period_id="period",
            posting_date="2026-10-05",
            command_id="report-wage-partial",
            actor=actor,
        )
    commit(runtime, partial, "report-wage-partial")
    with runtime.actor("maker") as (_, repository, actor):
        final = repository.prepare_payment(
            wage["id"],
            employees_minor={first: 502, second: 999},
            period_id="period",
            posting_date="2026-10-06",
            command_id="report-wage-final",
            actor=actor,
        )
    commit(runtime, final, "report-wage-final")
    post(runtime, collection(runtime, invoice, 1000, "report-invoice-partial"), "report-invoice-partial")
    post(runtime, collection(runtime, invoice, 5236, "report-invoice-final"), "report-invoice-final")
    with runtime.actor("maker", private=False) as (connection, _, _):
        project = connection.execute(
            "SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s AND project_code='P1'", (runtime.base.tenant,)
        ).fetchone()["id"]
    return wage["id"], invoice["id"], project


def selection(pair: tuple[str, str, str]) -> ProjectSourceSelection:
    wage, invoice, project = pair
    return ProjectSourceSelection(SCOPE, project, "period", wage, invoice)


def test_actual_project_wage_revenue_and_separate_whole_source_cash_read_without_private_rows(
    billing: PeopleRuntime, monkeypatch
) -> None:
    import reconforge.infrastructure.postgres_project_source_reconciliation as adapter

    original_reconcile = adapter.reconcile_project_sources

    def capture_original(subject, original):
        directory = Path(__file__).resolve().parents[1] / "output/project-source-native-inputs"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ("original-" + uuid4().hex + ".json")).open("x", encoding="utf8") as handle:
            json.dump(
                {"status": "captured-before-domain-admission", "original_rows": original},
                handle,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        return original_reconcile(subject, original)

    monkeypatch.setattr(adapter, "reconcile_project_sources", capture_original)
    pair = completed_pair(billing)
    with billing.actor("maker", private=False) as (connection, _, actor):
        before = connection.execute(
            "SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (billing.base.tenant,)
        ).fetchone()["n"]
        repository = PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant)
        proof = repository.report(selection(pair), actor=actor)
        repeated = repository.report(selection(pair), actor=actor)
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s",
                (billing.base.tenant,),
            ).fetchone()["n"]
            == before
            == 6
        )
    report = proof["report"]
    assert report["project_totals"] == {
        "wage_cost_minor": "1268",
        "revenue_minor": "2535",
        "source_margin_minor": "1267",
    }
    assert report["whole_source_settlement"] == {
        "wage_accrued_minor": "2501",
        "wage_paid_minor": "2501",
        "wage_liability_minor": "0",
        "invoice_minor": "6236",
        "collected_minor": "6236",
        "ar_outstanding_minor": "0",
        "per_project_cash_allocated": False,
    }
    assert repeated["report"]["report_digest"] == report["report_digest"]
    assert len(report["source_membership"]) == 6 and len(report["approved_time"]) == 2
    pending: list[Any] = [proof]
    forbidden = {"private", "employee_id", "employee_name", "hourly_rate_minor", "employees", "employees_minor"}
    while pending:
        value = pending.pop()
        if type(value) is dict:
            assert not forbidden.intersection(value)
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
    directory = Path(__file__).resolve().parents[1] / "output/project-source-native"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ("original-" + uuid4().hex + ".json")).open("x", encoding="utf8") as handle:
        json.dump(proof, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    origins = []
    root = Path(__file__).resolve().parents[1]
    for name in (
        "reconforge.domain.project_source_reconciliation",
        "reconforge.infrastructure.postgres_project_source_reconciliation",
        "reconforge.infrastructure.postgres_people_project_payroll",
        "reconforge.infrastructure.postgres_project_time_billing",
        "reconforge.infrastructure.postgres_finance_posting",
        "reconforge.infrastructure.postgres_operational_finance",
    ):
        path = Path(sys.modules[name].__file__).resolve()
        assert path.is_relative_to(root)
        raw = path.read_bytes()
        origins.append(
            {
                "module": name,
                "relative_path": path.relative_to(root).as_posix(),
                "physical_bytes": len(raw),
                "physical_sha256": hashlib.sha256(raw).hexdigest(),
                "normalized_source_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
            }
        )
    with (directory / ("origins-" + uuid4().hex + ".json")).open("x", encoding="utf8") as handle:
        json.dump(
            {
                "schema_version": "project-source-native-import-subject-v1",
                "original_evidence_digest": proof["evidence_digest"],
                "runtime_root": str(root),
                "module_origins": origins,
            },
            handle,
            sort_keys=True,
            separators=(",", ":"),
        )


def test_private_personnel_factory_is_refused_by_the_ordinary_aggregate_report(billing: PeopleRuntime) -> None:
    pair = completed_pair(billing)
    with billing.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).report(
            selection(pair), actor=actor
        )
    assert refused.value.code == "project_reconciliation_invalid"


def test_current_amount_permissions_cached_revocation_and_foreign_selection_refuse(
    billing: PeopleRuntime, monkeypatch
) -> None:
    import psycopg

    from tests.test_postgres_project_time_billing_read_authority import ceiling

    pair = completed_pair(billing)
    permissions = ("project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read")
    for permission in permissions:
        with monkeypatch.context() as context:
            observed = ceiling(context, permission)
            with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError):
                PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).report(
                    selection(pair), actor=actor
                )
            assert observed
    with billing.actor("maker", private=False) as (connection, _, actor):
        foreign = ProjectSourceSelection(SCOPE, "foreign-project", "period", pair[0], pair[1])
        with pytest.raises((FinancePostingError, KeyError)):
            PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).report(foreign, actor=actor)
        # The principal was authenticated before the persisted retirement.
        with psycopg.connect(billing.base.admin_dsn) as admin:
            admin.execute(
                """UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change'
                WHERE tenant_id=%s AND permission_name='finance_core.read'""",
                (billing.base.tenant,),
            )
        with pytest.raises(FinancePostingError) as refused:
            PostgresProjectSourceReconciliationRepository(connection, billing.base.tenant).report(
                selection(pair), actor=actor
            )
        assert "denied" in refused.value.code
