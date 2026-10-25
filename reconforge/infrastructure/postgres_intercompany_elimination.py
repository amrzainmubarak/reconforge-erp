"""Tenant/workspace-scoped PostgreSQL persistence for intercompany proposals."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyEliminationResult,
    IntercompanyProfitInStockElimination,
    IntercompanyProfitInStockRule,
    intercompany_elimination_input_line_from_dict,
    verify_intercompany_elimination_payload,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError, normalize_text

POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.intercompany_elimination_artifacts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^ice-[0-9a-f]{32}$'),
    workspace_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL CHECK (reporting_currency ~ '^[A-Z][A-Z0-9]{2,5}$'),
    version TEXT NOT NULL CHECK (version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
    result_digest TEXT NOT NULL CHECK (result_digest ~ '^[a-f0-9]{64}$'),
    request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    result_payload JSONB NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    prepared_by TEXT NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, result_digest),
    FOREIGN KEY (tenant_id, workspace_id)
        REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, prepared_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS intercompany_elimination_scope_idx
    ON reconforge.intercompany_elimination_artifacts
        (tenant_id, workspace_id, reporting_currency, created_at, id);
ALTER TABLE reconforge.intercompany_elimination_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_elimination_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_elimination_artifacts;
CREATE POLICY tenant_scope ON reconforge.intercompany_elimination_artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_intercompany_elimination_artifact()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'intercompany elimination artifacts are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'intercompany elimination artifacts cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS intercompany_elimination_artifact_guard
    ON reconforge.intercompany_elimination_artifacts;
CREATE TRIGGER intercompany_elimination_artifact_guard
BEFORE UPDATE OR DELETE ON reconforge.intercompany_elimination_artifacts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_intercompany_elimination_artifact();

CREATE TABLE IF NOT EXISTS reconforge.intercompany_profit_in_stock_rules (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    selling_entity TEXT NOT NULL,
    buying_entity TEXT NOT NULL,
    inventory_item_code TEXT NOT NULL,
    margin_basis_points INTEGER NOT NULL,
    ending_inventory_cost_minor BIGINT NOT NULL,
    nci_share_basis_points INTEGER NOT NULL,
    currency TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, rule_id)
);
ALTER TABLE reconforge.intercompany_profit_in_stock_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_rules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_rules;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_rules
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.intercompany_profit_in_stock_eliminations (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    elimination_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    unrealized_profit_minor BIGINT NOT NULL,
    parent_share_minor BIGINT NOT NULL,
    nci_share_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    rationale TEXT NOT NULL,
    finance_entry_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, elimination_id)
);
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations;
CREATE POLICY tenant_scope ON reconforge.intercompany_profit_in_stock_eliminations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresIntercompanyEliminationError(RuntimeError):
    """Safe PostgreSQL intercompany-elimination persistence failure."""


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload(value: object, field: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PostgresIntercompanyEliminationError(f"Persisted intercompany {field} is invalid.") from exc
    if not isinstance(decoded, dict):
        raise PostgresIntercompanyEliminationError(f"Persisted intercompany {field} is invalid.")
    return dict(decoded)


def _source_lines(payload: Mapping[str, object]) -> tuple[IntercompanyEliminationInputLine, ...]:
    if set(payload) != {"lines", "prepared_at", "prepared_by", "reporting_currency", "version"}:
        raise PostgresIntercompanyEliminationError("Persisted intercompany request fields are not exact.")
    raw_lines = payload["lines"]
    if not isinstance(raw_lines, list):
        raise PostgresIntercompanyEliminationError("Persisted intercompany source lines are invalid.")
    try:
        return tuple(intercompany_elimination_input_line_from_dict(item) for item in raw_lines)
    except (ConsolidationError, TypeError, ValueError) as exc:
        raise PostgresIntercompanyEliminationError("Persisted intercompany source lines failed decoding.") from exc


class PostgresIntercompanyEliminationRepository:
    """Persist replay-verified proposals; no journal posting is exposed here."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("Intercompany elimination actor is required.")
        return actor

    @staticmethod
    def _workspace(value: str) -> str:
        workspace = normalize_text(value, default="")
        if not workspace:
            raise PlatformError("Intercompany elimination workspace is required.")
        return workspace

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def _artifact_id(self, workspace: str, result: IntercompanyEliminationResult) -> str:
        digest = hashlib.sha256(f"{self.tenant_id}|{workspace}|{result.request_digest}".encode("ascii")).hexdigest()
        return f"ice-{digest[:32]}"

    @staticmethod
    def _verify_result(
        lines: tuple[IntercompanyEliminationInputLine, ...],
        result: IntercompanyEliminationResult,
    ) -> dict[str, object]:
        if not isinstance(result, IntercompanyEliminationResult):
            raise PostgresIntercompanyEliminationError("A typed intercompany elimination result is required.")
        try:
            replay = verify_intercompany_elimination_payload(result.to_dict(), lines)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresIntercompanyEliminationError(
                "Intercompany elimination evidence failed deterministic replay verification."
            ) from exc
        if replay.result_digest != result.result_digest:
            raise PostgresIntercompanyEliminationError("Intercompany result digest lineage is invalid.")
        return result.to_dict()

    @classmethod
    def _decode_row(cls, row: Any) -> dict[str, Any]:
        request_payload = _payload(_row_value(row, "request_payload", 7), "request payload")
        result_payload = _payload(_row_value(row, "result_payload", 8), "result payload")
        lines = _source_lines(request_payload)
        try:
            replay = verify_intercompany_elimination_payload(result_payload, lines)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresIntercompanyEliminationError("Persisted intercompany evidence failed replay verification.") from exc
        if str(_row_value(row, "request_digest", 5)) != replay.request_digest or str(_row_value(row, "result_digest", 6)) != replay.result_digest:
            raise PostgresIntercompanyEliminationError("Persisted intercompany digest columns do not match payloads.")
        return {
            "id": str(_row_value(row, "id", 1)),
            "tenant_id": str(_row_value(row, "tenant_id", 0)),
            "workspace_id": str(_row_value(row, "workspace_id", 2)),
            "reporting_currency": str(_row_value(row, "reporting_currency", 3)),
            "version": str(_row_value(row, "version", 4)),
            "request_digest": replay.request_digest,
            "result_digest": replay.result_digest,
            "request_payload": request_payload,
            "result_payload": result_payload,
            "prepared_by": str(_row_value(row, "prepared_by", 9)),
            "prepared_at": str(_row_value(row, "prepared_at", 10)),
            "created_at": str(_row_value(row, "created_at", 11)),
            "posting": "not_available",
        }

    def persist(
        self,
        lines: tuple[IntercompanyEliminationInputLine, ...],
        result: IntercompanyEliminationResult,
        *,
        workspace: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        workspace_id = self._workspace(workspace)
        if actor != result.prepared_by:
            raise PlatformError("The authenticated intercompany preparer must match the result preparer.")
        payload = self._verify_result(lines, result)
        request_payload: dict[str, object] = {
            "lines": [line.to_dict() for line in sorted(lines, key=lambda item: item.transaction_id)],
            "prepared_at": result.prepared_at,
            "prepared_by": result.prepared_by,
            "reporting_currency": result.reporting_currency,
            "version": result.version,
        }
        identifier = self._artifact_id(workspace_id, result)
        if re.fullmatch(r"ice-[0-9a-f]{32}", identifier) is None:
            raise PlatformError("Intercompany elimination artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                existing = self.connection.execute(
                    "SELECT * FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
                if existing is not None:
                    stored = self._decode_row(existing)
                    if stored["request_digest"] != result.request_digest or stored["result_digest"] != result.result_digest:
                        raise PlatformError("Intercompany artifact identifier conflicts with immutable evidence.")
                    return stored
                self.connection.execute(
                    """INSERT INTO reconforge.intercompany_elimination_artifacts(
                         tenant_id,id,workspace_id,reporting_currency,version,request_digest,result_digest,
                         request_payload,result_payload,prepared_by,prepared_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),CAST(%s AS jsonb),%s,%s)""",
                    (
                        self.tenant_id,
                        identifier,
                        workspace_id,
                        result.reporting_currency,
                        result.version,
                        result.request_digest,
                        result.result_digest,
                        _json(request_payload),
                        _json(payload),
                        result.prepared_by,
                        result.prepared_at,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="intercompany_elimination_artifact",
                    object_id=identifier,
                    action="intercompany_elimination_artifact_created",
                    after_hash=result.result_digest,
                    metadata={
                        "workspace_id": workspace_id,
                        "reporting_currency": result.reporting_currency,
                        "proposal_count": sum(item.status == "proposed" for item in result.resolutions),
                        "unresolved_count": sum(item.status == "unresolved" for item in result.resolutions),
                        "posting": "not_available",
                    },
                )
                return {
                    "id": identifier,
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    "request_digest": result.request_digest,
                    "result_digest": result.result_digest,
                    "posting": "not_available",
                }
        except (PlatformError, PostgresIntercompanyEliminationError):
            raise
        except Exception as exc:
            raise PostgresIntercompanyEliminationError("PostgreSQL intercompany elimination persistence failed.") from exc

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label)
        if re.fullmatch(r"ice-[0-9a-f]{32}", artifact_id) is None:
            raise PlatformError("Intercompany elimination artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                row = self.connection.execute(
                    "SELECT * FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, artifact_id),
                ).fetchone()
                if row is None:
                    raise PostgresIntercompanyEliminationError("Intercompany elimination artifact was not found.")
                return self._decode_row(row)
        except (PlatformError, PostgresIntercompanyEliminationError):
            raise
        except Exception as exc:
            raise PostgresIntercompanyEliminationError("PostgreSQL intercompany elimination read failed.") from exc

    def save_elimination_result(
        self,
        workspace: str,
        result: IntercompanyEliminationResult,
        *,
        actor_label: str = "local-cli",
    ) -> str:
        workspace_id = self._workspace(workspace)
        actor = self._actor(actor_label)
        identifier = self._artifact_id(workspace_id, result)
        payload = result.to_dict()
        request_payload: dict[str, object] = {
            "prepared_at": result.prepared_at,
            "prepared_by": result.prepared_by,
            "reporting_currency": result.reporting_currency,
            "version": result.version,
        }
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """INSERT INTO reconforge.intercompany_elimination_artifacts(
                         tenant_id,id,workspace_id,reporting_currency,version,request_digest,result_digest,
                         request_payload,result_payload,prepared_by,prepared_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),CAST(%s AS jsonb),%s,%s)
                       ON CONFLICT (tenant_id, id) DO NOTHING""",
                    (
                        self.tenant_id,
                        identifier,
                        workspace_id,
                        result.reporting_currency,
                        result.version,
                        result.request_digest,
                        result.result_digest,
                        _json(request_payload),
                        _json(payload),
                        result.prepared_by,
                        result.prepared_at,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="intercompany_elimination_artifact",
                    object_id=identifier,
                    action="intercompany_elimination_artifact_created",
                    after_hash=result.result_digest,
                    metadata={
                        "workspace_id": workspace_id,
                        "reporting_currency": result.reporting_currency,
                    },
                )
                return identifier
        except Exception as exc:
            raise PostgresIntercompanyEliminationError(f"PostgreSQL intercompany elimination save failed: {exc}") from exc

    def save_profit_in_stock_elimination(
        self,
        workspace: str,
        rule: IntercompanyProfitInStockRule,
        elimination: IntercompanyProfitInStockElimination,
        *,
        finance_entry_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> str:
        actor = self._actor(actor_label)
        workspace_id = self._workspace(workspace)
        rule_db_id = f"psr_{rule.rule_id}"
        elim_db_id = f"pse_{elimination.elimination_id}"

        try:
            with self.connection.transaction():
                self._scope()
                # Upsert rule
                self.connection.execute(
                    """
                    INSERT INTO reconforge.intercompany_profit_in_stock_rules (
                        tenant_id, id, workspace_id, rule_id, selling_entity, buying_entity,
                        inventory_item_code, margin_basis_points, ending_inventory_cost_minor,
                        nci_share_basis_points, currency
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, rule_id) DO UPDATE SET
                        margin_basis_points = excluded.margin_basis_points,
                        ending_inventory_cost_minor = excluded.ending_inventory_cost_minor,
                        nci_share_basis_points = excluded.nci_share_basis_points
                    """,
                    (
                        self.tenant_id,
                        rule_db_id,
                        workspace_id,
                        rule.rule_id,
                        rule.selling_entity,
                        rule.buying_entity,
                        rule.inventory_item_code,
                        rule.margin_basis_points,
                        rule.ending_inventory_cost_minor,
                        rule.nci_share_basis_points,
                        rule.currency,
                    ),
                )

                # Insert elimination
                self.connection.execute(
                    """
                    INSERT INTO reconforge.intercompany_profit_in_stock_eliminations (
                        tenant_id, id, workspace_id, elimination_id, rule_id,
                        unrealized_profit_minor, parent_share_minor, nci_share_minor,
                        currency, debit_account, credit_account, rationale, finance_entry_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, elimination_id) DO UPDATE SET
                        unrealized_profit_minor = excluded.unrealized_profit_minor,
                        parent_share_minor = excluded.parent_share_minor,
                        nci_share_minor = excluded.nci_share_minor,
                        finance_entry_id = COALESCE(excluded.finance_entry_id, reconforge.intercompany_profit_in_stock_eliminations.finance_entry_id)
                    """,
                    (
                        self.tenant_id,
                        elim_db_id,
                        workspace_id,
                        elimination.elimination_id,
                        elimination.rule_id,
                        elimination.unrealized_profit_minor,
                        elimination.parent_share_minor,
                        elimination.nci_share_minor,
                        elimination.currency,
                        elimination.debit_account,
                        elimination.credit_account,
                        elimination.rationale,
                        finance_entry_id,
                    ),
                )

                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="intercompany_profit_in_stock_elimination",
                    object_id=elimination.elimination_id,
                    action="profit_in_stock_eliminated",
                    after_hash=hashlib.sha256(f"{elimination.elimination_id}:{elimination.unrealized_profit_minor}:{finance_entry_id}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": workspace_id,
                        "rule_id": rule.rule_id,
                        "unrealized_profit_minor": elimination.unrealized_profit_minor,
                        "parent_share_minor": elimination.parent_share_minor,
                        "nci_share_minor": elimination.nci_share_minor,
                        "finance_entry_id": finance_entry_id,
                    },
                )
                return elimination.elimination_id
        except Exception as exc:
            raise PostgresIntercompanyEliminationError(f"PostgreSQL profit in stock save failed: {exc}") from exc

    def post_profit_in_stock_to_finance_core(
        self,
        *,
        elimination: IntercompanyProfitInStockElimination,
        organization_code: str,
        entity_code: str,
        period_id: str,
        posting_date: str,
        journal_code: str = "CONSOLIDATION",
        workspace: str = "default",
        finance_core_repo: Any | None = None,
        precision: int = 2,
        actor_label: str = "intercompany-elimination",
    ) -> str:
        """Post authoritative balanced double-entry elimination GL voucher into Finance Core."""
        if finance_core_repo is None:
            raise PostgresIntercompanyEliminationError("Finance Core repository is required for canonical elimination posting.")
        workspace_id = self._workspace(workspace)
        try:
            entry_number = f"PIS-{elimination.elimination_id}"
            whole = elimination.unrealized_profit_minor // (10 ** precision)
            cents = elimination.unrealized_profit_minor % (10 ** precision)
            amount_str = f"{whole}.{cents:0{precision}d}"
            zero_str = f"0.{'0' * precision}"

            lines = [
                {
                    "account_code": elimination.debit_account,
                    "debit": amount_str,
                    "credit": zero_str,
                    "description": f"Profit-in-stock elimination {elimination.elimination_id}",
                },
                {
                    "account_code": elimination.credit_account,
                    "debit": zero_str,
                    "credit": amount_str,
                    "description": f"Inventory valuation reduction {elimination.elimination_id}",
                },
            ]
            entry = finance_core_repo.create_entry(
                entry_number=entry_number,
                organization_code=organization_code,
                entity_code=entity_code,
                period_id=period_id,
                journal_code=journal_code,
                posting_date=posting_date,
                description=f"Intercompany profit-in-stock elimination {elimination.elimination_id}",
                lines=lines,
                workspace=workspace_id,
                source_type="Generated",
                actor_label=actor_label,
            )
            entry_id = entry.get("id") if isinstance(entry, Mapping) else None
            if not isinstance(entry_id, str) or not entry_id.strip():
                raise PostgresIntercompanyEliminationError("Finance Core did not return a canonical entry identifier.")

            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    UPDATE reconforge.intercompany_profit_in_stock_eliminations
                    SET finance_entry_id = %s
                    WHERE tenant_id = %s AND workspace_id = %s AND elimination_id = %s
                    """,
                    (entry_id, self.tenant_id, workspace_id, elimination.elimination_id),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="intercompany_profit_in_stock_elimination",
                    object_id=elimination.elimination_id,
                    action="profit_in_stock_gl_posted",
                    after_hash=hashlib.sha256(f"{elimination.elimination_id}:{entry_id}:{elimination.unrealized_profit_minor}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": workspace_id,
                        "elimination_id": elimination.elimination_id,
                        "finance_entry_id": entry_id,
                        "amount_minor": elimination.unrealized_profit_minor,
                    },
                )
            return entry_id
        except Exception as exc:
            raise PostgresIntercompanyEliminationError(f"PostgreSQL post profit in stock to Finance Core failed: {exc}") from exc

    def list_profit_in_stock_eliminations(
        self,
        workspace: str,
        *,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        self._actor(actor_label)
        workspace_id = self._workspace(workspace)
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT e.elimination_id, e.rule_id, e.unrealized_profit_minor,
                           e.parent_share_minor, e.nci_share_minor, e.currency,
                           e.debit_account, e.credit_account, e.rationale, e.created_at,
                           r.selling_entity, r.buying_entity, r.inventory_item_code,
                           r.margin_basis_points, r.ending_inventory_cost_minor
                    FROM reconforge.intercompany_profit_in_stock_eliminations e
                    JOIN reconforge.intercompany_profit_in_stock_rules r
                      ON r.tenant_id = e.tenant_id AND r.workspace_id = e.workspace_id AND r.rule_id = e.rule_id
                    WHERE e.tenant_id = %s AND e.workspace_id = %s
                    ORDER BY e.created_at DESC
                    """,
                    (self.tenant_id, workspace_id),
                )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "elimination_id": row[0],
                        "rule_id": row[1],
                        "unrealized_profit_minor": row[2],
                        "parent_share_minor": row[3],
                        "nci_share_minor": row[4],
                        "currency": row[5],
                        "debit_account": row[6],
                        "credit_account": row[7],
                        "rationale": row[8],
                        "created_at": str(row[9]),
                        "selling_entity": row[10],
                        "buying_entity": row[11],
                        "inventory_item_code": row[12],
                        "margin_basis_points": row[13],
                        "ending_inventory_cost_minor": row[14],
                    })
                return results
        except Exception as exc:
            raise PostgresIntercompanyEliminationError(f"PostgreSQL profit in stock list failed: {exc}") from exc

    def list_elimination_runs(
        self,
        workspace: str,
        *,
        limit: int = 50,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        self._actor(actor_label)
        workspace_id = self._workspace(workspace)
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT id, workspace_id, reporting_currency, version,
                           request_digest, result_digest, result_payload,
                           prepared_by, prepared_at, created_at
                    FROM reconforge.intercompany_elimination_artifacts
                    WHERE tenant_id = %s AND workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (self.tenant_id, workspace_id, max(1, min(limit, 200))),
                )
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "workspace_id": r[1],
                        "reporting_currency": r[2],
                        "version": r[3],
                        "request_digest": r[4],
                        "result_digest": r[5],
                        "result_payload": r[6] if isinstance(r[6], dict) else json.loads(r[6]),
                        "prepared_by": r[7],
                        "prepared_at": str(r[8]),
                        "created_at": str(r[9]),
                    }
                    for r in rows
                ]
        except Exception as exc:
            raise PostgresIntercompanyEliminationError(f"PostgreSQL elimination list failed: {exc}") from exc

    def get_elimination_run(
        self,
        workspace: str,
        run_id: str,
        *,
        actor_label: str = "local-cli",
    ) -> dict[str, Any] | None:
        try:
            return self.get(run_id, actor_label=actor_label)
        except PostgresIntercompanyEliminationError:
            return None


__all__ = [
    "POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL",
    "PostgresIntercompanyEliminationError",
    "PostgresIntercompanyEliminationRepository",
]
