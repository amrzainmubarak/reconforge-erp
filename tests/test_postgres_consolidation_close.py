from __future__ import annotations

import importlib.util
import inspect
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.consolidation_close import (
    ConsolidationCloseRepositoryProtocol,
    build_translation_evidence,
)
from reconforge.application.consolidation_deferred_tax import AcquisitionDeferredTaxApplicationService
from reconforge.application.consolidation_impairment import ConsolidationImpairmentApplicationService
from reconforge.application.consolidation_ownership_change import OwnershipChangeApplicationService
from reconforge.application.consolidation_ppa import AcquisitionPpaApplicationService
from reconforge.domain.intercompany_elimination import prepare_intercompany_eliminations
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, set_local_tenant_scope
from reconforge.infrastructure.postgres_approvals import PostgresApprovalRepository
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL,
    POSTGRES_CONSOLIDATION_DEFERRED_TAX_LINK_SCHEMA_SQL,
    POSTGRES_CONSOLIDATION_IMPAIRMENT_LINK_SCHEMA_SQL,
    POSTGRES_CONSOLIDATION_INTERCOMPANY_LINK_SCHEMA_SQL,
    POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_LINK_SCHEMA_SQL,
    POSTGRES_CONSOLIDATION_PPA_LINK_SCHEMA_SQL,
    PostgresConsolidationCloseRepository,
)
from reconforge.infrastructure.postgres_consolidation_deferred_tax import (
    PostgresConsolidationDeferredTaxRepository,
)
from reconforge.infrastructure.postgres_consolidation_impairment import (
    PostgresConsolidationImpairmentRepository,
)
from reconforge.infrastructure.postgres_consolidation_ownership_change import (
    PostgresConsolidationOwnershipChangeRepository,
)
from reconforge.infrastructure.postgres_consolidation_ppa import PostgresConsolidationPpaRepository
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationRepository,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


class _ScopeCaptureConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.calls.append((query, params))

    @contextmanager
    def transaction(self):
        yield


def test_close_and_approval_repositories_preserve_full_hierarchy_scope() -> None:
    connection = _ScopeCaptureConnection()
    close = PostgresConsolidationCloseRepository(
        connection,
        "tenant-a",
        organization_id="organization-a",
        workspace_id="workspace-a",
        legal_entity_id="entity-a",
    )
    close._scope()
    assert [params for query, params in connection.calls if "set_config" in query] == [
        ("tenant-a",),
        ("organization-a",),
        ("workspace-a",),
        ("entity-a",),
        ("entity-a",),
    ]

    connection.calls.clear()
    approval = PostgresApprovalRepository(
        connection,
        "tenant-a",
        organization_id="organization-a",
        workspace_id="workspace-a",
        legal_entity_id="entity-a",
    )
    with approval._transaction():
        pass
    assert [params for query, params in connection.calls if "set_config" in query] == [
        ("tenant-a",),
        ("organization-a",),
        ("workspace-a",),
        ("entity-a",),
        ("entity-a",),
    ]


def test_close_hierarchy_rejects_entity_without_organization() -> None:
    with pytest.raises(PlatformError, match="requires organization"):
        PostgresConsolidationCloseRepository(None, "tenant-a", legal_entity_id="entity-a")
    with pytest.raises(PlatformError, match="requires organization"):
        PostgresApprovalRepository(None, "tenant-a", legal_entity_id="entity-a")


def test_postgres_consolidation_close_schema_is_tenant_scoped_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL
    assert "JSONB NOT NULL" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting(''app.tenant_id'',true)" in schema
    assert "consolidation_close_run_lines" in schema
    assert "consolidation_close_effect_lines" in schema
    assert "append-only" in schema
    assert "DOUBLE PRECISION" not in schema


def test_postgres_close_intercompany_link_schema_is_immutable_and_tenant_scoped() -> None:
    schema = POSTGRES_CONSOLIDATION_INTERCOMPANY_LINK_SCHEMA_SQL
    assert "consolidation_close_intercompany_links" in schema
    assert "FOREIGN KEY (tenant_id,artifact_id)" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "intercompany links are immutable" in schema
    assert "cannot be deleted" in schema


