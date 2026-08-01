"""Tenant-scoped PostgreSQL account-reconciliation aggregate."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from reconforge.application.accounts import ImportTrialBalanceResult
from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import (
    PlatformError,
    normalize_key,
    normalize_text,
    parse_financial_amount,
    platform_id,
    read_local_record_document,
)

POSTGRES_ACCOUNTS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.account_reconciliation_templates (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,account_code TEXT NOT NULL,
 name TEXT NOT NULL,risk_rating TEXT NOT NULL CHECK(risk_rating IN('low','medium','high','critical')),
 materiality_threshold NUMERIC NOT NULL CHECK(materiality_threshold>=0),
 materiality_threshold_decimal TEXT NOT NULL,required_evidence TEXT NOT NULL DEFAULT '',
 owner TEXT NOT NULL DEFAULT '',reviewer TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,account_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.trial_balance_rows (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,period_name TEXT NOT NULL,
 entity_code TEXT NOT NULL,account_code TEXT NOT NULL,account_name TEXT NOT NULL,balance NUMERIC NOT NULL,
 balance_decimal TEXT NOT NULL,currency TEXT NOT NULL CHECK(currency ~ '^[A-Z]{3,12}$'),
 source_path TEXT NOT NULL,source_checksum_sha256 TEXT NOT NULL CHECK(source_checksum_sha256 ~ '^[0-9a-f]{64}$'),
 source_row_number INTEGER NOT NULL CHECK(source_row_number>0),imported_by TEXT NOT NULL,
 imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,period_name,entity_code,account_code,source_checksum_sha256,source_row_number),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.account_reconciliation_records (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,period_name TEXT NOT NULL,
 entity_code TEXT NOT NULL,account_code TEXT NOT NULL,account_name TEXT NOT NULL,template_id TEXT,
 status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN('Draft','Prepared','In Review','Reviewed','Complete')),
 balance NUMERIC NOT NULL,balance_decimal TEXT NOT NULL,materiality_threshold NUMERIC NOT NULL
 CHECK(materiality_threshold>=0),materiality_threshold_decimal TEXT NOT NULL,
 currency_code TEXT NOT NULL CHECK(currency_code ~ '^[A-Z]{3,12}$'),
 risk_rating TEXT NOT NULL CHECK(risk_rating IN('low','medium','high','critical')),
 owner TEXT NOT NULL DEFAULT '',preparer TEXT NOT NULL DEFAULT '',reviewer TEXT NOT NULL DEFAULT '',
 prepared_at TIMESTAMPTZ,submitted_at TIMESTAMPTZ,reviewed_at TIMESTAMPTZ,completed_at TIMESTAMPTZ,
 aging_days INTEGER NOT NULL DEFAULT 0 CHECK(aging_days>=0),created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,period_name,entity_code,account_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,template_id) REFERENCES reconforge.account_reconciliation_templates(tenant_id,id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS reconforge.account_reconciliation_items (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,reconciliation_id TEXT NOT NULL,item_type TEXT NOT NULL,
 description TEXT NOT NULL,amount NUMERIC NOT NULL,amount_decimal TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Open',evidence_required BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,reconciliation_id) REFERENCES reconforge.account_reconciliation_records(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.account_reconciliation_transitions (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,reconciliation_id TEXT NOT NULL,
 transition_sequence BIGINT NOT NULL CHECK(transition_sequence>0),from_status TEXT NOT NULL,
 to_status TEXT NOT NULL,actor_label TEXT NOT NULL,reason TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,reconciliation_id,transition_sequence),
 FOREIGN KEY(tenant_id,reconciliation_id) REFERENCES reconforge.account_reconciliation_records(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS account_reconciliation_queue_idx ON reconforge.account_reconciliation_records
 (tenant_id,status,owner,period_name,entity_code,risk_rating,account_code,id);
CREATE INDEX IF NOT EXISTS trial_balance_scope_idx ON reconforge.trial_balance_rows
 (tenant_id,workspace_id,period_name,entity_code,account_code,id);

CREATE OR REPLACE FUNCTION reconforge.account_reconciliation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='account_reconciliation_records' THEN
  IF TG_OP='INSERT' AND NEW.status<>'Draft' THEN RAISE EXCEPTION 'account reconciliations must be created as Draft'; END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status AND NOT ((OLD.status='Draft' AND NEW.status='Prepared') OR (OLD.status='Prepared' AND NEW.status='In Review') OR (OLD.status='In Review' AND NEW.status='Reviewed') OR (OLD.status='Reviewed' AND NEW.status='Complete')) THEN RAISE EXCEPTION 'invalid account reconciliation status transition'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Prepared' AND (NEW.preparer='' OR NEW.prepared_at IS NULL) THEN RAISE EXCEPTION 'preparing an account reconciliation requires actor evidence'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Prepared' AND NEW.status='In Review' AND NEW.submitted_at IS NULL THEN RAISE EXCEPTION 'submitting an account reconciliation requires timestamp evidence'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='In Review' AND NEW.status='Reviewed' AND (NEW.reviewer='' OR NEW.reviewed_at IS NULL OR lower(trim(NEW.reviewer))=lower(trim(NEW.preparer))) THEN RAISE EXCEPTION 'reviewing an account reconciliation requires separation of duties'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Reviewed' AND NEW.status='Complete' AND NEW.completed_at IS NULL THEN RAISE EXCEPTION 'completing an account reconciliation requires timestamp evidence'; END IF;
  IF TG_OP='UPDATE' AND OLD.status<>'Draft' AND (NEW.workspace_id,NEW.period_name,NEW.entity_code,NEW.account_code,NEW.account_name,NEW.template_id,NEW.balance,NEW.balance_decimal,NEW.materiality_threshold,NEW.materiality_threshold_decimal,NEW.currency_code,NEW.risk_rating,NEW.owner,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.workspace_id,OLD.period_name,OLD.entity_code,OLD.account_code,OLD.account_name,OLD.template_id,OLD.balance,OLD.balance_decimal,OLD.materiality_threshold,OLD.materiality_threshold_decimal,OLD.currency_code,OLD.risk_rating,OLD.owner,OLD.created_by,OLD.created_at) THEN RAISE EXCEPTION 'prepared account reconciliation financial fields are immutable'; END IF;
  IF TG_OP='UPDATE' AND OLD.status IN('Reviewed','Complete') AND (NEW.preparer,NEW.prepared_at,NEW.submitted_at,NEW.reviewer,NEW.reviewed_at) IS DISTINCT FROM (OLD.preparer,OLD.prepared_at,OLD.submitted_at,OLD.reviewer,OLD.reviewed_at) THEN RAISE EXCEPTION 'reviewed account reconciliation evidence is immutable'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Complete' THEN RAISE EXCEPTION 'completed account reconciliations are immutable'; END IF;
  IF TG_OP='DELETE' AND OLD.status<>'Draft' THEN RAISE EXCEPTION 'prepared account reconciliations cannot be deleted'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN
  IF EXISTS(SELECT 1 FROM reconforge.account_reconciliation_records r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.reconciliation_id AND r.status<>'Draft') THEN RAISE EXCEPTION 'prepared account reconciliation items are immutable'; END IF;
  RETURN OLD;
 END IF;
 IF EXISTS(SELECT 1 FROM reconforge.account_reconciliation_records r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.reconciliation_id AND r.status<>'Draft') THEN RAISE EXCEPTION 'prepared account reconciliation items are immutable'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS account_reconciliation_records_guard ON reconforge.account_reconciliation_records;
CREATE TRIGGER account_reconciliation_records_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.account_reconciliation_records FOR EACH ROW EXECUTE FUNCTION reconforge.account_reconciliation_guard();
DROP TRIGGER IF EXISTS account_reconciliation_items_guard ON reconforge.account_reconciliation_items;
CREATE TRIGGER account_reconciliation_items_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.account_reconciliation_items FOR EACH ROW EXECUTE FUNCTION reconforge.account_reconciliation_guard();

CREATE OR REPLACE FUNCTION reconforge.account_reconciliation_transition_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'account reconciliation transition evidence is append only'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.account_reconciliation_records r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.reconciliation_id AND r.status=NEW.to_status) THEN RAISE EXCEPTION 'transition evidence must match the current reconciliation status'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS account_reconciliation_transitions_guard ON reconforge.account_reconciliation_transitions;
CREATE TRIGGER account_reconciliation_transitions_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.account_reconciliation_transitions FOR EACH ROW EXECUTE FUNCTION reconforge.account_reconciliation_transition_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['account_reconciliation_templates','trial_balance_rows','account_reconciliation_records','account_reconciliation_items','account_reconciliation_transitions'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""

ACCOUNT_STATUSES = ("Draft", "Prepared", "In Review", "Reviewed", "Complete")
RISK_RATINGS = ("low", "medium", "high", "critical")


class PostgresAccountsError(RuntimeError):
    """Safe PostgreSQL account-reconciliation persistence failure."""


def _decimal(value: object, *, field: str, non_negative: bool = False) -> Decimal:
    parsed = parse_financial_amount(value, field=field)
    if non_negative and parsed < 0:
        raise PlatformError(f"Financial amount in field '{field}' cannot be negative.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _currency(value: object) -> str:
    result = normalize_key(value, default="LOCAL").upper()
    if not 3 <= len(result) <= 12 or not result.isalpha():
        raise PlatformError("Currency code must be alphabetic and between 3 and 12 characters.")
    return result


def _risk(value: object) -> str:
    result = normalize_key(value, default="medium").lower()
    if result not in RISK_RATINGS:
        raise PlatformError("Risk rating must be low, medium, high, or critical.")
    return result


class PostgresAccountReconciliationRepository:
    """Implement the complete account-reconciliation port for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresAccountsError):
            raise
        except Exception as exc:
            raise PostgresAccountsError("PostgreSQL account reconciliation operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_text(workspace, default="default")),
        ).fetchone()
        if row is None:
            raise PlatformError("Workspace was not found for this tenant.")
        return str(row[0])

    @staticmethod
    def _row_dict(cursor: Any) -> dict[str, Any] | None:
        row = cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, Mapping):
            return dict(row)
        return dict(zip((column.name for column in cursor.description), row, strict=True))

    @classmethod
    def _rows_dict(cls, cursor: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while (row := cls._row_dict(cursor)) is not None:
            rows.append(row)
        return rows

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        version: str | int,
        metadata: Mapping[str, object],
    ) -> None:
        actor = normalize_text(actor_label, default="local-cli")
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=dict(metadata),
        )
        event_id = platform_id("OBX", object_type, object_id, action, version)
        try:
            payload = encode_postgres_outbox_payload(
                {
                    "event_id": event_id,
                    "event_type": f"accounts.{action}",
                    "aggregate_type": object_type,
                    "aggregate_id": object_id,
                    "payload": {"actor": actor, **dict(metadata)},
                }
            ).text
        except PersistedJsonError as exc:
            raise PlatformError("Unable to encode account reconciliation evidence.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,aggregate_type,aggregate_id,event_type,payload)
            VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, object_type, object_id, f"accounts.{action}", payload),
        )

    def _record(self, reconciliation_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = (
            "SELECT * FROM reconforge.account_reconciliation_records WHERE tenant_id=%s AND id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM reconforge.account_reconciliation_records WHERE tenant_id=%s AND id=%s"
        )
        row = self._row_dict(
            self.connection.execute(query, (self.tenant_id, normalize_text(reconciliation_id, default="")))
        )
        if row is None:
            raise PlatformError("Account reconciliation record not found.")
        return row

    @staticmethod
    def _public_amounts(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for numeric, text in (
            ("balance", "balance_decimal"),
            ("materiality_threshold", "materiality_threshold_decimal"),
            ("amount", "amount_decimal"),
        ):
            if text in result:
                result[numeric] = result[text]
        if "evidence_required" in result:
            result["evidence_required"] = int(bool(result["evidence_required"]))
        return result

    def _get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]:
        record = self._public_amounts(self._record(reconciliation_id))
        rows = self._rows_dict(
            self.connection.execute(
                "SELECT * FROM reconforge.account_reconciliation_items WHERE tenant_id=%s AND reconciliation_id=%s ORDER BY created_at,id",
                (self.tenant_id, reconciliation_id),
            )
        )
        record["items"] = [self._public_amounts(row) for row in rows]
        return record

    def _upsert_record(
        self,
        *,
        workspace_id: str,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str,
        balance: object,
        owner: str,
        preparer: str,
        reviewer: str,
        risk_rating: str,
        materiality_threshold: object,
        currency_code: str,
        actor_label: str,
        template_id: str | None = None,
        finalize: bool = True,
    ) -> dict[str, Any]:
        period = normalize_key(period_name, default="current")
        entity = normalize_key(entity_code, default="local")
        code = normalize_key(account_code, default="")
        if not code:
            raise PlatformError("Account code is required.")
        parsed_balance = _decimal(balance, field="reconciliation balance")
        threshold = _decimal(materiality_threshold, field="materiality threshold", non_negative=True)
        currency = _currency(currency_code)
        risk = _risk(risk_rating)
        reconciliation_id = platform_id("AR", workspace_id, period, entity, code)
        row = self.connection.execute(
            """INSERT INTO reconforge.account_reconciliation_records(
            tenant_id,id,workspace_id,period_name,entity_code,account_code,account_name,template_id,
            status,balance,balance_decimal,materiality_threshold,materiality_threshold_decimal,
            currency_code,risk_rating,owner,preparer,reviewer,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(tenant_id,workspace_id,period_name,entity_code,account_code) DO UPDATE SET
            account_name=EXCLUDED.account_name,
            template_id=COALESCE(EXCLUDED.template_id,reconforge.account_reconciliation_records.template_id),
            balance=EXCLUDED.balance,balance_decimal=EXCLUDED.balance_decimal,
            materiality_threshold=EXCLUDED.materiality_threshold,
            materiality_threshold_decimal=EXCLUDED.materiality_threshold_decimal,
            currency_code=EXCLUDED.currency_code,risk_rating=EXCLUDED.risk_rating,
            owner=CASE WHEN EXCLUDED.owner<>'' THEN EXCLUDED.owner ELSE reconforge.account_reconciliation_records.owner END,
            reviewer=CASE WHEN EXCLUDED.reviewer<>'' THEN EXCLUDED.reviewer ELSE reconforge.account_reconciliation_records.reviewer END,
            updated_at=now(),row_version=reconforge.account_reconciliation_records.row_version+1
            WHERE reconforge.account_reconciliation_records.status='Draft' RETURNING id,row_version""",
            (
                self.tenant_id,
                reconciliation_id,
                workspace_id,
                period,
                entity,
                code,
                normalize_text(account_name, default=code),
                template_id,
                parsed_balance,
                _decimal_text(parsed_balance),
                threshold,
                _decimal_text(threshold),
                currency,
                risk,
                normalize_text(owner, default=""),
                normalize_text(preparer, default=""),
                normalize_text(reviewer, default=""),
                normalize_text(actor_label, default="local-cli"),
            ),
        ).fetchone()
        if row is None:
            raise PlatformError("Only Draft account reconciliations can be updated.")
        item_id = platform_id("ARI", reconciliation_id, "balance_support")
        evidence_required = abs(parsed_balance) >= threshold if threshold else abs(parsed_balance) > 0
        self.connection.execute(
            """INSERT INTO reconforge.account_reconciliation_items(
            tenant_id,id,reconciliation_id,item_type,description,amount,amount_decimal,status,evidence_required)
            VALUES(%s,%s,%s,'balance_support','Trial-balance balance support',%s,%s,'Open',%s)
            ON CONFLICT(tenant_id,id) DO UPDATE SET amount=EXCLUDED.amount,
            amount_decimal=EXCLUDED.amount_decimal,evidence_required=EXCLUDED.evidence_required,updated_at=now()""",
            (
                self.tenant_id,
                item_id,
                reconciliation_id,
                parsed_balance,
                _decimal_text(parsed_balance),
                evidence_required,
            ),
        )
        if finalize:
            self._event(
                actor_label=actor_label,
                object_type="account_reconciliation",
                object_id=reconciliation_id,
                action="reconciliation.saved",
                version=row["row_version"],
                metadata={"period": period, "entity": entity, "account_code": code},
            )
        return self._get_reconciliation(reconciliation_id)

    def import_trial_balance(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> ImportTrialBalanceResult:
        document = read_local_record_document(input_path)
        if not document.records:
            raise PlatformError("Trial balance input did not contain any records.")
        parsed_rows: list[dict[str, object]] = []
        for index, source in enumerate(document.records, start=1):
            period = normalize_key(source.get("period") or source.get("period_name"), default=default_period)
            entity = normalize_key(source.get("entity") or source.get("entity_code"), default=default_entity)
            code = normalize_key(
                source.get("account_code") or source.get("account") or source.get("account_number"), default=""
            )
            if not code:
                raise PlatformError("Trial balance rows require account_code.")
            amount_value: object = None
            for field in ("balance", "amount", "ending_balance"):
                candidate = source.get(field)
                if candidate is not None and (not isinstance(candidate, str) or candidate.strip()):
                    amount_value = candidate
                    break
            balance = _decimal(amount_value, field=f"trial balance row {index} balance")
            parsed_rows.append(
                {
                    "index": index,
                    "period": period,
                    "entity": entity,
                    "account_code": code,
                    "account_name": normalize_text(source.get("account_name") or source.get("name"), default=code),
                    "balance": balance,
                    "currency": _currency(source.get("currency")),
                }
            )
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            for parsed in parsed_rows:
                row_id = platform_id(
                    "TB",
                    workspace_id,
                    parsed["period"],
                    parsed["entity"],
                    parsed["account_code"],
                    document.checksum_sha256,
                    parsed["index"],
                )
                self.connection.execute(
                    """INSERT INTO reconforge.trial_balance_rows(
                    tenant_id,id,workspace_id,period_name,entity_code,account_code,account_name,balance,
                    balance_decimal,currency,source_path,source_checksum_sha256,source_row_number,imported_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(tenant_id,workspace_id,period_name,entity_code,account_code,source_checksum_sha256,source_row_number)
                    DO UPDATE SET account_name=EXCLUDED.account_name,balance=EXCLUDED.balance,
                    balance_decimal=EXCLUDED.balance_decimal,currency=EXCLUDED.currency,
                    imported_by=EXCLUDED.imported_by,imported_at=now()""",
                    (
                        self.tenant_id,
                        row_id,
                        workspace_id,
                        parsed["period"],
                        parsed["entity"],
                        parsed["account_code"],
                        parsed["account_name"],
                        parsed["balance"],
                        _decimal_text(cast(Decimal, parsed["balance"])),
                        parsed["currency"],
                        document.source_path.name,
                        document.checksum_sha256,
                        parsed["index"],
                        normalize_text(actor_label, default="local-cli"),
                    ),
                )
                template = self._row_dict(
                    self.connection.execute(
                        "SELECT * FROM reconforge.account_reconciliation_templates WHERE tenant_id=%s AND workspace_id=%s AND account_code=%s",
                        (self.tenant_id, workspace_id, parsed["account_code"]),
                    )
                )
                self._upsert_record(
                    workspace_id=workspace_id,
                    period_name=str(parsed["period"]),
                    entity_code=str(parsed["entity"]),
                    account_code=str(parsed["account_code"]),
                    account_name=str(parsed["account_name"]),
                    balance=parsed["balance"],
                    owner=str(template["owner"]) if template else "",
                    preparer="",
                    reviewer=str(template["reviewer"]) if template else "",
                    risk_rating=str(template["risk_rating"]) if template else "medium",
                    materiality_threshold=(template["materiality_threshold_decimal"] if template else "0"),
                    currency_code=str(parsed["currency"]),
                    actor_label=actor_label,
                    template_id=str(template["id"]) if template else None,
                    finalize=False,
                )
            import_id = platform_id("ARIMP", workspace_id, document.checksum_sha256)
            self._event(
                actor_label=actor_label,
                object_type="account_reconciliation_import",
                object_id=import_id,
                action="trial_balance.imported",
                version=document.checksum_sha256,
                metadata={
                    "source_file": document.source_path.name,
                    "source_checksum_sha256": document.checksum_sha256,
                    "source_size_bytes": document.size_bytes,
                    "ingress_profile": document.profile_id,
                    "imported_rows": len(parsed_rows),
                    "records": len(parsed_rows),
                },
            )
        return ImportTrialBalanceResult(document.source_path, len(parsed_rows), len(parsed_rows))

    def create_template(
        self,
        *,
        account_code: str,
        name: str = "",
        workspace: str = "default",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        required_evidence: str = "",
        owner: str = "",
        reviewer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        code = normalize_key(account_code, default="")
        if not code:
            raise PlatformError("Account code is required.")
        threshold = _decimal(materiality_threshold, field="materiality threshold", non_negative=True)
        risk = _risk(risk_rating)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            template_id = platform_id("ART", workspace_id, code)
            row = self._row_dict(
                self.connection.execute(
                    """INSERT INTO reconforge.account_reconciliation_templates(
                tenant_id,id,workspace_id,account_code,name,risk_rating,materiality_threshold,
                materiality_threshold_decimal,required_evidence,owner,reviewer,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,workspace_id,account_code) DO UPDATE SET name=EXCLUDED.name,
                risk_rating=EXCLUDED.risk_rating,materiality_threshold=EXCLUDED.materiality_threshold,
                materiality_threshold_decimal=EXCLUDED.materiality_threshold_decimal,
                required_evidence=EXCLUDED.required_evidence,owner=EXCLUDED.owner,reviewer=EXCLUDED.reviewer,
                updated_at=now(),row_version=reconforge.account_reconciliation_templates.row_version+1
                RETURNING *""",
                    (
                        self.tenant_id,
                        template_id,
                        workspace_id,
                        code,
                        normalize_text(name, default=f"{code} reconciliation"),
                        risk,
                        threshold,
                        _decimal_text(threshold),
                        normalize_text(required_evidence, default=""),
                        normalize_text(owner, default=""),
                        normalize_text(reviewer, default=""),
                        normalize_text(actor_label, default="local-cli"),
                    ),
                )
            )
            if row is None:
                raise PlatformError("Unable to save account reconciliation template.")
            self._event(
                actor_label=actor_label,
                object_type="account_reconciliation_template",
                object_id=template_id,
                action="template.saved",
                version=row["row_version"],
                metadata={"account_code": code, "risk_rating": risk},
            )
            return self._public_amounts(row)

    def create_reconciliation(
        self,
        *,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str = "",
        workspace: str = "default",
        balance: object = Decimal("0"),
        owner: str = "",
        preparer: str = "",
        reviewer: str = "",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            return self._upsert_record(
                workspace_id=self._workspace_id(workspace),
                period_name=period_name,
                entity_code=entity_code,
                account_code=account_code,
                account_name=account_name or account_code,
                balance=balance,
                owner=owner,
                preparer=preparer,
                reviewer=reviewer,
                risk_rating=risk_rating,
                materiality_threshold=materiality_threshold,
                currency_code="LOCAL",
                actor_label=actor_label,
            )

    def _transition(
        self,
        reconciliation_id: str,
        to_status: str,
        *,
        actor_label: str,
        preparer: str | None = None,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        expected = {
            "Prepared": "Draft",
            "In Review": "Prepared",
            "Reviewed": "In Review",
            "Complete": "Reviewed",
        }
        if to_status not in expected:
            raise PlatformError("Unsupported account reconciliation status.")
        record = self._record(reconciliation_id, lock=True)
        from_status = str(record["status"])
        if from_status != expected[to_status]:
            raise PlatformError(f"Cannot transition reconciliation from {from_status} to {to_status}.")
        actual_actor = normalize_text(actor_label, default="local-cli")
        actual_preparer = normalize_text(preparer, default=actual_actor) if preparer is not None else None
        actual_reviewer = normalize_text(reviewer, default=actual_actor) if reviewer is not None else None
        if to_status == "Reviewed" and same_actor(record.get("preparer"), actual_reviewer):
            raise PlatformError("Separation of duties conflict: preparer and reviewer must be different.")
        row = self.connection.execute(
            """UPDATE reconforge.account_reconciliation_records SET status=%s,updated_at=now(),
            preparer=COALESCE(%s,preparer),prepared_at=CASE WHEN %s='Prepared' THEN now() ELSE prepared_at END,
            submitted_at=CASE WHEN %s='In Review' THEN now() ELSE submitted_at END,
            reviewer=COALESCE(%s,reviewer),reviewed_at=CASE WHEN %s='Reviewed' THEN now() ELSE reviewed_at END,
            completed_at=CASE WHEN %s='Complete' THEN now() ELSE completed_at END,row_version=row_version+1
            WHERE tenant_id=%s AND id=%s AND status=%s RETURNING row_version""",
            (
                to_status,
                actual_preparer,
                to_status,
                to_status,
                actual_reviewer,
                to_status,
                to_status,
                self.tenant_id,
                reconciliation_id,
                from_status,
            ),
        ).fetchone()
        if row is None:
            raise PlatformError("Account reconciliation changed concurrently; reload and retry.")
        row_version = int(row[0])
        transition_id = platform_id("ARTR", reconciliation_id, from_status, to_status, row_version)
        self.connection.execute(
            """INSERT INTO reconforge.account_reconciliation_transitions(
            tenant_id,id,reconciliation_id,transition_sequence,from_status,to_status,actor_label,reason)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'Account reconciliation lifecycle update')""",
            (self.tenant_id, transition_id, reconciliation_id, row_version, from_status, to_status, actual_actor),
        )
        self._event(
            actor_label=actual_actor,
            object_type="account_reconciliation",
            object_id=reconciliation_id,
            action="reconciliation.transitioned",
            version=row_version,
            metadata={"from_status": from_status, "to_status": to_status},
        )
        return self._get_reconciliation(reconciliation_id)

    def prepare(
        self,
        *,
        reconciliation_id: str | None = None,
        workspace: str = "default",
        period_name: str = "current",
        entity_code: str = "local",
        account_code: str = "",
        preparer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            if reconciliation_id:
                selected_id = reconciliation_id
            else:
                workspace_id = self._workspace_id(workspace)
                selected_id = platform_id(
                    "AR",
                    workspace_id,
                    normalize_key(period_name, default="current"),
                    normalize_key(entity_code, default="local"),
                    normalize_key(account_code, default=""),
                )
            return self._transition(
                selected_id,
                "Prepared",
                actor_label=actor_label,
                preparer=normalize_text(preparer, default=actor_label),
            )

    def submit(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._transition(reconciliation_id, "In Review", actor_label=actor_label)

    def review(self, reconciliation_id: str, *, reviewer: str = "", actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            actual = normalize_text(reviewer, default=actor_label)
            return self._transition(
                reconciliation_id,
                "Reviewed",
                actor_label=actual,
                reviewer=actual,
            )

    def complete(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._transition(reconciliation_id, "Complete", actor_label=actor_label)

    def roll_forward(
        self,
        *,
        from_period: str,
        to_period: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> int:
        source_period = normalize_key(from_period, default="")
        target_period = normalize_key(to_period, default="")
        if not source_period or not target_period or source_period == target_period:
            raise PlatformError("Roll-forward requires distinct source and target periods.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self._rows_dict(
                self.connection.execute(
                    """SELECT * FROM reconforge.account_reconciliation_records
                WHERE tenant_id=%s AND workspace_id=%s AND period_name=%s
                ORDER BY entity_code,account_code,id""",
                    (self.tenant_id, workspace_id, source_period),
                )
            )
            for raw in rows:
                source = dict(raw)
                self._upsert_record(
                    workspace_id=workspace_id,
                    period_name=target_period,
                    entity_code=str(source["entity_code"]),
                    account_code=str(source["account_code"]),
                    account_name=str(source["account_name"]),
                    balance="0",
                    owner=str(source["owner"]),
                    preparer="",
                    reviewer=str(source["reviewer"]),
                    risk_rating=str(source["risk_rating"]),
                    materiality_threshold=str(source["materiality_threshold_decimal"]),
                    currency_code=str(source["currency_code"]),
                    actor_label=actor_label,
                    template_id=str(source["template_id"]) if source["template_id"] else None,
                    finalize=False,
                )
            roll_id = platform_id("ARF", workspace_id, source_period, target_period)
            self._event(
                actor_label=actor_label,
                object_type="account_reconciliation_roll_forward",
                object_id=roll_id,
                action="reconciliations.rolled_forward",
                version=len(rows),
                metadata={
                    "workspace_id": workspace_id,
                    "from_period": source_period,
                    "to_period": target_period,
                    "count": len(rows),
                },
            )
            return len(rows)

    def list_reconciliations(
        self,
        *,
        status: str = "",
        owner: str = "",
        period_name: str = "",
        entity_code: str = "",
        risk_rating: str = "",
    ) -> list[dict[str, Any]]:
        selected_status = normalize_text(status, default="")
        if selected_status and selected_status not in ACCOUNT_STATUSES:
            raise PlatformError("Unsupported account reconciliation status.")
        selected_risk = _risk(risk_rating) if risk_rating else ""
        with self._transaction():
            rows = self._rows_dict(
                self.connection.execute(
                    """SELECT * FROM reconforge.account_reconciliation_records
                WHERE tenant_id=%s AND (%s='' OR status=%s) AND (%s='' OR owner=%s)
                AND (%s='' OR period_name=%s) AND (%s='' OR entity_code=%s)
                AND (%s='' OR risk_rating=%s)
                ORDER BY period_name,entity_code,risk_rating DESC,account_code,id LIMIT 10000""",
                    (
                        self.tenant_id,
                        selected_status,
                        selected_status,
                        owner,
                        owner,
                        period_name,
                        period_name,
                        entity_code,
                        entity_code,
                        selected_risk,
                        selected_risk,
                    ),
                )
            )
            return [self._public_amounts(row) for row in rows]

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._get_reconciliation(reconciliation_id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._transaction():
            row = self._row_dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.account_reconciliation_templates WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, normalize_text(template_id, default="")),
                )
            )
            if row is None:
                raise PlatformError("Account reconciliation template not found.")
            return self._public_amounts(row)
