"""Tenant-scoped PostgreSQL adapter for immutable AP settlement evidence."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from reconforge.domain.finance_posting import canonical_json
from reconforge.domain.payables_payment_link import (
    FinancePaymentEvidence,
    FinancePaymentReversalEvidence,
    PayablesPaymentLinkError,
    payment_link_request_digest,
    payment_link_reversal_request_digest,
    validate_finance_payment_effect,
    validate_finance_payment_reversal_effect,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import (
    PostgresRepositoryScopeError,
    ensure_repository_tenant_scope,
)
from reconforge.io.finance_posting import decode_posting_snapshot
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
        actor_token = _text(actor_label, "Settlement actor id")
        if len(command_key) > 160:
            raise PlatformError("Command id must not exceed 160 characters.")
        with self._transaction():
            actor_id = self._canonical_principal_id(
                actor_token, field="Settlement actor id"
            )
            self._assert_current_actor(actor_id)
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
            if _stored_integer(invoice["row_version"], "supplier invoice row version") != expected_invoice_version:
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
            prior_amount = _active_allocation(self.connection, self.tenant_id, invoice_key)
            allocated_after = prior_amount + evidence.amount_minor
            invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
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
                or _stored_integer(_value(updated, "row_version", 1), "supplier invoice row version")
                != expected_invoice_version + 1
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
        expected_invoice_version: int,
        command_id: str,
        actor_label: str,
    ) -> Decimal:
        """Return a retained or admissible effect amount for bounded server policy.

        This read runs under the same tenant/RLS scope as the mutation.  It
        first recognizes an exact retained command receipt, allowing a lost
        response for a full allocation to be retried after its invoice has
        become ``Paid``.  A new command still validates the complete AP/cash
        shape.  The API never accepts a client supplied settlement amount for
        ABAC evaluation.
        """

        invoice_key = _text(invoice_id, "Supplier invoice id")
        effect_key = _text(finance_effect_id, "Finance effect id")
        ap_account = _text(ap_account_id, "Accounts payable account id")
        cash_account = _text(cash_account_id, "Cash account id")
        command_key = _text(command_id, "Command id")
        actor_token = _text(actor_label, "Settlement actor id")
        if len(command_key) > 160:
            raise PlatformError("Command id must not exceed 160 characters.")
        with self._transaction():
            actor_id = self._canonical_principal_id(
                actor_token, field="Settlement actor id"
            )
            self._assert_current_actor(actor_id)
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
            invoice = self._invoice(invoice_key)
            replay = self._replay_if_present(
                workspace_id=str(invoice["workspace_id"]),
                command_id=command_key,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                return Decimal(_stored_integer(replay.get("amount_minor"), "retained payment-link amount"))
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

    def reverse_finance_payment_link(
        self,
        invoice_id: str,
        payment_link_id: str,
        *,
        reversal_finance_effect_id: str,
        expected_invoice_version: int,
        command_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Append the only allowed AP allocation unwind: a posted full inverse."""

        invoice_key = _text(invoice_id, "Supplier invoice id")
        link_key = _text(payment_link_id, "Payment link id")
        effect_key = _text(reversal_finance_effect_id, "Reversal Finance effect id")
        command_key = _text(command_id, "Command id")
        actor_token = _text(actor_label, "Reversal actor id")
        if len(command_key) > 160:
            raise PlatformError("Command id must not exceed 160 characters.")
        with self._transaction():
            actor_id = self._canonical_principal_id(actor_token, field="Reversal actor id")
            self._assert_current_actor(actor_id)
            try:
                digest = payment_link_reversal_request_digest(
                    invoice_id=invoice_key,
                    payment_link_id=link_key,
                    reversal_finance_effect_id=effect_key,
                    expected_invoice_version=expected_invoice_version,
                    reversal_actor_id=actor_id,
                )
            except PayablesPaymentLinkError as exc:
                raise PlatformError(str(exc)) from exc
            invoice = self._invoice(invoice_key, lock=True)
            workspace_id = str(invoice["workspace_id"])
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{self.tenant_id}|{workspace_id}|{command_key}",),
            )
            replay = self._replay_reversal_if_present(
                workspace_id=workspace_id,
                command_id=command_key,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            if _stored_integer(invoice["row_version"], "supplier invoice row version") != expected_invoice_version:
                raise PlatformError("Supplier invoice changed concurrently; reload before reversing payment evidence.")
            link_row = self.connection.execute(
                """SELECT * FROM reconforge.ap_payment_links
                   WHERE tenant_id=%s AND id=%s AND supplier_invoice_id=%s FOR KEY SHARE""",
                (self.tenant_id, link_key, invoice_key),
            ).fetchone()
            if link_row is None:
                raise PlatformError("Supplier payment link not found for this invoice.")
            link = _row(link_row)
            effect = self._effect(effect_key)
            evidence = self._validate_reversal(
                invoice=invoice,
                link=link,
                effect=effect,
                reversal_actor_id=actor_id,
            )
            existing = self.connection.execute(
                """SELECT id FROM reconforge.ap_payment_link_reversals
                   WHERE tenant_id=%s AND (payment_link_id=%s OR reversal_finance_effect_id=%s) FOR KEY SHARE""",
                (self.tenant_id, link_key, evidence.reversal_finance_effect_id),
            ).fetchone()
            if existing is not None:
                raise PlatformError("Supplier payment link or Finance reversal effect is already reversed.")
            allocated_before = _active_allocation(self.connection, self.tenant_id, invoice_key)
            allocated_after = allocated_before - evidence.amount_minor
            if allocated_after < 0:
                raise PlatformError("Retained supplier payment allocation cannot become negative.")
            reversal_id = platform_id("APPAYREV", workspace_id, link_key, evidence.reversal_finance_effect_id)
            audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_user_id=actor_id,
                actor_label=actor_id,
                object_type="ap_payment_link_reversal",
                object_id=reversal_id,
                action="ap_payment_link_reversed",
                metadata={
                    "payment_link_id": link_key,
                    "supplier_invoice_id": invoice_key,
                    "original_finance_effect_id": str(link["finance_effect_id"]),
                    "reversal_finance_effect_id": evidence.reversal_finance_effect_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                    "invoice_version_before": expected_invoice_version,
                },
            )
            outbox_event_id = platform_id("OBX", "ap.payment_link_reversed", reversal_id)
            payload = {
                "audit_event_id": audit.id,
                "payment_link_reversal_id": reversal_id,
                "payment_link_id": link_key,
                "supplier_invoice_id": invoice_key,
                "reversal_finance_effect_id": evidence.reversal_finance_effect_id,
                "reversal_finance_entry_id": evidence.reversal_finance_entry_id,
                "amount_minor": evidence.amount_minor,
                "currency_code": evidence.currency_code,
            }
            try:
                payload_text = encode_postgres_outbox_payload(payload).text
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link reversal outbox payload is invalid.") from exc
            self.connection.execute(
                """INSERT INTO reconforge.outbox_events
                   (tenant_id,event_id,event_type,aggregate_type,aggregate_id,
                    workspace_id,organization_id,legal_entity_id,payload)
                   VALUES (%s,%s,'ap.payment_link_reversed','ap_payment_link_reversal',%s,%s,%s,%s,CAST(%s AS jsonb))""",
                (
                    self.tenant_id,
                    outbox_event_id,
                    reversal_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    payload_text,
                ),
            )
            self.connection.execute(
                """INSERT INTO reconforge.ap_payment_link_reversals
                   (tenant_id,id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,payment_link_id,
                    reversal_finance_effect_id,reversal_finance_entry_id,amount_minor,currency_code,reversal_date,
                    finance_validation_digest,finance_posted_actor_id,reversal_actor_id,invoice_version_before,
                    audit_event_id,outbox_event_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    reversal_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    invoice_key,
                    link_key,
                    evidence.reversal_finance_effect_id,
                    evidence.reversal_finance_entry_id,
                    evidence.amount_minor,
                    evidence.currency_code,
                    evidence.reversal_date,
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
            invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
            expected_status = "Paid" if allocated_after == invoice_total else "Approved"
            if (
                updated is None
                or str(_value(updated, "status", 0)) != expected_status
                or _stored_integer(_value(updated, "row_version", 1), "supplier invoice row version")
                != expected_invoice_version + 1
            ):
                raise PlatformError("Supplier invoice payment state was not advanced by retained reversal evidence.")
            result = _reversal_result(
                reversal_id=reversal_id,
                link=link,
                invoice=invoice,
                evidence=evidence,
                reversal_actor_id=actor_id,
                invoice_version_before=expected_invoice_version,
                allocated_minor=allocated_after,
                audit_event_id=audit.id,
                outbox_event_id=outbox_event_id,
            )
            try:
                receipt = encode_financial_idempotency_response(result)
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link reversal idempotency receipt is invalid.") from exc
            self.connection.execute(
                """INSERT INTO reconforge.ap_payment_link_reversal_commands
                   (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,
                    reversal_actor_id,request_digest,result_json)
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

    def authorization_reversal_amount(
        self,
        invoice_id: str,
        *,
        payment_link_id: str,
        reversal_finance_effect_id: str,
        expected_invoice_version: int,
        command_id: str,
        actor_label: str,
    ) -> Decimal:
        """Return a retained or admitted reversal amount for server-side ABAC."""

        invoice_key = _text(invoice_id, "Supplier invoice id")
        link_key = _text(payment_link_id, "Payment link id")
        effect_key = _text(reversal_finance_effect_id, "Reversal Finance effect id")
        command_key = _text(command_id, "Command id")
        actor_token = _text(actor_label, "Reversal actor id")
        if len(command_key) > 160:
            raise PlatformError("Command id must not exceed 160 characters.")
        with self._transaction():
            actor_id = self._canonical_principal_id(actor_token, field="Reversal actor id")
            self._assert_current_actor(actor_id)
            try:
                digest = payment_link_reversal_request_digest(
                    invoice_id=invoice_key,
                    payment_link_id=link_key,
                    reversal_finance_effect_id=effect_key,
                    expected_invoice_version=expected_invoice_version,
                    reversal_actor_id=actor_id,
                )
            except PayablesPaymentLinkError as exc:
                raise PlatformError(str(exc)) from exc
            invoice = self._invoice(invoice_key)
            replay = self._replay_reversal_if_present(
                workspace_id=str(invoice["workspace_id"]),
                command_id=command_key,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                return Decimal(
                    _stored_integer(replay.get("amount_minor"), "retained payment-link reversal amount")
                )
            link_row = self.connection.execute(
                """SELECT * FROM reconforge.ap_payment_links
                   WHERE tenant_id=%s AND id=%s AND supplier_invoice_id=%s FOR KEY SHARE""",
                (self.tenant_id, link_key, invoice_key),
            ).fetchone()
            if link_row is None:
                raise PlatformError("Supplier payment link not found for this invoice.")
            evidence = self._validate_reversal(
                invoice=invoice,
                link=_row(link_row),
                effect=self._effect(effect_key),
                reversal_actor_id=actor_id,
            )
            return Decimal(evidence.amount_minor)

    def list_payment_link_reversals(
        self, invoice_id: str, *, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        """Read immutable AP reversal evidence under the caller's tenant scope."""

        del actor_label
        invoice_key = _text(invoice_id, "Supplier invoice id")
        with self._transaction():
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,payment_link_id,
                          reversal_finance_effect_id,reversal_finance_entry_id,amount_minor,currency_code,
                          reversal_date,finance_validation_digest,finance_posted_actor_id,reversal_actor_id,
                          invoice_version_before,audit_event_id,outbox_event_id,created_at
                   FROM reconforge.ap_payment_link_reversals
                   WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY invoice_version_before,id""",
                (self.tenant_id, invoice_key),
            ).fetchall()
            return [_row(row) for row in rows]

    def _canonical_principal_id(self, value: object, *, field: str) -> str:
        """Resolve one retained tenant-local identity alias without guessing.

        Older Finance and AP evidence can contain a user-facing username where
        current tables expect an immutable identity id.  A value that happens
        to match one user's id and another user's username is intentionally
        rejected: choosing either would silently weaken segregation of duties.
        """

        actor = _text(value, field)
        rows = self.connection.execute(
            """SELECT id FROM reconforge.identity_users
               WHERE tenant_id=%s AND (id=%s OR username=%s)
               ORDER BY id FOR KEY SHARE""",
            (self.tenant_id, actor, actor),
        ).fetchall()
        if len(rows) != 1:
            raise PlatformError(f"{field} does not resolve to one tenant principal.")
        return _text(_value(rows[0], "id", 0), field)

    def _assert_current_actor(self, actor_id: str) -> None:
        row = self.connection.execute(
            """SELECT id FROM reconforge.identity_users
               WHERE tenant_id=%s AND id=%s AND NOT disabled FOR SHARE""",
            (self.tenant_id, actor_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Authenticated settlement actor is unavailable.")

    def _invoice(self, invoice_id: str, *, lock: bool = False) -> dict[str, Any]:
        if lock:
            row = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,currency_code,total_minor,status,
                          created_by,approved_by,row_version
                   FROM reconforge.ap_supplier_invoices
                   WHERE tenant_id=%s AND id=%s FOR NO KEY UPDATE""",
                (self.tenant_id, invoice_id),
            ).fetchone()
        else:
            row = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,currency_code,total_minor,status,
                          created_by,approved_by,row_version
                   FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s""",
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

    def _canonical_finance_effect_identities(
        self, effect: Mapping[str, object]
    ) -> dict[str, Any]:
        """Return a Finance effect whose actor fields are canonical ids.

        The stored posting rows deliberately retain their original actor text
        for immutable evidence.  This adapter canonicalizes the narrow
        authorization projection before it performs any SoD comparison; it
        never rewrites historic Finance evidence.
        """

        normalized = dict(effect)
        try:
            snapshot_value = normalized.get("snapshot_json", normalized.get("snapshot"))
            if isinstance(snapshot_value, Mapping):
                snapshot_value = canonical_json(dict(snapshot_value))
            snapshot = decode_posting_snapshot(snapshot_value).payload
        except (PersistedJsonError, TypeError, ValueError) as exc:
            raise PlatformError("Financial posting identity evidence is invalid.") from exc
        header = snapshot.get("entry")
        if not isinstance(header, Mapping):
            raise PlatformError("Financial posting identity evidence is invalid.")
        normalized_header = dict(header)
        normalized_header["preparer_actor_id"] = self._canonical_principal_id(
            normalized_header.get("preparer_actor_id"),
            field="Financial preparer actor id",
        )
        normalized_snapshot = dict(snapshot)
        normalized_snapshot["entry"] = normalized_header
        normalized["snapshot_json"] = normalized_snapshot
        normalized["validator_actor_id"] = self._canonical_principal_id(
            normalized.get("validator_actor_id"),
            field="Financial validator actor id",
        )
        normalized["posted_actor_id"] = self._canonical_principal_id(
            normalized.get("posted_actor_id"),
            field="Financial posted actor id",
        )
        return normalized

    @staticmethod
    def _canonical_finance_role_ids(effect: Mapping[str, object]) -> tuple[str, str, str]:
        snapshot = effect.get("snapshot_json")
        header = snapshot.get("entry") if isinstance(snapshot, Mapping) else None
        if not isinstance(header, Mapping):
            raise PlatformError("Financial posting identity evidence is invalid.")
        preparer = _text(header.get("preparer_actor_id"), "Financial preparer actor id")
        validator = _text(effect.get("validator_actor_id"), "Financial validator actor id")
        poster = _text(effect.get("posted_actor_id"), "Financial posted actor id")
        if len({preparer, validator, poster}) != 3:
            raise PlatformError(
                "Financial evidence lacks independent preparation, review, and posting."
            )
        return preparer, validator, poster

    def _canonical_payment_link_identities(
        self, link: Mapping[str, object]
    ) -> dict[str, Any]:
        """Resolve the original settlement and Finance participants on reversal."""

        normalized = dict(link)
        normalized["settlement_actor_id"] = self._canonical_principal_id(
            normalized.get("settlement_actor_id"),
            field="Payment-link settlement actor id",
        )
        retained_poster = self._canonical_principal_id(
            normalized.get("finance_posted_actor_id"),
            field="Payment-link Finance posted actor id",
        )
        original_effect_id = _text(
            normalized.get("finance_effect_id"), "Payment-link Finance effect id"
        )
        original_effect = self._canonical_finance_effect_identities(
            self._effect(original_effect_id)
        )
        _preparer, _validator, original_poster = self._canonical_finance_role_ids(
            original_effect
        )
        if retained_poster != original_poster:
            raise PlatformError(
                "Retained payment-link Finance identity does not match its original evidence."
            )
        normalized["finance_posted_actor_id"] = retained_poster
        return normalized

    def _validate(
        self,
        *,
        invoice: Mapping[str, object],
        effect: Mapping[str, object],
        ap_account_id: str,
        cash_account_id: str,
        settlement_actor_id: str,
    ) -> FinancePaymentEvidence:
        settlement_id = self._canonical_principal_id(
            settlement_actor_id, field="Settlement actor id"
        )
        creator_id = self._canonical_principal_id(
            invoice.get("created_by"), field="Invoice creator actor id"
        )
        approver_id = self._canonical_principal_id(
            invoice.get("approved_by"), field="Invoice approver actor id"
        )
        try:
            return validate_finance_payment_effect(
                invoice=invoice,
                effect=self._canonical_finance_effect_identities(effect),
                ap_account_id=ap_account_id,
                cash_account_id=cash_account_id,
                settlement_actor_id=settlement_id,
                invoice_creator_actor_id=creator_id,
                invoice_approver_actor_id=approver_id,
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc

    def _validate_reversal(
        self,
        *,
        invoice: Mapping[str, object],
        link: Mapping[str, object],
        effect: Mapping[str, object],
        reversal_actor_id: str,
    ) -> FinancePaymentReversalEvidence:
        creator_id = self._canonical_principal_id(
            invoice.get("created_by"), field="Invoice creator actor id"
        )
        approver_id = self._canonical_principal_id(
            invoice.get("approved_by"), field="Invoice approver actor id"
        )
        normalized_link = self._canonical_payment_link_identities(link)
        if normalized_link["settlement_actor_id"] in {creator_id, approver_id} or normalized_link[
            "finance_posted_actor_id"
        ] in {creator_id, approver_id}:
            raise PlatformError("Retained payment-link identity violates separation of duties.")
        reversal_id = self._canonical_principal_id(
            reversal_actor_id, field="Reversal actor id"
        )
        try:
            return validate_finance_payment_reversal_effect(
                invoice=invoice,
                payment_link=normalized_link,
                effect=self._canonical_finance_effect_identities(effect),
                reversal_actor_id=reversal_id,
                invoice_creator_actor_id=creator_id,
                invoice_approver_actor_id=approver_id,
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
            self._canonical_principal_id(
                _value(row, "settlement_actor_id", 0),
                field="Retained payment-link settlement actor id",
            )
            != actor_id
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
        if (
            self._canonical_principal_id(
                link["settlement_actor_id"],
                field="Retained payment-link settlement actor id",
            )
            != actor_id
            or dict(result) != _result_from_link(self.connection, self.tenant_id, link)
        ):
            raise PlatformError("Stored payment-link idempotency receipt does not match retained evidence.")

    def _replay_reversal_if_present(
        self,
        *,
        workspace_id: str,
        command_id: str,
        actor_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT reversal_actor_id,request_digest,result_json::text AS result_json
               FROM reconforge.ap_payment_link_reversal_commands
               WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""",
            (self.tenant_id, workspace_id, command_id),
        ).fetchone()
        if row is None:
            return None
        if (
            self._canonical_principal_id(
                _value(row, "reversal_actor_id", 0),
                field="Retained payment-link reversal actor id",
            )
            != actor_id
            or str(_value(row, "request_digest", 1)) != request_digest
        ):
            raise PlatformError(
                "Payment-link reversal idempotency key was already used with a different request or actor."
            )
        try:
            result = decode_financial_idempotency_response(_value(row, "result_json", 2)).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored payment-link reversal idempotency receipt is invalid.") from exc
        self._validate_reversal_replay(result, workspace_id=workspace_id, actor_id=actor_id)
        return result

    def _validate_reversal_replay(
        self, result: Mapping[str, object], *, workspace_id: str, actor_id: str
    ) -> None:
        reversal_id = result.get("payment_link_reversal_id")
        if not isinstance(reversal_id, str) or not reversal_id:
            raise PlatformError("Stored payment-link reversal idempotency receipt is invalid.")
        row = self.connection.execute(
            """SELECT * FROM reconforge.ap_payment_link_reversals
               WHERE tenant_id=%s AND id=%s AND workspace_id=%s FOR KEY SHARE""",
            (self.tenant_id, reversal_id, workspace_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Stored payment-link reversal receipt does not match retained evidence.")
        reversal = _row(row)
        if (
            self._canonical_principal_id(
                reversal["reversal_actor_id"],
                field="Retained payment-link reversal actor id",
            )
            != actor_id
            or dict(result) != _result_from_reversal(self.connection, self.tenant_id, reversal)
        ):
            raise PlatformError("Stored payment-link reversal receipt does not match retained evidence.")


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
    invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
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
    total = _stored_integer(_value(invoice, "total_minor", 1), "supplier invoice total")
    allocated_row = connection.execute(
        """SELECT COALESCE(SUM(history.amount_minor),0)::bigint AS amount
           FROM reconforge.ap_payment_links history
           WHERE history.tenant_id=%s AND history.supplier_invoice_id=%s
             AND history.invoice_version_before<=%s
             AND NOT EXISTS(
                SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                WHERE reversal.tenant_id=history.tenant_id AND reversal.payment_link_id=history.id
                  AND reversal.invoice_version_before<=%s
             )""",
        (
            tenant_id,
            link["supplier_invoice_id"],
            link["invoice_version_before"],
            link["invoice_version_before"],
        ),
    ).fetchone()
    allocated = _stored_integer(_value(allocated_row, "amount", 0), "retained payment-link allocated amount")
    if allocated > total:
        raise PlatformError("Retained payment link has an invalid supplier invoice allocation.")
    amount_minor = _stored_integer(link["amount_minor"], "payment-link amount")
    version_before = _stored_integer(link["invoice_version_before"], "payment-link invoice version")
    return {
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(link["supplier_invoice_id"]),
        "finance_effect_id": str(link["finance_effect_id"]),
        "finance_entry_id": str(link["finance_entry_id"]),
        "ap_account_id": str(link["ap_account_id"]),
        "cash_account_id": str(link["cash_account_id"]),
        "amount_minor": amount_minor,
        "currency_code": str(link["currency_code"]),
        "payment_date": str(link["payment_date"]),
        "finance_validation_digest": str(link["finance_validation_digest"]),
        "finance_posted_actor_id": str(link["finance_posted_actor_id"]),
        "settlement_actor_id": str(link["settlement_actor_id"]),
        "invoice_version_before": version_before,
        "invoice_version_after": version_before + 1,
        "allocated_minor": allocated,
        "outstanding_minor": total - allocated,
        "invoice_status": "Paid" if allocated == total else "Approved",
        "audit_event_id": str(link["audit_event_id"]),
        "outbox_event_id": str(link["outbox_event_id"]),
    }


def _active_allocation(
    connection: Any,
    tenant_id: str,
    invoice_id: str,
    *,
    through_version: int | None = None,
) -> int:
    """Read the active allocation at the requested immutable history point."""

    if through_version is None:
        row = connection.execute(
            """SELECT COALESCE(SUM(link.amount_minor),0)::bigint AS amount
               FROM reconforge.ap_payment_links link
               WHERE link.tenant_id=%s AND link.supplier_invoice_id=%s
                 AND NOT EXISTS(
                    SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                    WHERE reversal.tenant_id=link.tenant_id AND reversal.payment_link_id=link.id
                 )""",
            (tenant_id, invoice_id),
        ).fetchone()
    else:
        row = connection.execute(
            """SELECT COALESCE(SUM(link.amount_minor),0)::bigint AS amount
               FROM reconforge.ap_payment_links link
               WHERE link.tenant_id=%s AND link.supplier_invoice_id=%s
                 AND link.invoice_version_before<=%s
                 AND NOT EXISTS(
                    SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                    WHERE reversal.tenant_id=link.tenant_id AND reversal.payment_link_id=link.id
                      AND reversal.invoice_version_before<=%s
                 )""",
            (tenant_id, invoice_id, through_version, through_version),
        ).fetchone()
    return _stored_integer(_value(row, "amount", 0), "retained payment-link allocated amount")


def _reversal_result(
    *,
    reversal_id: str,
    link: Mapping[str, object],
    invoice: Mapping[str, object],
    evidence: FinancePaymentReversalEvidence,
    reversal_actor_id: str,
    invoice_version_before: int,
    allocated_minor: int,
    audit_event_id: str,
    outbox_event_id: str,
) -> dict[str, Any]:
    total = _stored_integer(invoice["total_minor"], "supplier invoice total")
    return {
        "payment_link_reversal_id": reversal_id,
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(invoice["id"]),
        "original_finance_effect_id": str(link["finance_effect_id"]),
        "original_finance_entry_id": str(link["finance_entry_id"]),
        "reversal_finance_effect_id": evidence.reversal_finance_effect_id,
        "reversal_finance_entry_id": evidence.reversal_finance_entry_id,
        "amount_minor": evidence.amount_minor,
        "currency_code": evidence.currency_code,
        "reversal_date": evidence.reversal_date,
        "finance_validation_digest": evidence.validation_digest,
        "finance_posted_actor_id": evidence.posted_actor_id,
        "reversal_actor_id": reversal_actor_id,
        "invoice_version_before": invoice_version_before,
        "invoice_version_after": invoice_version_before + 1,
        "allocated_minor": allocated_minor,
        "outstanding_minor": total - allocated_minor,
        "invoice_status": "Paid" if allocated_minor == total else "Approved",
        "audit_event_id": audit_event_id,
        "outbox_event_id": outbox_event_id,
    }


def _result_from_reversal(
    connection: Any, tenant_id: str, reversal: Mapping[str, object]
) -> dict[str, Any]:
    link_row = connection.execute(
        """SELECT * FROM reconforge.ap_payment_links
           WHERE tenant_id=%s AND id=%s FOR KEY SHARE""",
        (tenant_id, reversal["payment_link_id"]),
    ).fetchone()
    invoice_row = connection.execute(
        """SELECT id,total_minor FROM reconforge.ap_supplier_invoices
           WHERE tenant_id=%s AND id=%s FOR KEY SHARE""",
        (tenant_id, reversal["supplier_invoice_id"]),
    ).fetchone()
    if link_row is None or invoice_row is None:
        raise PlatformError("Retained payment-link reversal references missing evidence.")
    link = _row(link_row)
    invoice = _row(invoice_row)
    version_before = _stored_integer(
        reversal["invoice_version_before"], "payment-link reversal invoice version"
    )
    evidence = FinancePaymentReversalEvidence(
        payment_link_id=str(reversal["payment_link_id"]),
        reversal_finance_effect_id=str(reversal["reversal_finance_effect_id"]),
        reversal_finance_entry_id=str(reversal["reversal_finance_entry_id"]),
        workspace_id=str(reversal["workspace_id"]),
        organization_id=str(reversal["organization_id"]),
        legal_entity_id=str(reversal["legal_entity_id"]),
        currency_code=str(reversal["currency_code"]),
        amount_minor=_stored_integer(reversal["amount_minor"], "payment-link reversal amount"),
        reversal_date=str(reversal["reversal_date"]),
        validation_digest=str(reversal["finance_validation_digest"]),
        posted_actor_id=str(reversal["finance_posted_actor_id"]),
        preparer_actor_id="retained",
        validator_actor_id="retained",
    )
    return _reversal_result(
        reversal_id=str(reversal["id"]),
        link=link,
        invoice=invoice,
        evidence=evidence,
        reversal_actor_id=str(reversal["reversal_actor_id"]),
        invoice_version_before=version_before,
        allocated_minor=_active_allocation(
            connection,
            tenant_id,
            str(reversal["supplier_invoice_id"]),
            through_version=version_before,
        ),
        audit_event_id=str(reversal["audit_event_id"]),
        outbox_event_id=str(reversal["outbox_event_id"]),
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PlatformError(f"{field} must be text.")
    text = value.strip()
    if not text or len(text) > 160 or any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise PlatformError(f"{field} is invalid.")
    return text


def _stored_integer(value: object, field: str) -> int:
    """Decode persisted integer columns without accepting floats or booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise PlatformError(f"{field} must be an integer.")
    return value


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
