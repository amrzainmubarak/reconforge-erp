"""Tenant-scoped PostgreSQL control-journal persistence for consolidation close.

This adapter deliberately persists the verified worksheet and lifecycle effects as
canonical JSONB.  It is a control ledger boundary; it is not an ERP write-back or
statutory consolidation posting engine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from reconforge.application.consolidation_close import build_translation_evidence
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_close_bundle import build_consolidation_close_bundle
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationWorksheetResult,
    verify_consolidation_worksheet_payload,
)
from reconforge.domain.consolidation_statement import build_management_statement_package
from reconforge.infrastructure.postgres import (
    set_local_tenant_scope,
    validate_legal_entity_id,
    validate_organization_id,
    validate_tenant_id,
    validate_workspace_id,
)
from reconforge.infrastructure.postgres_approvals import PostgresApprovalRepository
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
from reconforge.platform.common import PlatformError, normalize_text, platform_id
from reconforge.platform.inventory_values import MAX_AMOUNT_MINOR
from reconforge.utils.money import Money


class JournalLineMaterial(TypedDict):
    account_type: str
    amount_decimal: str
    amount_minor: int
    currency_code: str
    elimination_id: str
    entity_code: str
    group_account_code: str
    source_digest: str
    source_line_id: str
    source_reference: str


class EffectLineMaterial(TypedDict):
    amount_minor: int
    currency_code: str
    run_line_id: str

POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_periods (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, group_code TEXT NOT NULL,
 period_name TEXT NOT NULL, reporting_currency TEXT NOT NULL, period_start_date DATE NOT NULL,
 period_end_date DATE NOT NULL, reporting_date DATE NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
 row_version INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,group_code,period_name), CHECK (status IN ('Open','Locked')),
 CHECK (period_start_date<=reporting_date AND reporting_date<=period_end_date)
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_runs (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, period_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 run_number TEXT NOT NULL, worksheet_payload JSONB NOT NULL, worksheet_digest TEXT NOT NULL,
 journal_digest TEXT NOT NULL, journal_line_count INTEGER NOT NULL DEFAULT 0 CHECK (journal_line_count >= 0),
 status TEXT NOT NULL DEFAULT 'Prepared', row_version INTEGER NOT NULL DEFAULT 1,
 prepared_by TEXT NOT NULL, approved_by TEXT, posted_by TEXT, reversal_requested_by TEXT, reversed_by TEXT,
 prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(), approved_at TIMESTAMPTZ, posted_at TIMESTAMPTZ,
 reversal_requested_at TIMESTAMPTZ, reversed_at TIMESTAMPTZ, reasons JSONB NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,period_id,run_number),
 CHECK (status IN ('Prepared','Approved','Posted','ReversalPrepared','Reversed'))
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_effects (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, effect_type TEXT NOT NULL,
 source_effect_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Legacy',
 line_count INTEGER NOT NULL DEFAULT 0 CHECK (line_count >= 0), actor TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), effect_digest TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,effect_type)
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_period_events (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, period_id TEXT NOT NULL, action TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_run_lines (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 elimination_id TEXT NOT NULL, source_line_id TEXT NOT NULL, entity_code TEXT NOT NULL,
 group_account_code TEXT NOT NULL, account_type TEXT NOT NULL, amount_decimal NUMERIC(38,18) NOT NULL,
 amount_minor BIGINT NOT NULL, currency_code TEXT NOT NULL, source_reference TEXT NOT NULL,
 source_digest TEXT NOT NULL, PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,run_id,ordinal), FOREIGN KEY (tenant_id,run_id)
  REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE CASCADE,
 CHECK (ordinal >= 1), CHECK (amount_minor <> 0), CHECK (currency_code ~ '^[A-Z]{3}$')
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_effect_lines (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, effect_id TEXT NOT NULL, run_line_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, amount_decimal NUMERIC(38,18) NOT NULL, amount_minor BIGINT NOT NULL,
 currency_code TEXT NOT NULL, PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,effect_id,ordinal),
 FOREIGN KEY (tenant_id,effect_id) REFERENCES reconforge.consolidation_close_effects(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,run_line_id) REFERENCES reconforge.consolidation_close_run_lines(tenant_id,id) ON DELETE RESTRICT,
 CHECK (ordinal >= 1), CHECK (amount_minor <> 0), CHECK (currency_code ~ '^[A-Z]{3}$')
);
CREATE INDEX IF NOT EXISTS consolidation_close_runs_scope_idx ON reconforge.consolidation_close_runs(tenant_id,workspace_id,status);
CREATE INDEX IF NOT EXISTS consolidation_close_run_lines_run_idx ON reconforge.consolidation_close_run_lines(tenant_id,run_id,ordinal);
CREATE INDEX IF NOT EXISTS consolidation_close_effect_lines_effect_idx ON reconforge.consolidation_close_effect_lines(tenant_id,effect_id,ordinal);
ALTER TABLE reconforge.consolidation_close_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_periods FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effects FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_period_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_period_events FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_run_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_run_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effect_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effect_lines FORCE ROW LEVEL SECURITY;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['consolidation_close_periods','consolidation_close_runs','consolidation_close_effects','consolidation_close_period_events','consolidation_close_run_lines','consolidation_close_effect_lines'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', t);
 EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))', t);
END LOOP; END $$;
CREATE OR REPLACE FUNCTION reconforge.reject_consolidation_close_child_mutation()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
 RAISE EXCEPTION 'consolidation close child rows are append-only';
END;
$fn$;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['consolidation_close_effects','consolidation_close_run_lines','consolidation_close_effect_lines'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS %I_immutable ON reconforge.%I', t, t);
 EXECUTE format('CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.reject_consolidation_close_child_mutation()', t, t);
END LOOP; END $$;
"""


POSTGRES_CONSOLIDATION_INTERCOMPANY_LINK_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_intercompany_links (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
 artifact_result_digest TEXT NOT NULL CHECK (artifact_result_digest ~ '^[a-f0-9]{64}$'),
 matched_elimination_ids JSONB NOT NULL CHECK (jsonb_typeof(matched_elimination_ids) = 'array'),
 unresolved_count INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_count >= 0),
 link_digest TEXT NOT NULL CHECK (link_digest ~ '^[a-f0-9]{64}$'), actor TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,artifact_id),
 FOREIGN KEY (tenant_id,run_id) REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY (tenant_id,artifact_id) REFERENCES reconforge.intercompany_elimination_artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_close_ic_links_run_idx
 ON reconforge.consolidation_close_intercompany_links(tenant_id,run_id,created_at,id);
ALTER TABLE reconforge.consolidation_close_intercompany_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_intercompany_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_close_intercompany_links;
CREATE POLICY tenant_scope ON reconforge.consolidation_close_intercompany_links
 USING (tenant_id = current_setting('app.tenant_id', true))
 WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_close_intercompany_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  RAISE EXCEPTION 'consolidation close intercompany links are immutable' USING ERRCODE='check_violation';
 END IF;
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'consolidation close intercompany links cannot be deleted' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_close_intercompany_link_guard
 ON reconforge.consolidation_close_intercompany_links;
CREATE TRIGGER consolidation_close_intercompany_link_guard
 BEFORE UPDATE OR DELETE ON reconforge.consolidation_close_intercompany_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_close_intercompany_link();
"""


POSTGRES_CONSOLIDATION_IMPAIRMENT_LINK_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_impairment_links (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
 artifact_result_digest TEXT NOT NULL CHECK (artifact_result_digest ~ '^[a-f0-9]{64}$'),
 entity_code TEXT NOT NULL, link_digest TEXT NOT NULL CHECK (link_digest ~ '^[a-f0-9]{64}$'),
 actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,artifact_id), UNIQUE (tenant_id,run_id,entity_code),
 FOREIGN KEY (tenant_id,run_id) REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY (tenant_id,artifact_id) REFERENCES reconforge.consolidation_impairment_artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_close_impairment_links_run_idx
 ON reconforge.consolidation_close_impairment_links(tenant_id,run_id,created_at,id);
ALTER TABLE reconforge.consolidation_close_impairment_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_impairment_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_close_impairment_links;
CREATE POLICY tenant_scope ON reconforge.consolidation_close_impairment_links
 USING (tenant_id = current_setting('app.tenant_id', true))
 WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_close_impairment_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  RAISE EXCEPTION 'consolidation close impairment links are immutable' USING ERRCODE='check_violation';
 END IF;
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'consolidation close impairment links cannot be deleted' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_close_impairment_link_guard
 ON reconforge.consolidation_close_impairment_links;
CREATE TRIGGER consolidation_close_impairment_link_guard
 BEFORE UPDATE OR DELETE ON reconforge.consolidation_close_impairment_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_close_impairment_link();
"""