def test_postgres_close_intercompany_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0064_postgres_close_intercompany_links.py"
    spec = importlib.util.spec_from_file_location("migration_0064", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0064_pg_close_ic_links"
    assert module.down_revision == "0063_pg_ic_elimination"
    assert "refusing to discard close/intercompany evidence links" in path.read_text(encoding="utf-8")


def test_postgres_close_impairment_link_schema_is_immutable_and_tenant_scoped() -> None:
    schema = POSTGRES_CONSOLIDATION_IMPAIRMENT_LINK_SCHEMA_SQL
    assert "consolidation_close_impairment_links" in schema
    assert "consolidation_impairment_artifacts" in schema
    assert "UNIQUE (tenant_id,run_id,entity_code)" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "impairment links are immutable" in schema
    assert "cannot be deleted" in schema


def test_postgres_close_impairment_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0067_postgres_close_impairment_links.py"
    spec = importlib.util.spec_from_file_location("migration_0067", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0067_pg_close_impairment_links"
    assert module.down_revision == "0066_pg_impairment"
    assert "refusing to discard close/impairment evidence links" in path.read_text(encoding="utf-8")


def test_postgres_close_deferred_tax_link_schema_is_immutable_and_tenant_scoped() -> None:
    schema = POSTGRES_CONSOLIDATION_DEFERRED_TAX_LINK_SCHEMA_SQL
    assert "consolidation_close_deferred_tax_links" in schema
    assert "consolidation_deferred_tax_artifacts" in schema
    assert "UNIQUE (tenant_id,run_id,entity_code)" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "deferred-tax links are immutable" in schema
    assert "cannot be deleted" in schema


def test_postgres_close_deferred_tax_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0068_postgres_close_deferred_tax_links.py"
    spec = importlib.util.spec_from_file_location("migration_0068", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0068_pg_close_deferred_tax_links"
    assert module.down_revision == "0067_pg_close_impairment_links"
    assert "refusing to discard close/deferred-tax evidence links" in path.read_text(encoding="utf-8")


def test_postgres_close_ppa_link_schema_is_immutable_and_tenant_scoped() -> None:
    schema = POSTGRES_CONSOLIDATION_PPA_LINK_SCHEMA_SQL
    assert "consolidation_close_ppa_links" in schema
    assert "consolidation_ppa_artifacts" in schema
    assert "UNIQUE (tenant_id,run_id,entity_code)" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "consolidation close PPA links are immutable" in schema
    assert "cannot be deleted" in schema


def test_postgres_close_ppa_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0069_postgres_close_ppa_links.py"
    spec = importlib.util.spec_from_file_location("migration_0069", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0069_pg_close_ppa_links"
    assert module.down_revision == "0068_pg_close_deferred_tax_links"
    assert "refusing to discard close/PPA evidence links" in path.read_text(encoding="utf-8")


def test_postgres_close_ownership_change_link_schema_is_immutable_and_tenant_scoped() -> None:
    schema = POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_LINK_SCHEMA_SQL
    assert "consolidation_close_ownership_change_links" in schema
    assert "consolidation_ownership_change_artifacts" in schema
    assert "UNIQUE (tenant_id,run_id,entity_code)" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "consolidation close ownership-change links are immutable" in schema
    assert "cannot be deleted" in schema


def test_postgres_close_ownership_change_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0071_postgres_close_ownership_change_links.py"
    spec = importlib.util.spec_from_file_location("migration_0071", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0071_pg_close_ownchg_links"
    assert module.down_revision == "0070_pg_ownership_change"
    assert "refusing to discard close/ownership-change evidence links" in path.read_text(encoding="utf-8")


def test_postgres_consolidation_close_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0055_postgres_consolidation_close.py"
    spec = importlib.util.spec_from_file_location("migration_0055", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0055_pg_consol_close"
    assert module.down_revision == "0054_pg_consol_ownership"
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_runs" in path.read_text(encoding="utf-8")


def test_postgres_consolidation_journal_lines_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0057_postgres_consolidation_journal_lines.py"
    spec = importlib.util.spec_from_file_location("migration_0057", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0057_pg_consol_journal_lines"
    assert module.down_revision == "0056_pg_policy_delegations"
    sql = path.read_text(encoding="utf-8")
    assert "journal_line_count" in sql
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_effect_lines" in sql


def test_postgres_adapter_exposes_the_backend_neutral_close_port() -> None:
    required = {
        name
        for name, value in vars(ConsolidationCloseRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    }
    assert required <= set(vars(PostgresConsolidationCloseRepository))
    for name in required:
        assert callable(getattr(PostgresConsolidationCloseRepository, name))
        assert (
            inspect.signature(getattr(PostgresConsolidationCloseRepository, name)).return_annotation
            is not inspect.Signature.empty
        )


def test_postgres_journal_material_is_canonical_and_balanced() -> None:
    from tests.test_sqlite_consolidation_close import _worksheet

    lines, digest = PostgresConsolidationCloseRepository._worksheet_lines(_worksheet())
    assert len(lines) == 2
    assert sum(line["amount_minor"] for line in lines) == 0
    assert {line["amount_decimal"] for line in lines} == {"12.00", "-12.00"}
    assert len(digest) == 64
    restored = PostgresConsolidationCloseRepository._line_material(
        {
            "account_type": "Asset",
            "amount_decimal": "999.000000",
            "amount_minor": 1200,
            "currency_code": "USD",
            "elimination_id": "ELIM-IC-1",
            "entity_code": "SUB",
            "group_account_code": "1000",
            "source_digest": "source",
            "source_line_id": "line",
            "source_reference": "reference",
        }
    )
    assert restored["amount_decimal"] == "12.00"
    assert PostgresConsolidationCloseRepository._amount_matches_minor("12.000000000000000000", 1200, "USD")
    assert not PostgresConsolidationCloseRepository._amount_matches_minor("12.01", 1200, "USD")


def test_translation_evidence_projection_is_backend_neutral() -> None:
    from tests.test_sqlite_consolidation_close import _worksheet

    worksheet = _worksheet()
    evidence = build_translation_evidence(worksheet.request.translation_result).to_dict()

    assert evidence["result_digest"] == worksheet.translation_result_digest
    assert evidence["line_count"] == 4
    assert evidence["source_currencies"] == ["USD"]
    assert len(str(evidence["lineage_digest"])) == 64


def test_management_statement_projection_is_backend_neutral() -> None:
    from reconforge.domain.consolidation_statement import build_management_statement_package
    from tests.test_sqlite_consolidation_close import _worksheet

    worksheet = _worksheet()
    statement = build_management_statement_package(worksheet).to_dict()

    assert statement["worksheet_result_digest"] == worksheet.result_digest
    assert statement["total_balance"]["amount"] == "0.00"
    assert [section["account_type"] for section in statement["sections"]] == sorted(
        section["account_type"] for section in statement["sections"]
    )


def test_intercompany_artifact_binding_requires_exact_replay_match() -> None:
    """A close link must bind the complete deterministic proposal, not only its ID."""

    from dataclasses import replace

    from tests.test_intercompany_elimination import _line
    from tests.test_sqlite_consolidation_close import _worksheet

    base = _worksheet()
    source_lines = (
        _line("TX-A", "PARENT", "SUB", "100.00", account="IC-RECEIVABLE", period="2026-08"),
        _line("TX-B", "SUB", "PARENT", "-100.00", account="IC-PAYABLE", period="2026-08"),
    )
    source = prepare_intercompany_eliminations(
        source_lines,
        reporting_currency="USD",
        prepared_by=base.prepared_by,
        prepared_at=base.prepared_at,
    )
    proposal = source.resolutions[0].proposal
    assert proposal is not None
    # Re-run the pure worksheet builder so its result digest and journal are
    # bound to the intercompany_transaction proposal.
    from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet

    worksheet = prepare_consolidation_worksheet(replace(base.request, eliminations=(proposal,)))
    artifact = {
        "workspace_id": "workspace-a",
        "reporting_currency": "USD",
        "request_payload": {"lines": [line.to_dict() for line in source_lines]},
        "result_payload": source.to_dict(),
    }
    run = {
        "id": "run-a",
        "workspace_id": "workspace-a",
        "period_id": "2026-08",
        "worksheet_object": worksheet,
    }
    repository = PostgresConsolidationCloseRepository(None, "tenant-a")
    matched, unresolved = repository._validate_intercompany_artifact_for_run(run, artifact)
    assert matched == (proposal.elimination_id,)
    assert unresolved == 0
    tampered_result = source.to_dict()
    tampered_resolutions = list(tampered_result["resolutions"])
    tampered_resolutions[0] = {
        **tampered_resolutions[0],
        "proposal": {**tampered_resolutions[0]["proposal"], "rationale": "tampered"},
    }
    tampered_result["resolutions"] = tampered_resolutions
    tampered = {**artifact, "result_payload": tampered_result}
    with pytest.raises(PlatformError, match="proposal does not reproduce"):
        repository._validate_intercompany_artifact_for_run(run, tampered)


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL application role",
)
def test_live_postgres_consolidation_close_is_tenant_isolated_and_replayable() -> None:
    psycopg = pytest.importorskip("psycopg")
    from tests.test_sqlite_consolidation_close import _worksheet

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_a = "pgclose_a_" + uuid4().hex[:10]
    tenant_b = "pgclose_b_" + uuid4().hex[:10]
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.consolidation_close_periods,"
                " reconforge.consolidation_close_runs,reconforge.consolidation_close_effects,"
                " reconforge.consolidation_close_period_events,reconforge.consolidation_close_run_lines,"
                " reconforge.consolidation_close_effect_lines,reconforge.consolidation_close_intercompany_links,"
                " reconforge.consolidation_close_impairment_links,reconforge.consolidation_close_deferred_tax_links,"
                " reconforge.consolidation_close_ppa_links,reconforge.intercompany_elimination_artifacts,"
                " reconforge.consolidation_impairment_artifacts,reconforge.consolidation_deferred_tax_artifacts,"
                " reconforge.consolidation_ppa_artifacts,reconforge.consolidation_ownership_change_artifacts,"
                " reconforge.consolidation_close_ownership_change_links,reconforge.certification_records TO " + app_user
            )
            admin.execute(
                "GRANT SELECT,INSERT,UPDATE ON reconforge.domain_audit_ledger_state,"
                " reconforge.domain_audit_events,reconforge.outbox_events TO " + app_user
            )
            admin.execute(
                "GRANT SELECT,INSERT ON reconforge.identity_users,reconforge.domain_workspaces TO " + app_user
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, "close-ic", "Close intercompany"),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_users("
                "tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    tenant_a,
                    "consolidation-preparer",
                    "consolidation-preparer",
                    "Synthetic consolidation preparer",
                    "x",
                    "x",
                    100000,
                    "pbkdf2_sha256",
                ),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_users("
                "tenant_id,id,username,display_name,password_hash,password_salt,password_iterations,password_algorithm"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s),(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    tenant_a,
                    "impairment-preparer",
                    "impairment-preparer",
                    "Synthetic impairment preparer",
                    "x",
                    "x",
                    100000,
                    "pbkdf2_sha256",
                    tenant_a,
                    "impairment-reviewer",
                    "impairment-reviewer",
                    "Synthetic impairment reviewer",
                    "x",
                    "x",
                    100000,
                    "pbkdf2_sha256",
                ),
            )
    finally:
        admin.close()

    connection = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False)).connect()
    try:
        repository = PostgresConsolidationCloseRepository(connection, tenant_a)
        worksheet = _worksheet()
        period = repository.create_period(
            group_code=worksheet.group_code,
            period_id=worksheet.period_id,
            reporting_currency=worksheet.reporting_currency,
            period_start_date=worksheet.period_start_date,
            period_end_date=worksheet.period_end_date,
            reporting_date=worksheet.reporting_date,
            workspace="close",
            actor_label="period-preparer",
        )
        first = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        replay = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        assert first["id"] == replay["id"]
        approved = repository.approve_run(
            first["id"], expected_version=1, reason="reviewed", actor_label="close-reviewer"
        )
        posted = repository.post_run(
            first["id"], expected_version=approved["row_version"], reason="posted", actor_label="close-poster"
        )
        prepared_certification = repository.prepare_certification(
            posted["id"], note="Posted control-journal evidence prepared.", actor_label="close-certifier"
        )
        assert prepared_certification["status"] == "Prepared"
        with pytest.raises(PlatformError, match="different"):
            repository.review_certification(posted["id"], note="Self review", actor_label="close-certifier")
        reviewed_certification = repository.review_certification(
            posted["id"], note="Independent certification review.", actor_label="close-cert-reviewer"
        )
        assert reviewed_certification["status"] == "Reviewed"
        assert repository.get_certification(posted["id"])["reviewed_by"] == "close-cert-reviewer"
        reversal = repository.request_reversal(
            first["id"],
            expected_version=posted["row_version"],
            reason="correcting",
            actor_label="reversal-preparer",
        )
        repository.approve_reversal(
            first["id"],
            expected_version=reversal["row_version"],
            reason="approved",
            actor_label="reversal-reviewer",
        )
        locked = repository.lock_period(period["id"], expected_version=1, reason="close", actor_label="period-reviewer")
        assert locked["status"] == "Locked"
        with pytest.raises(PlatformError, match="independent"):
            repository.reopen_period(
                period["id"],
                expected_version=locked["row_version"],
                reason="same actor",
                actor_label="period-reviewer",
            )
        reopened = repository.reopen_period(
            period["id"],
            expected_version=locked["row_version"],
            reason="controlled reopen",
            actor_label="period-reopener",
        )
        assert reopened["status"] == "Open"
        assert repository.summary(workspace="close").reversed_runs == 1
        detail = repository.get_run(first["id"])
        assert detail["worksheet"]["worksheet_id"] == worksheet.worksheet_id
        assert len(detail["journal_lines"]) == 2
        assert {str(line["currency_code"]) for line in detail["journal_lines"]} == {"USD"}
        assert {str(effect["effect_type"]) for effect in detail["effects"]} == {"Posting", "Reversal"}
        assert all(str(effect["status"]) == "Committed" for effect in detail["effects"])
        assert all(len(effect["lines"]) == 2 for effect in detail["effects"])

        # A prepared close can bind one replay-verified, explicitly non-posting
        # impairment artifact for an entity represented in the worksheet.
        from tests.test_consolidation_impairment import _request

        impairment_request = _request(
            entity_code="SUB",
            period_id=worksheet.period_id,
            prepared_by="impairment-preparer",
            approved_by="impairment-reviewer",
        )
        impairment_artifact = ConsolidationImpairmentApplicationService(
            PostgresConsolidationImpairmentRepository(connection, tenant_a)
        ).prepare_and_persist(impairment_request, actor_label="impairment-preparer")
        impairment_run = repository.prepare_run(
            run_number="RUN-IMP-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        impairment_link = repository.attach_impairment_artifact(
            impairment_run["id"], impairment_artifact["id"], workspace="close", actor_label="close-reviewer"
        )
        assert impairment_link["artifact_id"] == impairment_artifact["id"]
        impairment_detail = repository.get_run(impairment_run["id"])
        assert impairment_detail["impairment_evidence"][0]["artifact_result_digest"] == impairment_artifact[
            "result_digest"
        ]
        assert impairment_detail["close_bundle"]["impairment_artifact_digests"] == [
            impairment_artifact["result_digest"]
        ]

        from tests.test_consolidation_deferred_tax import _request as deferred_tax_request

        deferred_request = deferred_tax_request(
            subsidiary_entity_code="SUB",
            period_id=worksheet.period_id,
            prepared_by="impairment-preparer",
            approved_by="impairment-reviewer",
        )
        deferred_artifact = AcquisitionDeferredTaxApplicationService(
            PostgresConsolidationDeferredTaxRepository(connection, tenant_a)
        ).prepare_and_persist(deferred_request, actor_label="impairment-preparer")
        deferred_run = repository.prepare_run(
            run_number="RUN-DTAX-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        deferred_link = repository.attach_deferred_tax_artifact(
            deferred_run["id"], deferred_artifact["id"], workspace="close", actor_label="close-reviewer"
        )
        assert deferred_link["artifact_id"] == deferred_artifact["id"]
        deferred_detail = repository.get_run(deferred_run["id"])
        assert deferred_detail["deferred_tax_evidence"][0]["artifact_result_digest"] == deferred_artifact[
            "result_digest"
        ]
        assert deferred_detail["close_bundle"]["deferred_tax_artifact_digests"] == [
            deferred_artifact["result_digest"]
        ]

        from tests.test_consolidation_ppa import _request as ppa_request

        ppa_artifact = AcquisitionPpaApplicationService(
            PostgresConsolidationPpaRepository(connection, tenant_a)
        ).prepare_and_persist(
            ppa_request(
                subsidiary_entity_code="SUB",
                period_id=worksheet.period_id,
                prepared_by="impairment-preparer",
                approved_by="impairment-reviewer",
            ),
            actor_label="impairment-preparer",
        )
        ppa_run = repository.prepare_run(
            run_number="RUN-PPA-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        ppa_link = repository.attach_ppa_artifact(
            ppa_run["id"], ppa_artifact["id"], workspace="close", actor_label="close-reviewer"
        )
        assert ppa_link["artifact_id"] == ppa_artifact["id"]
        ppa_detail = repository.get_run(ppa_run["id"])
        assert ppa_detail["ppa_evidence"][0]["artifact_result_digest"] == ppa_artifact["result_digest"]
        assert ppa_detail["close_bundle"]["ppa_artifact_digests"] == [ppa_artifact["result_digest"]]

        from dataclasses import replace

        from tests.test_consolidation_ownership_changes import _request as ownership_change_request

        ownership_artifact = OwnershipChangeApplicationService(
            PostgresConsolidationOwnershipChangeRepository(connection, tenant_a)
        ).prepare_and_persist(
            replace(
                ownership_change_request(),
                period_id=worksheet.period_id,
                effective_date="2026-08-01",
                prepared_by="impairment-preparer",
                approved_by="impairment-reviewer",
            ),
            actor_label="impairment-preparer",
        )
        ownership_run = repository.prepare_run(
            run_number="RUN-OWNCHG-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        ownership_link = repository.attach_ownership_change_artifact(
            ownership_run["id"],
            ownership_artifact["id"],
            workspace="close",
            actor_label="close-reviewer",
        )
        assert ownership_link["artifact_id"] == ownership_artifact["id"]
        ownership_detail = repository.get_run(ownership_run["id"])
        assert ownership_detail["ownership_change_evidence"][0]["artifact_result_digest"] == ownership_artifact[
            "result_digest"
        ]
        assert ownership_detail["close_bundle"]["ownership_change_artifact_digests"] == [
            ownership_artifact["result_digest"]
        ]

        # A prepared run with intercompany_transaction eliminations cannot be
        # approved until its exact PostgreSQL proposal artifact is bound.
        from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
        from tests.test_intercompany_elimination import _line

        source_lines = (
            _line("TX-A", "PARENT", "SUB", "100.00", account="IC-RECEIVABLE", period="2026-08"),
            _line("TX-B", "SUB", "PARENT", "-100.00", account="IC-PAYABLE", period="2026-08"),
        )
        source_result = prepare_intercompany_eliminations(
            source_lines,
            reporting_currency="USD",
            prepared_by=worksheet.prepared_by,
            prepared_at=worksheet.prepared_at,
        )
        proposal = source_result.resolutions[0].proposal
        assert proposal is not None
        intercompany_worksheet = prepare_consolidation_worksheet(
            replace(worksheet.request, eliminations=(proposal,))
        )
        intercompany_repo = PostgresIntercompanyEliminationRepository(connection, tenant_a)
        artifact = intercompany_repo.persist(
            source_lines,
            source_result,
            workspace="close-ic",
            actor_label=worksheet.prepared_by,
        )
        intercompany_period = repository.create_period(
            group_code=intercompany_worksheet.group_code,
            period_id=intercompany_worksheet.period_id,
            reporting_currency=intercompany_worksheet.reporting_currency,
            period_start_date=intercompany_worksheet.period_start_date,
            period_end_date=intercompany_worksheet.period_end_date,
            reporting_date=intercompany_worksheet.reporting_date,
            workspace="close-ic",
            actor_label="period-preparer",
        )
        intercompany_run = repository.prepare_run(
            run_number="RUN-IC-001",
            worksheet=intercompany_worksheet,
            workspace="close-ic",
            actor_label=intercompany_worksheet.prepared_by,
        )
        linked = repository.attach_intercompany_artifact(
            intercompany_run["id"], artifact["id"], actor_label="intercompany-linker"
        )
        assert linked["artifact_id"] == artifact["id"]
        approved_intercompany = repository.approve_run(
            intercompany_run["id"], expected_version=1, reason="Evidence linked", actor_label="close-reviewer-ic"
        )
        assert approved_intercompany["status"] == "Approved"
        intercompany_detail = repository.get_run(intercompany_run["id"])
        assert intercompany_detail["intercompany_evidence"][0]["artifact_result_digest"] == source_result.result_digest
        assert intercompany_detail["close_bundle"]["intercompany_artifact_digests"] == [source_result.result_digest]
        assert intercompany_period["workspace_id"] == "close-ic"
        with connection.transaction():
            set_local_tenant_scope(connection, tenant_a)
            with pytest.raises(psycopg.Error, match="append-only"):
                connection.execute(
                    "UPDATE reconforge.consolidation_close_run_lines "
                    "SET amount_minor=amount_minor+1 WHERE tenant_id=%s AND run_id=%s",
                    (tenant_a, first["id"]),
                )
        with connection.transaction():
            set_local_tenant_scope(connection, tenant_a)
            events = connection.execute(
                "SELECT action,actor FROM reconforge.consolidation_close_period_events WHERE tenant_id=%s AND period_id=%s ORDER BY created_at,id",
                (tenant_a, period["id"]),
            ).fetchall()
        assert [(str(item["action"]), str(item["actor"])) for item in events] == [
            ("Locked", "period-reviewer"),
            ("Open", "period-reopener"),
        ]
        with pytest.raises(PlatformError, match="not found"):
            PostgresConsolidationCloseRepository(connection, tenant_b).get_period(period["id"])
    finally:
        connection.close()
