"""Tenant-scoped PostgreSQL adapter for immutable AP settlement evidence."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from reconforge.domain.payables_payment_link import (
    FinancePaymentEvidence,
    PayablesPaymentLinkError,
    payment_link_request_digest,
    validate_finance_payment_effect,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import (
    PostgresRepositoryScopeError,
    ensure_repository_tenant_scope,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
    encode_postgres_outbox_payload,
)
from reconforge.platform.common import PlatformError, platform_id


class PostgresPayablesPaymentLinkError(RuntimeError):
    """Safe storage failure for the PostgreSQL payment-link aggregate."""


class PostgresPayablesPaymentLinkRepository:
    """Allocate reviewed manual AP/cash effects while holding the invoice lock."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                ensure_repository_tenant_scope(self.connection, self.tenant_id)
                isolation = self.connection.execute("SHOW transaction_isolation").fetchone()
                value = isolation["transaction_isolation"] if isinstance(isolation, Mapping) else isolation[0]
                if str(value).lower() != "read committed":
                    raise PlatformError("Supplier payment settlement requires READ COMMITTED isolation.")
                yield
        except PostgresRepositoryScopeError as exc:
            raise PlatformError(str(exc)) from exc
        except (PlatformError, PostgresPayablesPaymentLinkError):
            raise
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise PlatformError("Supplier payment settlement conflicts with current retained state; reload before retrying.") from exc
            raise PostgresPayablesPaymentLinkError("PostgreSQL supplier payment settlement failed.") from exc

    def link_finance_payment(
        self,
        invoice_id: str,
        *,
        finance_effect_id: str,
        ap_account_id: str,
        cash_account_id: str,
        expected_invoice_version: int,
        command_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Atomically link one independent Finance effect to one AP invoice."""

        invoice_key = _text(invoice_id, "Supplier invoice id")
        effect_key = _text(finance_effect_id, "Finance effect id")
        ap_account = _text(ap_account_id, "Accounts payable account id")
        cash_account = _text(cash_account_id, "Cash account id")
        command_key = _text(command_id, "Command id")
        actor_id = _text(actor_label, "Settlement actor id")
        if len(command_key) > 160:
            raise PlatformError("Command id must not exceed 160 characters.")
        try:
            digest = payment_link_request_digest(
                invoice_id=invoice_key,
                finance_effect_id=effect_key,
                ap_account_id=ap_account,
                cash_account_id=cash_account,
                expected_invoice_version=expected_invoice_version,
                settlement_actor_id=actor_id,
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc
        with self._transaction():
            self._assert_current_actor(actor_id)
            invoice = self._invoice(invoice_key, lock=True)
            workspace_id = str(invoice["workspace_id"])
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{self.tenant_id}|{workspace_id}|{command_key}",),
            )
            replay = self._replay_if_present(
                workspace_id=workspace_id,
                command_id=command_key,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            if int(invoice["row_version"]) != expected_invoice_version:
                raise PlatformError("Supplier invoice changed concurrently; reload before linking payment evidence.")
            effect = self._effect(effect_key)
            evidence = self._validate(
                invoice=invoice,
                effect=effect,
                ap_account_id=ap_account,
                cash_account_id=cash_account,
                settlement_actor_id=actor_id,
            )
            existing = self.connection.execute(
                """SELECT id FROM reconforge.ap_payment_links
                   WHERE tenant_id=%s AND finance_effect_id=%s FOR KEY SHARE""",
                (self.tenant_id, evidence.finance_effect_id),
            ).fetchone()
            if existing is not None:
                raise PlatformError("Financial posting effect is already allocated to a supplier invoice.")
            allocated_before = self.connection.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS amount
                   FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s""",
                (self.tenant_id, invoice_key),
            ).fetchone()
            prior_amount = int(_value(allocated_before, "amount", 0))
            allocated_after = prior_amount + evidence.amount_minor
            invoice_total = int(invoice["total_minor"])
            if allocated_after > invoice_total:
                raise PlatformError("Payment allocation exceeds the supplier invoice total.")
            link_id = platform_id("APPAY", workspace_id, invoice_key, evidence.finance_effect_id)
            audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_user_id=actor_id,
                actor_label=actor_id,
                object_type="ap_payment_link",
                object_id=link_id,
                action="ap_payment_linked",
                metadata={
                    "supplier_invoice_id": invoice_key,
                    "finance_effect_id": evidence.finance_effect_id,
                    "finance_entry_id": evidence.finance_entry_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                    "invoice_version_before": expected_invoice_version,
                },
            )
            outbox_event_id = platform_id("OBX", "ap.payment_linked", link_id)
            payload = {
                "audit_event_id": audit.id,
                "payment_link_id": link_id,
                "supplier_invoice_id": invoice_key,
                "finance_effect_id": evidence.finance_effect_id,
                "finance_entry_id": evidence.finance_entry_id,
                "amount_minor": evidence.amount_minor,
                "currency_code": evidence.currency_code,
            }
            try:
                payload_text = encode_postgres_outbox_payload(payload).text
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link outbox payload is invalid.") from exc
            self.connection.execute(
                """INSERT INTO reconforge.outbox_events
                   (tenant_id,event_id,event_type,aggregate_type,aggregate_id,
                    workspace_id,organization_id,legal_entity_id,payload)
                   VALUES (%s,%s,'ap.payment_linked','ap_payment_link',%s,%s,%s,%s,CAST(%s AS jsonb))""",
                (
                    self.tenant_id,
                    outbox_event_id,
                    link_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    payload_text,
                ),
            )
            self.connection.execute(
                """INSERT INTO reconforge.ap_payment_links
                   (tenant_id,id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,
                    finance_effect_id,finance_entry_id,ap_account_id,cash_account_id,amount_minor,
                    currency_code,payment_date,finance_validation_digest,finance_posted_actor_id,
                    settlement_actor_id,invoice_version_before,audit_event_id,outbox_event_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    link_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    invoice_key,
                    evidence.finance_effect_id,
                    evidence.finance_entry_id,
                    ap_account,
                    cash_account,
                    evidence.amount_minor,
                    evidence.currency_code,
                    evidence.payment_date,
                    evidence.validation_digest,
                    evidence.posted_actor_id,
                    actor_id,
                    expected_invoice_version,
                    audit.id,
                    outbox_event_id,
                ),
            )
            updated = self.connection.execute(
                """SELECT status,row_version FROM reconforge.ap_supplier_invoices
                   WHERE tenant_id=%s AND id=%s FOR KEY SHARE""",
                (self.tenant_id, invoice_key),
            ).fetchone()
            expected_status = "Paid" if allocated_after == invoice_total else "Approved"
            if (
                updated is None
                or str(_value(updated, "status", 0)) != expected_status
                or int(_value(updated, "row_version", 1)) != expected_invoice_version + 1
            ):
                raise PlatformError("Supplier invoice payment state was not advanced by retained payment evidence.")
            result = _result(
                link_id=link_id,
                invoice=invoice,
                evidence=evidence,
                ap_account_id=ap_account,
                cash_account_id=cash_account,
                settlement_actor_id=actor_id,
                invoice_version_before=expected_invoice_version,
                allocated_minor=allocated_after,
                audit_event_id=audit.id,
                outbox_event_id=outbox_event_id,
            )
            try:
                receipt = encode_financial_idempotency_response(result)
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link idempotency receipt is invalid.") from exc
            self.connection.execute(
                """INSERT INTO reconforge.ap_payment_link_commands
                   (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,
                    settlement_actor_id,request_digest,result_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb))""",
                (
                    self.tenant_id,
                    workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    command_key,
                    actor_id,
                    digest,
                    receipt.text,
                ),
            )
            return result

    def authorization_amount(
        self,
        invoice_id: str,
        *,
        finance_effect_id: str,
        ap_account_id: str,
        cash_account_id: str,
        actor_label: str,
    ) -> Decimal:
        """Return the immutable effect amount used by bounded server policy.

        This read runs under the same tenant/RLS scope as the mutation and
        validates the complete AP/cash shape.  The API never accepts a client
        supplied settlement amount for ABAC evaluation.
        """

        invoice_key = _text(invoice_id, "Supplier invoice id")
        effect_key = _text(finance_effect_id, "Finance effect id")
        ap_account = _text(ap_account_id, "Accounts payable account id")
        cash_account = _text(cash_account_id, "Cash account id")
        actor_id = _text(actor_label, "Settlement actor id")
        with self._transaction():
            self._assert_current_actor(actor_id)
            invoice = self._invoice(invoice_key)
            effect = self._effect(effect_key)
            evidence = self._validate(
                invoice=invoice,
                effect=effect,
                ap_account_id=ap_account,
                cash_account_id=cash_account,
                settlement_actor_id=actor_id,
            )
            return Decimal(evidence.amount_minor)

    def list_payment_links(self, invoice_id: str, *, actor_label: str = "local-cli") -> list[dict[str, Any]]:
        """Read ordered immutable payment links under the caller's tenant scope."""

        del actor_label  # API/server authorization owns the read permission on PostgreSQL.
        invoice_key = _text(invoice_id, "Supplier invoice id")
        with self._transaction():
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,
                          finance_effect_id,finance_entry_id,ap_account_id,cash_account_id,amount_minor,
                          currency_code,payment_date,finance_validation_digest,finance_posted_actor_id,
                          settlement_actor_id,invoice_version_before,audit_event_id,outbox_event_id,created_at
                   FROM reconforge.ap_payment_links
                   WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY invoice_version_before,id""",
                (self.tenant_id, invoice_key),
            ).fetchall()
            return [_row(row) for row in rows]

    def _assert_current_actor(self, actor_id: str) -> None:
        row = self.connection.execute(
            """SELECT id FROM reconforge.identity_users
               WHERE tenant_id=%s AND id=%s AND NOT disabled FOR SHARE""",
            (self.tenant_id, actor_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Authenticated settlement actor is unavailable.")

    def _invoice(self, invoice_id: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " FOR NO KEY UPDATE" if lock else ""
        row = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,currency_code,total_minor,status,
                      created_by,approved_by,row_version
               FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s""" + suffix,
            (self.tenant_id, invoice_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Supplier invoice not found.")
        return _row(row)

    def _effect(self, effect_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT effect.*,entry.validator_actor_id
               FROM reconforge.finance_posting_effects effect
               JOIN reconforge.finance_entries entry ON entry.tenant_id=effect.tenant_id AND entry.id=effect.entry_id
               WHERE effect.tenant_id=%s AND effect.id=%s FOR KEY SHARE OF effect,entry""",
            (self.tenant_id, effect_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Financial posting effect not found.")
        return _row(row)

    def _validate(
        self,
        *,
        invoice: Mapping[str, object],
        effect: Mapping[str, object],
        ap_account_id: str,
        cash_account_id: str,
        settlement_actor_id: str,
    ) -> FinancePaymentEvidence:
        try:
            return validate_finance_payment_effect(
                invoice=invoice,
                effect=effect,
                ap_account_id=ap_account_id,
                cash_account_id=cash_account_id,
                settlement_actor_id=settlement_actor_id,
                invoice_creator_actor_id=invoice.get("created_by"),
                invoice_approver_actor_id=invoice.get("approved_by"),
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc

    def _replay_if_present(
        self,
        *,
        workspace_id: str,
        command_id: str,
        actor_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT settlement_actor_id,request_digest,result_json::text AS result_json
               FROM reconforge.ap_payment_link_commands
               WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""",
            (self.tenant_id, workspace_id, command_id),
        ).fetchone()
        if row is None:
            return None
        if (
            str(_value(row, "settlement_actor_id", 0)) != actor_id
            or str(_value(row, "request_digest", 1)) != request_digest
        ):
            raise PlatformError("Payment-link idempotency key was already used with a different request or actor.")
        try:
            result = decode_financial_idempotency_response(_value(row, "result_json", 2)).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored payment-link idempotency receipt is invalid.") from exc
        self._validate_replay(result, workspace_id=workspace_id, actor_id=actor_id)
        return result

    def _validate_replay(self, result: Mapping[str, object], *, workspace_id: str, actor_id: str) -> None:
        link_id = result.get("payment_link_id")
        if not isinstance(link_id, str) or not link_id:
            raise PlatformError("Stored payment-link idempotency receipt is invalid.")
        row = self.connection.execute(
            """SELECT * FROM reconforge.ap_payment_links
               WHERE tenant_id=%s AND id=%s AND workspace_id=%s FOR KEY SHARE""",
            (self.tenant_id, link_id, workspace_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Stored payment-link idempotency receipt does not match retained evidence.")
        link = _row(row)
        if str(link["settlement_actor_id"]) != actor_id or dict(result) != _result_from_link(self.connection, self.tenant_id, link):
            raise PlatformError("Stored payment-link idempotency receipt does not match retained evidence.")


def _result(
    *,
    link_id: str,
    invoice: Mapping[str, object],
    evidence: FinancePaymentEvidence,
    ap_account_id: str,
    cash_account_id: str,
    settlement_actor_id: str,
    invoice_version_before: int,
    allocated_minor: int,
    audit_event_id: str,
    outbox_event_id: str,
) -> dict[str, Any]:
    invoice_total = int(invoice["total_minor"])
    return {
        "payment_link_id": link_id,
        "supplier_invoice_id": str(invoice["id"]),
        "finance_effect_id": evidence.finance_effect_id,
        "finance_entry_id": evidence.finance_entry_id,
        "ap_account_id": ap_account_id,
        "cash_account_id": cash_account_id,
        "amount_minor": evidence.amount_minor,
        "currency_code": evidence.currency_code,
        "payment_date": evidence.payment_date,
        "finance_validation_digest": evidence.validation_digest,
        "finance_posted_actor_id": evidence.posted_actor_id,
        "settlement_actor_id": settlement_actor_id,
        "invoice_version_before": invoice_version_before,
        "invoice_version_after": invoice_version_before + 1,
        "allocated_minor": allocated_minor,
        "outstanding_minor": invoice_total - allocated_minor,
        "invoice_status": "Paid" if allocated_minor == invoice_total else "Approved",
        "audit_event_id": audit_event_id,
        "outbox_event_id": outbox_event_id,
    }


def _result_from_link(connection: Any, tenant_id: str, link: Mapping[str, object]) -> dict[str, Any]:
    invoice = connection.execute(
        """SELECT id,total_minor FROM reconforge.ap_supplier_invoices
           WHERE tenant_id=%s AND id=%s FOR KEY SHARE""",
        (tenant_id, link["supplier_invoice_id"]),
    ).fetchone()
    if invoice is None:
        raise PlatformError("Retained payment link references a missing supplier invoice.")
    total = int(_value(invoice, "total_minor", 1))
    allocated_row = connection.execute(
        """SELECT COALESCE(SUM(amount_minor),0) AS amount
           FROM reconforge.ap_payment_links
           WHERE tenant_id=%s AND supplier_invoice_id=%s AND invoice_version_before<=%s""",
        (tenant_id, link["supplier_invoice_id"], link["invoice_version_before"]),
    ).fetchone()
    allocated = int(_value(allocated_row, "amount", 0))
    if allocated > total:
        raise PlatformError("Retained payment link has an invalid supplier invoice allocation.")
    return {
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(link["supplier_invoice_id"]),
        "finance_effect_id": str(link["finance_effect_id"]),
        "finance_entry_id": str(link["finance_entry_id"]),
        "ap_account_id": str(link["ap_account_id"]),
        "cash_account_id": str(link["cash_account_id"]),
        "amount_minor": int(link["amount_minor"]),
        "currency_code": str(link["currency_code"]),
        "payment_date": str(link["payment_date"]),
        "finance_validation_digest": str(link["finance_validation_digest"]),
        "finance_posted_actor_id": str(link["finance_posted_actor_id"]),
        "settlement_actor_id": str(link["settlement_actor_id"]),
        "invoice_version_before": int(link["invoice_version_before"]),
        "invoice_version_after": int(link["invoice_version_before"]) + 1,
        "allocated_minor": allocated,
        "outstanding_minor": total - allocated,
        "invoice_status": "Paid" if allocated == total else "Approved",
        "audit_event_id": str(link["audit_event_id"]),
        "outbox_event_id": str(link["outbox_event_id"]),
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PlatformError(f"{field} must be text.")
    text = value.strip()
    if not text or len(text) > 160 or any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise PlatformError(f"{field} is invalid.")
    return text


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _row(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {str(key): row[key] for key in keys()}
    raise PostgresPayablesPaymentLinkError("PostgreSQL row does not expose stable column names.")


__all__ = ["PostgresPayablesPaymentLinkError", "PostgresPayablesPaymentLinkRepository"]