POSTGRES_CONSOLIDATION_DEFERRED_TAX_LINK_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_deferred_tax_links (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
 artifact_result_digest TEXT NOT NULL CHECK (artifact_result_digest ~ '^[a-f0-9]{64}$'),
 entity_code TEXT NOT NULL, link_digest TEXT NOT NULL CHECK (link_digest ~ '^[a-f0-9]{64}$'),
 actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,artifact_id), UNIQUE (tenant_id,run_id,entity_code),
 FOREIGN KEY (tenant_id,run_id) REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY (tenant_id,artifact_id) REFERENCES reconforge.consolidation_deferred_tax_artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_close_deferred_tax_links_run_idx
 ON reconforge.consolidation_close_deferred_tax_links(tenant_id,run_id,created_at,id);
ALTER TABLE reconforge.consolidation_close_deferred_tax_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_deferred_tax_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_close_deferred_tax_links;
CREATE POLICY tenant_scope ON reconforge.consolidation_close_deferred_tax_links
 USING (tenant_id = current_setting('app.tenant_id', true))
 WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_close_deferred_tax_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  RAISE EXCEPTION 'consolidation close deferred-tax links are immutable' USING ERRCODE='check_violation';
 END IF;
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'consolidation close deferred-tax links cannot be deleted' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_close_deferred_tax_link_guard
 ON reconforge.consolidation_close_deferred_tax_links;
CREATE TRIGGER consolidation_close_deferred_tax_link_guard
 BEFORE UPDATE OR DELETE ON reconforge.consolidation_close_deferred_tax_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_close_deferred_tax_link();
"""


POSTGRES_CONSOLIDATION_PPA_LINK_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_ppa_links (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
 artifact_result_digest TEXT NOT NULL CHECK (artifact_result_digest ~ '^[a-f0-9]{64}$'),
 entity_code TEXT NOT NULL, link_digest TEXT NOT NULL CHECK (link_digest ~ '^[a-f0-9]{64}$'),
 actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,artifact_id), UNIQUE (tenant_id,run_id,entity_code),
 FOREIGN KEY (tenant_id,run_id) REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY (tenant_id,artifact_id) REFERENCES reconforge.consolidation_ppa_artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_close_ppa_links_run_idx
 ON reconforge.consolidation_close_ppa_links(tenant_id,run_id,created_at,id);
ALTER TABLE reconforge.consolidation_close_ppa_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_ppa_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_close_ppa_links;
CREATE POLICY tenant_scope ON reconforge.consolidation_close_ppa_links
 USING (tenant_id = current_setting('app.tenant_id', true))
 WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_close_ppa_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  RAISE EXCEPTION 'consolidation close PPA links are immutable' USING ERRCODE='check_violation';
 END IF;
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'consolidation close PPA links cannot be deleted' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_close_ppa_link_guard
 ON reconforge.consolidation_close_ppa_links;
CREATE TRIGGER consolidation_close_ppa_link_guard
 BEFORE UPDATE OR DELETE ON reconforge.consolidation_close_ppa_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_close_ppa_link();
"""


POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_LINK_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_ownership_change_links (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
 artifact_result_digest TEXT NOT NULL CHECK (artifact_result_digest ~ '^[a-f0-9]{64}$'),
 entity_code TEXT NOT NULL, link_digest TEXT NOT NULL CHECK (link_digest ~ '^[a-f0-9]{64}$'),
 actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,artifact_id), UNIQUE (tenant_id,run_id,entity_code),
 FOREIGN KEY (tenant_id,run_id) REFERENCES reconforge.consolidation_close_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY (tenant_id,artifact_id)
   REFERENCES reconforge.consolidation_ownership_change_artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_close_ownership_change_links_run_idx
 ON reconforge.consolidation_close_ownership_change_links(tenant_id,run_id,created_at,id);
ALTER TABLE reconforge.consolidation_close_ownership_change_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_ownership_change_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_close_ownership_change_links;
CREATE POLICY tenant_scope ON reconforge.consolidation_close_ownership_change_links
 USING (tenant_id = current_setting('app.tenant_id', true))
 WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_close_ownership_change_link()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  RAISE EXCEPTION 'consolidation close ownership-change links are immutable' USING ERRCODE='check_violation';
 END IF;
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'consolidation close ownership-change links cannot be deleted' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_close_ownership_change_link_guard
 ON reconforge.consolidation_close_ownership_change_links;
CREATE TRIGGER consolidation_close_ownership_change_link_guard
 BEFORE UPDATE OR DELETE ON reconforge.consolidation_close_ownership_change_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_close_ownership_change_link();
"""


class PostgresConsolidationCloseRepository:
    def __init__(
        self,
        connection: Any,
        tenant_id: str,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.organization_id = validate_organization_id(organization_id)
        self.workspace_id = validate_workspace_id(workspace_id)
        self.legal_entity_id = validate_legal_entity_id(legal_entity_id)
        if self.legal_entity_id is not None and self.organization_id is None:
            raise PlatformError("Consolidation close legal-entity scope requires organization scope.")

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("Consolidation actor is required.")
        return actor

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)

    def _scope(self) -> None:
        set_local_tenant_scope(
            self.connection,
            self.tenant_id,
            self.organization_id,
            workspace_id=self.workspace_id,
            legal_entity_id=self.legal_entity_id,
        )

    @staticmethod
    def _worksheet_lines(
        worksheet: ConsolidationWorksheetResult,
    ) -> tuple[list[JournalLineMaterial], str]:
        """Materialize balanced control-journal lines from a verified worksheet."""

        lines: list[JournalLineMaterial] = []
        for elimination in worksheet.eliminations:
            for line in elimination.lines:
                if line.amount.currency != worksheet.reporting_currency:
                    raise PlatformError("Consolidation journal lines must use the worksheet reporting currency.")
                minor = line.amount.to_minor_units()
                if minor == 0 or abs(minor) > MAX_AMOUNT_MINOR:
                    raise PlatformError("Consolidation journal line exceeds the supported amount range.")
                lines.append(
                    {
                        "account_type": line.account_type,
                        "amount_decimal": str(line.amount.to_canonical_dict()["amount"]),
                        "amount_minor": minor,
                        "currency_code": line.amount.currency,
                        "elimination_id": elimination.elimination_id,
                        "entity_code": line.entity_code,
                        "group_account_code": line.group_account_code,
                        "source_digest": line.source_digest,
                        "source_line_id": line.line_id,
                        "source_reference": line.source_reference,
                    }
                )
        lines.sort(key=lambda item: (str(item["elimination_id"]), str(item["source_line_id"])))
        if not 2 <= len(lines) <= 10_000:
            raise PlatformError("Persisted consolidation journals require between 2 and 10000 lines.")
        if sum(line["amount_minor"] for line in lines) != 0:
            raise PlatformError("Persisted consolidation journal lines must balance exactly in minor units.")
        digest_material: dict[str, object] = {
            "schema_version": 1,
            "worksheet_result_digest": worksheet.result_digest,
            "lines": lines,
        }
        digest = hashlib.sha256(
            json.dumps(digest_material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        return lines, digest

    @staticmethod
    def _line_material(row: Mapping[str, Any]) -> JournalLineMaterial:
        currency_code = str(row["currency_code"])
        amount_minor = int(row["amount_minor"])
        canonical_amount = Money.from_minor_units(amount_minor, currency_code).to_canonical_dict()["amount"]
        return {
            "account_type": str(row["account_type"]),
            "amount_decimal": str(canonical_amount),
            "amount_minor": amount_minor,
            "currency_code": currency_code,
            "elimination_id": str(row["elimination_id"]),
            "entity_code": str(row["entity_code"]),
            "group_account_code": str(row["group_account_code"]),
            "source_digest": str(row["source_digest"]),
            "source_line_id": str(row["source_line_id"]),
            "source_reference": str(row["source_reference"]),
        }

    @staticmethod
    def _amount_matches_minor(amount_decimal: Any, amount_minor: int, currency_code: str) -> bool:
        expected = Money.from_minor_units(amount_minor, currency_code).to_canonical_dict()["amount"]
        try:
            actual_decimal = Decimal(str(amount_decimal))
            expected_decimal = Decimal(str(expected))
        except (InvalidOperation, ValueError):
            return False
        return actual_decimal.is_finite() and actual_decimal == expected_decimal

    def _run_lines(
        self,
        run_id: str,
        worksheet: ConsolidationWorksheetResult,
        *,
        persist_legacy_fallback: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_run_lines "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY ordinal",
            (self.tenant_id, run_id),
        ).fetchall()
        expected_material, expected_digest = self._worksheet_lines(worksheet)
        expected_lines: list[dict[str, Any]] = [dict(line) for line in expected_material]
        if not rows:
            # Pre-0057 rows did not have a line table. Reads replay the
            # verified worksheet; a later governed effect transition may
            # materialize those exact lines inside the same transaction.
            if persist_legacy_fallback:
                for ordinal, line in enumerate(expected_lines, 1):
                    self.connection.execute(
                        "INSERT INTO reconforge.consolidation_close_run_lines("
                        "tenant_id,id,run_id,ordinal,elimination_id,source_line_id,entity_code,"
                        "group_account_code,account_type,amount_decimal,amount_minor,currency_code,"
                        "source_reference,source_digest"
                        ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            self.tenant_id,
                            platform_id("PGCCL", run_id, ordinal),
                            run_id,
                            ordinal,
                            line["elimination_id"],
                            line["source_line_id"],
                            line["entity_code"],
                            line["group_account_code"],
                            line["account_type"],
                            line["amount_decimal"],
                            line["amount_minor"],
                            line["currency_code"],
                            line["source_reference"],
                            line["source_digest"],
                        ),
                    )
                rows = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_run_lines "
                    "WHERE tenant_id=%s AND run_id=%s ORDER BY ordinal",
                    (self.tenant_id, run_id),
                ).fetchall()
                return [self._line_material(row) | {"id": str(row["id"]), "ordinal": int(row["ordinal"])} for row in rows], expected_digest
            return expected_lines, expected_digest
        actual_material: list[dict[str, Any]] = [dict(self._line_material(row)) for row in rows]
        if (
            actual_material != expected_lines
            or len(rows) != len(expected_lines)
            or any(
                not self._amount_matches_minor(row["amount_decimal"], int(row["amount_minor"]), str(row["currency_code"]))
                for row in rows
            )
        ):
            raise PlatformError("Persisted consolidation journal lines do not reproduce the worksheet.")
        actual_lines = [
            material | {"id": str(row["id"]), "ordinal": int(row["ordinal"])}
            for material, row in zip(actual_material, rows, strict=True)
        ]
        return actual_lines, expected_digest

    def _create_effect(
        self,
        run: Mapping[str, Any],
        *,
        effect_type: str,
        actor: str,
        run_lines: Sequence[Mapping[str, Any]],
    ) -> None:
        if effect_type not in {"Posting", "Reversal"}:
            raise PlatformError("Unsupported consolidation effect type.")
        run_id = str(run["id"])
        if len(run_lines) != int(run.get("journal_line_count", len(run_lines))):
            raise PlatformError("Consolidation run line count changed before effect creation.")
        source_effect_id = ""
        if effect_type == "Reversal":
            source = self.connection.execute(
                "SELECT id FROM reconforge.consolidation_close_effects "
                "WHERE tenant_id=%s AND run_id=%s AND effect_type='Posting' "
                "AND status IN ('Committed','Legacy')",
                (self.tenant_id, run_id),
            ).fetchone()
            if source is None:
                raise PlatformError("A committed posting effect is required before reversal.")
            source_effect_id = str(source["id"])
        sign = 1 if effect_type == "Posting" else -1
        material_lines: list[EffectLineMaterial] = [
            {
                "amount_minor": sign * int(row["amount_minor"]),
                "currency_code": str(row["currency_code"]),
                "run_line_id": str(row["id"]),
            }
            for row in run_lines
        ]
        effect_id = platform_id("PGCCE", self.tenant_id, run_id, effect_type)
        effect_digest = hashlib.sha256(
            self._json(
                {
                    "effect_type": effect_type,
                    "lines": material_lines,
                    "run_id": run_id,
                    "schema_version": 1,
                    "source_effect_id": source_effect_id,
                }
            ).encode("ascii")
        ).hexdigest()
        self.connection.execute(
            "INSERT INTO reconforge.consolidation_close_effects("
            "tenant_id,id,run_id,effect_type,source_effect_id,status,line_count,actor,effect_digest"
            ") VALUES(%s,%s,%s,%s,%s,'Committed',%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                self.tenant_id,
                effect_id,
                run_id,
                effect_type,
                source_effect_id,
                len(material_lines),
                actor,
                effect_digest,
            ),
        )
        for ordinal, (row, material) in enumerate(zip(run_lines, material_lines, strict=True), 1):
            amount = Money.from_minor_units(material["amount_minor"], material["currency_code"])
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_effect_lines("
                "tenant_id,id,effect_id,run_line_id,ordinal,amount_decimal,amount_minor,currency_code"
                ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    platform_id("PGCCEL", effect_id, ordinal),
                    effect_id,
                    str(row["id"]),
                    ordinal,
                    str(amount.to_canonical_dict()["amount"]),
                    material["amount_minor"],
                    material["currency_code"],
                ),
            )

    def create_period(
        self,
        *,
        group_code: str,
        period_id: str,
        reporting_currency: str,
        period_start_date: str,
        period_end_date: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        workspace = normalize_text(workspace, default="default")
        group_code = normalize_text(group_code, default="")
        period_id = normalize_text(period_id, default="")
        if not group_code or not period_id or not reporting_currency:
            raise PlatformError("Consolidation period fields are required.")
        identifier = platform_id("PGCCP", self.tenant_id, workspace, group_code, period_id)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, identifier),
            ).fetchone()
            if row:
                return dict(row)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_periods(tenant_id,id,workspace_id,group_code,period_name,reporting_currency,period_start_date,period_end_date,reporting_date,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    identifier,
                    workspace,
                    group_code,
                    period_id,
                    reporting_currency,
                    period_start_date,
                    period_end_date,
                    reporting_date,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
            )

    def prepare_run(
        self,
        *,
        run_number: str,
        worksheet: ConsolidationWorksheetResult,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("A verified consolidation worksheet is required.")
        try:
            verified = verify_consolidation_worksheet_payload(worksheet.to_dict())
        except ConsolidationError as exc:
            raise PlatformError("Consolidation worksheet replay failed before persistence.") from exc
        if verified.prepared_by != actor or verified.posting_effect != "none":
            raise PlatformError("Worksheet preparation policy rejected the actor or posting effect.")
        lines, journal_digest = self._worksheet_lines(verified)
        period_id = platform_id("PGCCP", self.tenant_id, workspace, verified.group_code, verified.period_id)
        run_id = platform_id("PGCGR", self.tenant_id, workspace, verified.group_code, verified.period_id, run_number)
        payload = verified.to_dict()
        digest = hashlib.sha256(self._json(payload).encode()).hexdigest()
        with self.connection.transaction():
            self._scope()
            period = self.connection.execute(
                "SELECT status FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_id),
            ).fetchone()
            if not period:
                raise PlatformError("Consolidation period does not exist.")
            if str(period[0]) == "Locked":
                raise PlatformError("A locked consolidation period cannot accept a new run.")
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, run_id),
            ).fetchone()
            if existing:
                if str(existing["worksheet_digest"]) != digest or str(existing["prepared_by"]) != actor:
                    raise PlatformError("Consolidation run identifier conflicts with immutable worksheet evidence.")
                return dict(existing)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_runs("
                "tenant_id,id,period_id,workspace_id,run_number,worksheet_payload,worksheet_digest,"
                "journal_digest,journal_line_count,prepared_by"
                ") VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    run_id,
                    period_id,
                    workspace,
                    run_number,
                    self._json(payload),
                    digest,
                    journal_digest,
                    len(lines),
                    actor,
                ),
            )
            for ordinal, line in enumerate(lines, 1):
                self.connection.execute(
                    "INSERT INTO reconforge.consolidation_close_run_lines("
                    "tenant_id,id,run_id,ordinal,elimination_id,source_line_id,entity_code,"
                    "group_account_code,account_type,amount_decimal,amount_minor,currency_code,"
                    "source_reference,source_digest"
                    ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.tenant_id,
                        platform_id("PGCCL", run_id, ordinal),
                        run_id,
                        ordinal,
                        line["elimination_id"],
                        line["source_line_id"],
                        line["entity_code"],
                        line["group_account_code"],
                        line["account_type"],
                        line["amount_decimal"],
                        line["amount_minor"],
                        line["currency_code"],
                        line["source_reference"],
                        line["source_digest"],
                    ),
                )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, run_id),
                ).fetchone()
            )

    def _transition(
        self,
        run_id: str,
        expected_version: int,
        from_status: str,
        to_status: str,
        reason: str,
        actor_label: str,
        actor_field: str,
        effect_kind: str | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if not row or row["status"] != from_status or int(row["row_version"]) != expected_version:
                raise PlatformError("Consolidation run changed concurrently or has an invalid state.")
            if (
                actor == row["prepared_by"]
                or actor == row["approved_by"]
                or (actor_field in {"reversed_by"} and actor == row["posted_by"])
            ):
                raise PlatformError("Maker-checker actor separation rejected the transition.")
            if effect_kind:
                verified = self._verified_run(dict(row))
                run_lines, _ = self._run_lines(
                    run_id,
                    verified["worksheet_object"],
                    persist_legacy_fallback=True,
                )
                self._create_effect(
                    verified,
                    effect_type=effect_kind,
                    actor=actor,
                    run_lines=run_lines,
                )
            elif from_status == "Prepared" and to_status == "Approved":
                verified = self._verified_run(dict(row))
                expected_intercompany = {
                    item.elimination_id
                    for item in verified["worksheet_object"].eliminations
                    if item.elimination_type == "intercompany_transaction"
                }
                linked_intercompany = {
                    elimination_id
                    for evidence in verified.get("intercompany_evidence", [])
                    for elimination_id in evidence["matched_elimination_ids"]
                }
                if expected_intercompany != linked_intercompany:
                    raise PlatformError(
                        "Every intercompany worksheet elimination requires a replay-verified source artifact before approval."
                    )
            self.connection.execute(
                f"UPDATE reconforge.consolidation_close_runs SET status=%s,row_version=row_version+1,{actor_field}=%s,reasons=jsonb_set(reasons,ARRAY[%s]::text[],to_jsonb(%s::text),true) WHERE tenant_id=%s AND id=%s",  # nosec B608
                (to_status, actor, to_status.lower() + "_reason", reason, self.tenant_id, run_id),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, run_id),
                ).fetchone()
            )

    def approve_run(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        # Intercompany eliminations are only approvable after their immutable
        # source artifact has been bound to the close worksheet.  The check is
        # intentionally in the transition transaction so a concurrent attach
        # cannot race an approval.
        return self._transition(run_id, expected_version, "Prepared", "Approved", reason, actor_label, "approved_by")

    def post_run(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id, expected_version, "Approved", "Posted", reason, actor_label, "posted_by", effect_kind="Posting"
        )

    def request_reversal(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id, expected_version, "Posted", "ReversalPrepared", reason, actor_label, "reversal_requested_by"
        )

    def approve_reversal(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id,
            expected_version,
            "ReversalPrepared",
            "Reversed",
            reason,
            actor_label,
            "reversed_by",
            effect_kind="Reversal",
        )

    def prepare_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Prepare certification only for a replay-verified posted run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            run = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if run is None:
                raise PlatformError("Consolidation run not found.")
            verified = self._verified_run(dict(run))
            if str(verified["status"]) not in {"Posted", "Reversed"}:
                raise PlatformError("Only a posted or reversed consolidation run can be certified.")
            period = self.connection.execute(
                "SELECT period_name,group_code FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, str(verified["period_id"])),
            ).fetchone()
            if period is None:
                raise PlatformError("Consolidation period not found.")
            return PostgresApprovalRepository(
                self.connection,
                self.tenant_id,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                legal_entity_id=self.legal_entity_id,
            ).prepare_certification(
                object_type="consolidation_close_run",
                object_id=str(verified["id"]),
                period_name=str(period["period_name"]),
                entity_code=str(period["group_code"]),
                note=note,
                actor_label=actor,
            )

    def review_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Review posted-run certification with PostgreSQL maker-checker guard."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            run = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if run is None:
                raise PlatformError("Consolidation run not found.")
            verified = self._verified_run(dict(run))
            if str(verified["status"]) not in {"Posted", "Reversed"}:
                raise PlatformError("Only a posted or reversed consolidation run can be certified.")
            return PostgresApprovalRepository(
                self.connection,
                self.tenant_id,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                legal_entity_id=self.legal_entity_id,
            ).review_certification(
                object_type="consolidation_close_run",
                object_id=str(verified["id"]),
                note=note,
                actor_label=actor,
            )

    def get_certification(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Replay-verify the run before exposing its PostgreSQL certification."""

        del actor_label
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            self._verified_run(dict(row))
            return PostgresApprovalRepository(
                self.connection,
                self.tenant_id,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                legal_entity_id=self.legal_entity_id,
            )._certification(
                "consolidation_close_run", run_id
            )

    def lock_period(
        self, period_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._period_transition(period_id, expected_version, "Open", "Locked", reason, actor_label)

    def reopen_period(
        self, period_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._period_transition(period_id, expected_version, "Locked", "Open", reason, actor_label)

    def _period_transition(
        self, period_id: str, expected_version: int, old: str, new: str, reason: str, actor_label: str
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        reason_text = self._actor(reason)
        with self.connection.transaction():
            self._scope()
            current = self.connection.execute(
                "SELECT status,row_version FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, period_id),
            ).fetchone()
            if current is None:
                raise PlatformError("Consolidation period not found.")
            if str(current["status"]) != old or int(current["row_version"]) != expected_version:
                raise PlatformError("Consolidation period changed concurrently or has an invalid state.")
            if new == "Open":
                locker = self.connection.execute(
                    "SELECT actor FROM reconforge.consolidation_close_period_events WHERE tenant_id=%s AND period_id=%s AND action='Locked' ORDER BY created_at DESC,id DESC LIMIT 1",
                    (self.tenant_id, period_id),
                ).fetchone()
                if locker is not None and str(locker["actor"]) == actor:
                    raise PlatformError("Period reopen requires an actor independent of the period locker.")
            updated = self.connection.execute(
                "UPDATE reconforge.consolidation_close_periods SET status=%s,row_version=row_version+1,updated_at=now() WHERE tenant_id=%s AND id=%s AND status=%s AND row_version=%s",
                (new, self.tenant_id, period_id, old, expected_version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation period changed concurrently or has an invalid state.")
            event_id = platform_id("PGCCPE", self.tenant_id, period_id, new, expected_version + 1)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_period_events(tenant_id,id,period_id,action,actor,reason) VALUES(%s,%s,%s,%s,%s,%s)",
                (self.tenant_id, event_id, period_id, new, actor, reason_text),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, period_id),
                ).fetchone()
            )

    def get_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_id),
            ).fetchone()
            return dict(row) if row else (_ for _ in ()).throw(PlatformError("Consolidation period not found."))

    def list_periods(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        with self.connection.transaction():
            self._scope()
            return [
                dict(r)
                for r in self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND workspace_id=%s ORDER BY period_name LIMIT %s OFFSET %s",
                    (self.tenant_id, workspace, limit, offset),
                ).fetchall()
            ]

    def get_run(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            return self._verified_run(dict(row))

    @staticmethod
    def _worksheet_elimination_payload(item: Any) -> dict[str, object]:
        """Return the exact proposal fields used for artifact binding."""

        return {
            "elimination_id": item.elimination_id,
            "elimination_type": item.elimination_type,
            "lines": [line.to_input_dict() for line in item.lines],
            "prepared_at": item.prepared_at,
            "prepared_by": item.prepared_by,
            "rationale": item.rationale,
            "version": item.version,
        }

    def _intercompany_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, artifact_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Intercompany elimination artifact was not found.")
        try:
            return PostgresIntercompanyEliminationRepository._decode_row(row)
        except Exception as exc:
            raise PlatformError("Persisted intercompany evidence failed replay verification.") from exc

    def _validate_intercompany_artifact_for_run(
        self,
        run: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], int]:
        worksheet = run.get("worksheet_object")
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("Consolidation worksheet replay object is missing.")
        if str(artifact.get("workspace_id")) != str(run.get("workspace_id")):
            raise PlatformError("Intercompany evidence workspace does not match the consolidation run.")
        if str(artifact.get("reporting_currency")) != worksheet.reporting_currency:
            raise PlatformError("Intercompany evidence currency does not match the consolidation run.")
        request_payload = artifact.get("request_payload")
        if not isinstance(request_payload, Mapping):
            raise PlatformError("Intercompany evidence request payload is invalid.")
        # `run["period_id"]` is the internal PostgreSQL period row identity
        # (`PGCCP-*`), while source evidence carries the business period name
        # (for example, `2026-08`). Bind the artifact to the replay-verified
        # worksheet period instead of comparing unlike identifiers.
        if any(
            str(line.get("period_name")) != str(worksheet.period_id)
            for line in request_payload.get("lines", [])
            if isinstance(line, Mapping)
        ):
            raise PlatformError("Intercompany evidence period does not match the consolidation run.")
        resolutions = artifact.get("result_payload", {}).get("resolutions")
        if not isinstance(resolutions, list):
            raise PlatformError("Intercompany evidence resolutions are invalid.")
        worksheet_items = {
            item.elimination_id: item
            for item in worksheet.eliminations
            if item.elimination_type == "intercompany_transaction"
        }
        proposed_ids: list[str] = []
        for resolution in resolutions:
            if not isinstance(resolution, Mapping) or resolution.get("status") != "proposed":
                continue
            proposal = resolution.get("proposal")
            if not isinstance(proposal, Mapping):
                raise PlatformError("Intercompany proposed resolution is invalid.")
            elimination_id = str(proposal.get("elimination_id", ""))
            worksheet_item = worksheet_items.get(elimination_id)
            if worksheet_item is None or self._json(dict(proposal)) != self._json(
                self._worksheet_elimination_payload(worksheet_item)
            ):
                raise PlatformError("Intercompany evidence proposal does not reproduce the worksheet elimination.")
            proposed_ids.append(elimination_id)
        matched_ids = tuple(sorted(proposed_ids))
        if not matched_ids:
            raise PlatformError("Intercompany evidence contains no proposed elimination for this run.")
        if len(set(matched_ids)) != len(matched_ids):
            raise PlatformError("Intercompany evidence contains duplicate proposed eliminations.")
        unresolved_count = sum(
            1 for resolution in resolutions if isinstance(resolution, Mapping) and resolution.get("status") == "unresolved"
        )
        return matched_ids, unresolved_count

    def _verified_intercompany_links(
        self,
        run: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_intercompany_links "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY created_at,id",
            (self.tenant_id, str(run["id"])),
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen_eliminations: set[str] = set()
        for raw in rows:
            item = dict(raw)
            artifact = self._intercompany_artifact(str(item["artifact_id"]))
            matched_ids, unresolved_count = self._validate_intercompany_artifact_for_run(run, artifact)
            stored_ids = item.get("matched_elimination_ids")
            if isinstance(stored_ids, str):
                try:
                    stored_ids = json.loads(stored_ids)
                except json.JSONDecodeError as exc:
                    raise PlatformError("Persisted intercompany link IDs are invalid.") from exc
            if not isinstance(stored_ids, list) or tuple(sorted(str(value) for value in stored_ids)) != matched_ids:
                raise PlatformError("Persisted intercompany link does not reproduce its artifact proposals.")
            if seen_eliminations.intersection(matched_ids):
                raise PlatformError("An intercompany worksheet elimination is linked more than once.")
            seen_eliminations.update(matched_ids)
            link_material = {
                "artifact_id": str(item["artifact_id"]),
                "artifact_result_digest": str(artifact["result_digest"]),
                "matched_elimination_ids": list(matched_ids),
                "run_id": str(run["id"]),
                "schema_version": 1,
            }
            expected_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if (
                str(item.get("artifact_result_digest")) != str(artifact["result_digest"])
                or int(item.get("unresolved_count", 0)) != unresolved_count
                or not hmac.compare_digest(expected_digest, str(item.get("link_digest")))
            ):
                raise PlatformError("Persisted intercompany close link failed digest verification.")
            result.append(
                {
                    "id": str(item["id"]),
                    "artifact_id": str(item["artifact_id"]),
                    "artifact_result_digest": str(artifact["result_digest"]),
                    "matched_elimination_ids": list(matched_ids),
                    "unresolved_count": unresolved_count,
                    "link_digest": str(item["link_digest"]),
                    "actor": str(item["actor"]),
                    "created_at": str(item["created_at"]),
                    "posting": "not_available",
                }
            )
        return result

    def attach_intercompany_artifact(
        self,
        run_id: str,
        artifact_id: str,
        *,
        workspace: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Bind an immutable intercompany artifact to a prepared close run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            run = self._verified_run(dict(row))
            if workspace is not None and str(run["workspace_id"]) != normalize_text(workspace, default=""):
                raise PlatformError("Workspace scope is not authorized.")
            if str(run["status"]) != "Prepared":
                raise PlatformError("Intercompany evidence can only be attached to a prepared run.")
            artifact = self._intercompany_artifact(artifact_id)
            matched_ids, unresolved_count = self._validate_intercompany_artifact_for_run(run, artifact)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_intercompany_links "
                "WHERE tenant_id=%s AND run_id=%s AND artifact_id=%s",
                (self.tenant_id, run_id, artifact_id),
            ).fetchone()
            link_material = {
                "artifact_id": artifact_id,
                "artifact_result_digest": str(artifact["result_digest"]),
                "matched_elimination_ids": list(matched_ids),
                "run_id": run_id,
                "schema_version": 1,
            }
            link_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if existing is not None:
                if str(existing["link_digest"]) != link_digest:
                    raise PlatformError("Intercompany close link conflicts with immutable evidence.")
                return dict(existing)
            if any(
                elimination_id in {
                    linked_id
                    for evidence in run.get("intercompany_evidence", [])
                    for linked_id in evidence["matched_elimination_ids"]
                }
                for elimination_id in matched_ids
            ):
                raise PlatformError("An intercompany worksheet elimination is already linked to this run.")
            link_id = platform_id("PGCCIL", self.tenant_id, run_id, artifact_id)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_intercompany_links("
                "tenant_id,id,run_id,artifact_id,artifact_result_digest,matched_elimination_ids,"
                "unresolved_count,link_digest,actor) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (
                    self.tenant_id,
                    link_id,
                    run_id,
                    artifact_id,
                    artifact["result_digest"],
                    self._json(list(matched_ids)),
                    unresolved_count,
                    link_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_intercompany_links WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, link_id),
                ).fetchone()
            )

    def _impairment_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_impairment_artifacts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, artifact_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Impairment evidence artifact was not found.")
        try:
            return PostgresConsolidationImpairmentRepository._decode_row(row)
        except Exception as exc:
            raise PlatformError("Persisted impairment evidence failed replay verification.") from exc

    def _validate_impairment_artifact_for_run(
        self,
        run: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> str:
        worksheet = run.get("worksheet_object")
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("Consolidation worksheet replay object is missing.")
        if str(artifact.get("reporting_currency")) != worksheet.reporting_currency:
            raise PlatformError("Impairment evidence currency does not match the consolidation run.")
        if str(artifact.get("period_id")) != str(worksheet.period_id):
            raise PlatformError("Impairment evidence period does not match the consolidation run.")
        entity_code = str(artifact.get("entity_code", ""))
        worksheet_entities = {line.entity_code for item in worksheet.eliminations for line in item.lines}
        if entity_code not in worksheet_entities:
            raise PlatformError("Impairment evidence entity is not present in the consolidation worksheet.")
        return entity_code

    def _verified_impairment_links(self, run: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_impairment_links "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY created_at,id",
            (self.tenant_id, str(run["id"])),
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw in rows:
            item = dict(raw)
            artifact = self._impairment_artifact(str(item["artifact_id"]))
            entity_code = self._validate_impairment_artifact_for_run(run, artifact)
            if entity_code in seen_entities:
                raise PlatformError("An impairment entity is linked more than once to this run.")
            seen_entities.add(entity_code)
            link_material = {
                "artifact_id": str(item["artifact_id"]),
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": str(run["id"]),
                "schema_version": 1,
            }
            expected_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if (
                str(item.get("artifact_result_digest")) != str(artifact["result_digest"])
                or str(item.get("entity_code")) != entity_code
                or not hmac.compare_digest(expected_digest, str(item.get("link_digest")))
            ):
                raise PlatformError("Persisted impairment close link failed digest verification.")
            result_payload = artifact.get("result_payload")
            if not isinstance(result_payload, Mapping):
                raise PlatformError("Persisted impairment result payload is invalid.")
            result.append(
                {
                    "id": str(item["id"]),
                    "artifact_id": str(item["artifact_id"]),
                    "artifact_result_digest": str(artifact["result_digest"]),
                    "entity_code": entity_code,
                    "period_id": str(artifact["period_id"]),
                    "reporting_currency": str(artifact["reporting_currency"]),
                    "total_impairment_loss": result_payload.get("total_impairment_loss"),
                    "posted": result_payload.get("posted"),
                    "link_digest": str(item["link_digest"]),
                    "actor": str(item["actor"]),
                    "created_at": str(item["created_at"]),
                }
            )
        return result

    def attach_impairment_artifact(
        self,
        run_id: str,
        artifact_id: str,
        *,
        workspace: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Bind immutable, non-posting impairment evidence to a prepared close run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            run = self._verified_run(dict(row))
            if workspace is not None and str(run["workspace_id"]) != normalize_text(workspace, default=""):
                raise PlatformError("Workspace scope is not authorized.")
            if str(run["status"]) != "Prepared":
                raise PlatformError("Impairment evidence can only be attached to a prepared run.")
            if actor == str(run["prepared_by"]):
                raise PlatformError("Impairment evidence linking requires an actor independent of the run preparer.")
            artifact = self._impairment_artifact(artifact_id)
            entity_code = self._validate_impairment_artifact_for_run(run, artifact)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_impairment_links "
                "WHERE tenant_id=%s AND run_id=%s AND artifact_id=%s",
                (self.tenant_id, run_id, artifact_id),
            ).fetchone()
            link_material = {
                "artifact_id": artifact_id,
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": run_id,
                "schema_version": 1,
            }
            link_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if existing is not None:
                if str(existing["link_digest"]) != link_digest:
                    raise PlatformError("Impairment close link conflicts with immutable evidence.")
                return dict(existing)
            if any(
                entity_code == str(evidence["entity_code"])
                for evidence in run.get("impairment_evidence", [])
            ):
                raise PlatformError("An impairment entity is already linked to this run.")
            link_id = platform_id("PGCCIL", self.tenant_id, run_id, artifact_id, "impairment")
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_impairment_links("
                "tenant_id,id,run_id,artifact_id,artifact_result_digest,entity_code,link_digest,actor) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    link_id,
                    run_id,
                    artifact_id,
                    artifact["result_digest"],
                    entity_code,
                    link_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_impairment_links WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, link_id),
                ).fetchone()
            )

    def _deferred_tax_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_deferred_tax_artifacts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, artifact_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Deferred-tax evidence artifact was not found.")
        try:
            return PostgresConsolidationDeferredTaxRepository._decode_row(row)
        except Exception as exc:
            raise PlatformError("Persisted deferred-tax evidence failed replay verification.") from exc

    def _validate_deferred_tax_artifact_for_run(
        self,
        run: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> str:
        worksheet = run.get("worksheet_object")
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("Consolidation worksheet replay object is missing.")
        if str(artifact.get("reporting_currency")) != worksheet.reporting_currency:
            raise PlatformError("Deferred-tax evidence currency does not match the consolidation run.")
        if str(artifact.get("period_id")) != str(worksheet.period_id):
            raise PlatformError("Deferred-tax evidence period does not match the consolidation run.")
        entity_code = str(artifact.get("subsidiary_entity_code", ""))
        worksheet_entities = {line.entity_code for item in worksheet.eliminations for line in item.lines}
        if entity_code not in worksheet_entities:
            raise PlatformError("Deferred-tax evidence entity is not present in the consolidation worksheet.")
        return entity_code

    def _verified_deferred_tax_links(self, run: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_deferred_tax_links "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY created_at,id",
            (self.tenant_id, str(run["id"])),
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw in rows:
            item = dict(raw)
            artifact = self._deferred_tax_artifact(str(item["artifact_id"]))
            entity_code = self._validate_deferred_tax_artifact_for_run(run, artifact)
            if entity_code in seen_entities:
                raise PlatformError("A deferred-tax entity is linked more than once to this run.")
            seen_entities.add(entity_code)
            link_material = {
                "artifact_id": str(item["artifact_id"]),
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": str(run["id"]),
                "schema_version": 1,
            }
            expected_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if (
                str(item.get("artifact_result_digest")) != str(artifact["result_digest"])
                or str(item.get("entity_code")) != entity_code
                or not hmac.compare_digest(expected_digest, str(item.get("link_digest")))
            ):
                raise PlatformError("Persisted deferred-tax close link failed digest verification.")
            result_payload = artifact.get("result_payload")
            if not isinstance(result_payload, Mapping):
                raise PlatformError("Persisted deferred-tax result payload is invalid.")
            result.append(
                {
                    "id": str(item["id"]),
                    "artifact_id": str(item["artifact_id"]),
                    "artifact_result_digest": str(artifact["result_digest"]),
                    "entity_code": entity_code,
                    "period_id": str(artifact["period_id"]),
                    "reporting_currency": str(artifact["reporting_currency"]),
                    "net_deferred_tax": result_payload.get("net_deferred_tax"),
                    "posted": result_payload.get("posted"),
                    "link_digest": str(item["link_digest"]),
                    "actor": str(item["actor"]),
                    "created_at": str(item["created_at"]),
                }
            )
        return result

    def attach_deferred_tax_artifact(
        self,
        run_id: str,
        artifact_id: str,
        *,
        workspace: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Bind immutable, non-posting deferred-tax evidence to a prepared close run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            run = self._verified_run(dict(row))
            if workspace is not None and str(run["workspace_id"]) != normalize_text(workspace, default=""):
                raise PlatformError("Workspace scope is not authorized.")
            if str(run["status"]) != "Prepared":
                raise PlatformError("Deferred-tax evidence can only be attached to a prepared run.")
            if actor == str(run["prepared_by"]):
                raise PlatformError("Deferred-tax evidence linking requires an actor independent of the run preparer.")
            artifact = self._deferred_tax_artifact(artifact_id)
            entity_code = self._validate_deferred_tax_artifact_for_run(run, artifact)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_deferred_tax_links "
                "WHERE tenant_id=%s AND run_id=%s AND artifact_id=%s",
                (self.tenant_id, run_id, artifact_id),
            ).fetchone()
            link_material = {
                "artifact_id": artifact_id,
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": run_id,
                "schema_version": 1,
            }
            link_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if existing is not None:
                if str(existing["link_digest"]) != link_digest:
                    raise PlatformError("Deferred-tax close link conflicts with immutable evidence.")
                return dict(existing)
            if any(
                entity_code == str(evidence["entity_code"])
                for evidence in run.get("deferred_tax_evidence", [])
            ):
                raise PlatformError("A deferred-tax entity is already linked to this run.")
            link_id = platform_id("PGCCDTL", self.tenant_id, run_id, artifact_id)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_deferred_tax_links("
                "tenant_id,id,run_id,artifact_id,artifact_result_digest,entity_code,link_digest,actor) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    link_id,
                    run_id,
                    artifact_id,
                    artifact["result_digest"],
                    entity_code,
                    link_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_deferred_tax_links WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, link_id),
                ).fetchone()
            )

    def _ppa_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_ppa_artifacts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, artifact_id),
        ).fetchone()
        if row is None:
            raise PlatformError("PPA evidence artifact was not found.")
        try:
            return PostgresConsolidationPpaRepository._decode_row(row)
        except Exception as exc:
            raise PlatformError("Persisted PPA evidence failed replay verification.") from exc

    def _validate_ppa_artifact_for_run(
        self,
        run: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> str:
        worksheet = run.get("worksheet_object")
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("Consolidation worksheet replay object is missing.")
        if str(artifact.get("reporting_currency")) != worksheet.reporting_currency:
            raise PlatformError("PPA evidence currency does not match the consolidation run.")
        if str(artifact.get("period_id")) != str(worksheet.period_id):
            raise PlatformError("PPA evidence period does not match the consolidation run.")
        entity_code = str(artifact.get("subsidiary_entity_code", ""))
        worksheet_entities = {line.entity_code for item in worksheet.eliminations for line in item.lines}
        if entity_code not in worksheet_entities:
            raise PlatformError("PPA evidence entity is not present in the consolidation worksheet.")
        return entity_code

    def _verified_ppa_links(self, run: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_ppa_links "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY created_at,id",
            (self.tenant_id, str(run["id"])),
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw in rows:
            item = dict(raw)
            artifact = self._ppa_artifact(str(item["artifact_id"]))
            entity_code = self._validate_ppa_artifact_for_run(run, artifact)
            if entity_code in seen_entities:
                raise PlatformError("A PPA entity is linked more than once to this run.")
            seen_entities.add(entity_code)
            link_material = {
                "artifact_id": str(item["artifact_id"]),
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": str(run["id"]),
                "schema_version": 1,
            }
            expected_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if (
                str(item.get("artifact_result_digest")) != str(artifact["result_digest"])
                or str(item.get("entity_code")) != entity_code
                or not hmac.compare_digest(expected_digest, str(item.get("link_digest")))
            ):
                raise PlatformError("Persisted PPA close link failed digest verification.")
            result_payload = artifact.get("result_payload")
            if not isinstance(result_payload, Mapping):
                raise PlatformError("Persisted PPA result payload is invalid.")
            result.append(
                {
                    "id": str(item["id"]),
                    "artifact_id": str(item["artifact_id"]),
                    "artifact_result_digest": str(artifact["result_digest"]),
                    "entity_code": entity_code,
                    "period_id": str(artifact["period_id"]),
                    "reporting_currency": str(artifact["reporting_currency"]),
                    "fair_value_adjustment": result_payload.get("fair_value_adjustment"),
                    "posted": result_payload.get("posted"),
                    "link_digest": str(item["link_digest"]),
                    "actor": str(item["actor"]),
                    "created_at": str(item["created_at"]),
                }
            )
        return result

    def attach_ppa_artifact(
        self,
        run_id: str,
        artifact_id: str,
        *,
        workspace: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Bind immutable, non-posting PPA evidence to a prepared close run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            run = self._verified_run(dict(row))
            if workspace is not None and str(run["workspace_id"]) != normalize_text(workspace, default=""):
                raise PlatformError("Workspace scope is not authorized.")
            if str(run["status"]) != "Prepared":
                raise PlatformError("PPA evidence can only be attached to a prepared run.")
            if actor == str(run["prepared_by"]):
                raise PlatformError("PPA evidence linking requires an actor independent of the run preparer.")
            artifact = self._ppa_artifact(artifact_id)
            entity_code = self._validate_ppa_artifact_for_run(run, artifact)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_ppa_links "
                "WHERE tenant_id=%s AND run_id=%s AND artifact_id=%s",
                (self.tenant_id, run_id, artifact_id),
            ).fetchone()
            link_material = {
                "artifact_id": artifact_id,
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": run_id,
                "schema_version": 1,
            }
            link_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if existing is not None:
                if str(existing["link_digest"]) != link_digest:
                    raise PlatformError("PPA close link conflicts with immutable evidence.")
                return dict(existing)
            if any(entity_code == str(evidence["entity_code"]) for evidence in run.get("ppa_evidence", [])):
                raise PlatformError("A PPA entity is already linked to this run.")
            link_id = platform_id("PGCPPAL", self.tenant_id, run_id, artifact_id)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_ppa_links("
                "tenant_id,id,run_id,artifact_id,artifact_result_digest,entity_code,link_digest,actor) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    link_id,
                    run_id,
                    artifact_id,
                    artifact["result_digest"],
                    entity_code,
                    link_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_ppa_links WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, link_id),
                ).fetchone()
            )

    def _ownership_change_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_ownership_change_artifacts "
            "WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, artifact_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Ownership-change evidence artifact was not found.")
        try:
            return PostgresConsolidationOwnershipChangeRepository._decode_row(row)
        except Exception as exc:
            raise PlatformError("Persisted ownership-change evidence failed replay verification.") from exc

    def _validate_ownership_change_artifact_for_run(
        self,
        run: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> str:
        worksheet = run.get("worksheet_object")
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("Consolidation worksheet replay object is missing.")
        if str(artifact.get("reporting_currency")) != worksheet.reporting_currency:
            raise PlatformError("Ownership-change evidence currency does not match the consolidation run.")
        if str(artifact.get("period_id")) != str(worksheet.period_id):
            raise PlatformError("Ownership-change evidence period does not match the consolidation run.")
        entity_code = str(artifact.get("subsidiary_entity_code", ""))
        worksheet_entities = {line.entity_code for item in worksheet.eliminations for line in item.lines}
        if entity_code not in worksheet_entities:
            raise PlatformError(
                "Ownership-change evidence entity is not present in the consolidation worksheet."
            )
        return entity_code

    def _verified_ownership_change_links(self, run: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_ownership_change_links "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY created_at,id",
            (self.tenant_id, str(run["id"])),
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw in rows:
            item = dict(raw)
            artifact = self._ownership_change_artifact(str(item["artifact_id"]))
            entity_code = self._validate_ownership_change_artifact_for_run(run, artifact)
            if entity_code in seen_entities:
                raise PlatformError("An ownership-change entity is linked more than once to this run.")
            seen_entities.add(entity_code)
            link_material = {
                "artifact_id": str(item["artifact_id"]),
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": str(run["id"]),
                "schema_version": 1,
            }
            expected_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if (
                str(item.get("artifact_result_digest")) != str(artifact["result_digest"])
                or str(item.get("entity_code")) != entity_code
                or not hmac.compare_digest(expected_digest, str(item.get("link_digest")))
            ):
                raise PlatformError("Persisted ownership-change close link failed digest verification.")
            result_payload = artifact.get("result_payload")
            if not isinstance(result_payload, Mapping):
                raise PlatformError("Persisted ownership-change result payload is invalid.")
            result.append(
                {
                    "id": str(item["id"]),
                    "artifact_id": str(item["artifact_id"]),
                    "artifact_result_digest": str(artifact["result_digest"]),
                    "entity_code": entity_code,
                    "period_id": str(artifact["period_id"]),
                    "reporting_currency": str(artifact["reporting_currency"]),
                    "nci_rounding_delta": result_payload.get("nci_rounding_delta"),
                    "posted": result_payload.get("posted"),
                    "link_digest": str(item["link_digest"]),
                    "actor": str(item["actor"]),
                    "created_at": str(item["created_at"]),
                }
            )
        return result

    def attach_ownership_change_artifact(
        self,
        run_id: str,
        artifact_id: str,
        *,
        workspace: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Bind immutable, non-posting ownership-change evidence to a prepared close run."""

        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Consolidation run not found.")
            run = self._verified_run(dict(row))
            if workspace is not None and str(run["workspace_id"]) != normalize_text(workspace, default=""):
                raise PlatformError("Workspace scope is not authorized.")
            if str(run["status"]) != "Prepared":
                raise PlatformError("Ownership-change evidence can only be attached to a prepared run.")
            if actor == str(run["prepared_by"]):
                raise PlatformError(
                    "Ownership-change evidence linking requires an actor independent of the run preparer."
                )
            artifact = self._ownership_change_artifact(artifact_id)
            entity_code = self._validate_ownership_change_artifact_for_run(run, artifact)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_ownership_change_links "
                "WHERE tenant_id=%s AND run_id=%s AND artifact_id=%s",
                (self.tenant_id, run_id, artifact_id),
            ).fetchone()
            link_material = {
                "artifact_id": artifact_id,
                "artifact_result_digest": str(artifact["result_digest"]),
                "entity_code": entity_code,
                "run_id": run_id,
                "schema_version": 1,
            }
            link_digest = hashlib.sha256(self._json(link_material).encode("ascii")).hexdigest()
            if existing is not None:
                if str(existing["link_digest"]) != link_digest:
                    raise PlatformError("Ownership-change close link conflicts with immutable evidence.")
                return dict(existing)
            if any(
                entity_code == str(evidence["entity_code"])
                for evidence in run.get("ownership_change_evidence", [])
            ):
                raise PlatformError("An ownership-change entity is already linked to this run.")
            link_id = platform_id("PGCCOCL", self.tenant_id, run_id, artifact_id)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_ownership_change_links("
                "tenant_id,id,run_id,artifact_id,artifact_result_digest,entity_code,link_digest,actor) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    link_id,
                    run_id,
                    artifact_id,
                    artifact["result_digest"],
                    entity_code,
                    link_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_ownership_change_links "
                    "WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, link_id),
                ).fetchone()
            )

    def _verified_run(self, record: dict[str, Any]) -> dict[str, Any]:
        """Replay-check worksheet, journal lines, and effect metadata before exposure."""

        payload = record.get("worksheet_payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise PlatformError("Persisted consolidation worksheet is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise PlatformError("Persisted consolidation worksheet is not an object.")
        try:
            verified = verify_consolidation_worksheet_payload(payload)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PlatformError("Persisted consolidation worksheet failed replay verification.") from exc
        expected_digest = hashlib.sha256(self._json(verified.to_dict()).encode()).hexdigest()
        if expected_digest != str(record.get("worksheet_digest")):
            raise PlatformError("Persisted consolidation worksheet digest mismatch.")
        expected_lines, expected_journal_digest = self._worksheet_lines(verified)
        persisted_lines = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_run_lines "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY ordinal",
            (self.tenant_id, str(record["id"])),
        ).fetchall()
        actual_material = [self._line_material(row) for row in persisted_lines]
        if persisted_lines:
            if (
                actual_material != expected_lines
                or len(persisted_lines) != int(record.get("journal_line_count", 0) or 0)
                or not hmac.compare_digest(expected_journal_digest, str(record.get("journal_digest")))
                or any(
                    not self._amount_matches_minor(
                        row["amount_decimal"], int(row["amount_minor"]), str(row["currency_code"])
                    )
                    for row in persisted_lines
                )
            ):
                raise PlatformError("Persisted consolidation journal failed balance or digest verification.")
        elif int(record.get("journal_line_count", 0) or 0) != 0:
            raise PlatformError("Persisted consolidation journal line count has no stored lines.")
        elif str(record.get("journal_digest")) != verified.result_digest:
            # Compatibility reader for rows created before migration 0057.
            raise PlatformError("Persisted legacy consolidation journal digest mismatch.")
        actual_lines = [
            material | {"id": str(row["id"]), "ordinal": int(row["ordinal"])}
            for material, row in zip(actual_material, persisted_lines, strict=True)
        ]
        effects = self._verified_effects(str(record["id"]), actual_lines or expected_lines)
        if int(record.get("journal_line_count", 0) or 0) == 0:
            record["journal_line_count"] = len(expected_lines)
        record["worksheet"] = verified.to_dict()
        record["worksheet_object"] = verified
        record["translation_evidence"] = build_translation_evidence(verified.request.translation_result).to_dict()
        record["management_statement"] = build_management_statement_package(verified).to_dict()
        record["journal_lines"] = actual_lines or expected_lines
        record["effects"] = effects
        record["intercompany_evidence"] = self._verified_intercompany_links(record | {"worksheet_object": verified})
        record["impairment_evidence"] = self._verified_impairment_links(record | {"worksheet_object": verified})
        record["deferred_tax_evidence"] = self._verified_deferred_tax_links(record | {"worksheet_object": verified})
        record["ppa_evidence"] = self._verified_ppa_links(record | {"worksheet_object": verified})
        record["ownership_change_evidence"] = self._verified_ownership_change_links(
            record | {"worksheet_object": verified}
        )
        record["close_bundle"] = build_consolidation_close_bundle(record).to_dict()
        return record

    def _verified_effects(
        self,
        run_id: str,
        run_lines: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        effects = self.connection.execute(
            "SELECT * FROM reconforge.consolidation_close_effects "
            "WHERE tenant_id=%s AND run_id=%s ORDER BY effect_type",
            (self.tenant_id, run_id),
        ).fetchall()
        result: list[dict[str, Any]] = []
        run_by_id = {str(row["id"]): row for row in run_lines}
        for raw_effect in effects:
            effect = dict(raw_effect)
            status = str(effect.get("status", "Legacy"))
            effect_type = str(effect["effect_type"])
            if status == "Legacy":
                expected_digest = hashlib.sha256(f"{run_id}:{effect_type}".encode()).hexdigest()
                if str(effect.get("effect_digest")) != expected_digest:
                    raise PlatformError("Persisted legacy consolidation effect digest mismatch.")
                item = dict(effect)
                item["lines"] = []
                result.append(item)
                continue
            if status != "Committed":
                raise PlatformError("Persisted consolidation effect is incomplete.")
            lines = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_effect_lines "
                "WHERE tenant_id=%s AND effect_id=%s ORDER BY ordinal",
                (self.tenant_id, str(effect["id"])),
            ).fetchall()
            material: list[EffectLineMaterial] = []
            sign = 1 if effect_type == "Posting" else -1
            for line in lines:
                source = run_by_id.get(str(line["run_line_id"]))
                if (
                    source is None
                    or int(line["amount_minor"]) != sign * int(source["amount_minor"])
                    or str(line["currency_code"]) != str(source["currency_code"])
                    or not self._amount_matches_minor(
                        line["amount_decimal"], int(line["amount_minor"]), str(line["currency_code"])
                    )
                    or int(line["ordinal"]) != int(source["ordinal"])
                ):
                    raise PlatformError("Persisted consolidation effect does not reproduce its run lines.")
                material.append(
                    {
                        "amount_minor": int(line["amount_minor"]),
                        "currency_code": str(line["currency_code"]),
                        "run_line_id": str(line["run_line_id"]),
                    }
                )
            expected_digest = hashlib.sha256(
                self._json(
                    {
                        "effect_type": effect_type,
                        "lines": material,
                        "run_id": run_id,
                        "schema_version": 1,
                        "source_effect_id": str(effect.get("source_effect_id", "")),
                    }
                ).encode("ascii")
            ).hexdigest()
            if (
                len(lines) != int(effect.get("line_count", 0) or 0)
                or sum(int(line["amount_minor"]) for line in lines) != 0
                or not hmac.compare_digest(expected_digest, str(effect["effect_digest"]))
            ):
                raise PlatformError("Persisted consolidation effect failed balance or digest verification.")
            item = dict(effect)
            item["lines"] = [dict(line) for line in lines]
            result.append(item)
        status_row = self.connection.execute(
            "SELECT status FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, run_id),
        ).fetchone()
        if status_row is None:
            raise PlatformError("Consolidation run disappeared during effect verification.")
        expected_effect_types = {
            "Prepared": set(),
            "Approved": set(),
            "Posted": {"Posting"},
            "ReversalPrepared": {"Posting"},
            "Reversed": {"Posting", "Reversal"},
        }.get(str(status_row["status"]))
        if expected_effect_types is None or {str(item["effect_type"]) for item in effects} != expected_effect_types:
            raise PlatformError("Persisted consolidation effects do not match the governed run state.")
        return result

    def list_runs(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        with self.connection.transaction():
            self._scope()
            rows = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s) ORDER BY run_number LIMIT %s OFFSET %s",
                (self.tenant_id, workspace, status, status, limit, offset),
            ).fetchall()
            return [self._verified_run(dict(r)) for r in rows]

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> Any:
        from reconforge.application.consolidation_close import ConsolidationCloseSummary

        rows = self.list_periods(workspace=workspace)
        runs = self.list_runs(workspace=workspace)
        return ConsolidationCloseSummary(
            workspace=workspace,
            periods=len(rows),
            locked_periods=sum(r["status"] == "Locked" for r in rows),
            prepared_runs=sum(r["status"] == "Prepared" for r in runs),
            approved_runs=sum(r["status"] == "Approved" for r in runs),
            posted_runs=sum(r["status"] == "Posted" for r in runs),
            reversal_prepared_runs=sum(r["status"] == "ReversalPrepared" for r in runs),
            reversed_runs=sum(r["status"] == "Reversed" for r in runs),
        )
