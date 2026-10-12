"""SQLite persistence for evidence-bound supplier-invoice settlement links.

This adapter intentionally does not create a cash payment or a journal entry.
It consumes an immutable Finance posting after that aggregate has independently
prepared, reviewed, and posted it.  A single SQLite writer transaction makes
the allocation, AP status change, audit event, outbox event, and command
receipt one recoverable business effect.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from reconforge.db.connection import DatabaseError
from reconforge.domain.models import utc_now_text
from reconforge.domain.payables_payment_link import (
    FinancePaymentEvidence,
    FinancePaymentReversalEvidence,
    PayablesPaymentLinkError,
    payment_link_request_digest,
    payment_link_reversal_request_digest,
    validate_finance_payment_effect,
    validate_finance_payment_reversal_effect,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_audit_metadata,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
)
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    audit,
    ensure_platform_schema,
    platform_id,
    require_permission,
    rows_to_dicts,
    user_for_actor,
)

_LINK_COLUMNS = (
    "id",
    "workspace_id",
    "organization_id",
    "legal_entity_id",
    "supplier_invoice_id",
    "finance_effect_id",
    "finance_entry_id",
    "ap_account_id",
    "cash_account_id",
    "amount_minor",
    "currency_code",
    "payment_date",
    "finance_validation_digest",
    "finance_posted_actor_id",
    "settlement_actor_id",
    "invoice_version_before",
    "audit_event_id",
    "outbox_event_id",
    "created_at",
)

_REVERSAL_COLUMNS = (
    "id",
    "workspace_id",
    "organization_id",
    "legal_entity_id",
    "supplier_invoice_id",
    "payment_link_id",
    "reversal_finance_effect_id",
    "reversal_finance_entry_id",
    "amount_minor",
    "currency_code",
    "reversal_date",
    "finance_validation_digest",
    "finance_posted_actor_id",
    "reversal_actor_id",
    "invoice_version_before",
    "audit_event_id",
    "outbox_event_id",
    "created_at",
)


class SQLitePayablesPaymentLinkRepository:
    """Persist exact AP/cash allocation evidence in an immediate transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        try:
            installed = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ap_payment_links'"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError("Unable to inspect the Payables settlement schema.") from exc
        if installed is None:
            raise DatabaseError("Payables settlement schema is not initialized. Run 'reconforge db migrate' first.")
        self.connection = connection

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
        """Consume one posted AP/cash effect and allocate it to one invoice.

        The method accepts partial payments.  It changes the invoice to ``Paid``
        only when immutable allocations exactly equal its stored minor-unit
        total.  Retrying the same command returns the retained response; any
        payload or actor change under the same key is rejected.
        """

        actor = require_permission(self.connection, actor_label=actor_label, permission="payables.settle")
        actor_id = actor.id if actor is not None else _required_text(actor_label, "settlement actor")
        audit_actor = actor.username if actor is not None else _required_text(actor_label, "settlement actor")
        normalized_invoice = _required_text(invoice_id, "supplier invoice id")
        normalized_effect = _required_text(finance_effect_id, "finance effect id")
        normalized_ap_account = _required_text(ap_account_id, "accounts payable account id")
        normalized_cash_account = _required_text(cash_account_id, "cash account id")
        normalized_command = _command_id(command_id)
        try:
            digest = payment_link_request_digest(
                invoice_id=normalized_invoice,
                finance_effect_id=normalized_effect,
                ap_account_id=normalized_ap_account,
                cash_account_id=normalized_cash_account,
                expected_invoice_version=expected_invoice_version,
                settlement_actor_id=actor_id,
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            invoice_row = self.connection.execute(
                "SELECT * FROM ap_supplier_invoices WHERE id=?", (normalized_invoice,)
            ).fetchone()
            if invoice_row is None:
                raise PlatformError("Supplier invoice not found.")
            invoice = dict(invoice_row)
            workspace_id = _required_text(invoice.get("workspace_id"), "invoice workspace id")
            replay = self._replay_if_present(
                workspace_id=workspace_id,
                command_id=normalized_command,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                self.connection.commit()
                return replay
            if _stored_integer(invoice["row_version"], "supplier invoice row version") != expected_invoice_version:
                raise PlatformError("Supplier invoice changed concurrently; reload before linking payment evidence.")
            effect_row = self.connection.execute(
                """SELECT effect.*,entry.validator_actor_id
                   FROM finance_posting_effects effect
                   JOIN ledger_entries entry ON entry.id=effect.entry_id
                   WHERE effect.id=?""",
                (normalized_effect,),
            ).fetchone()
            if effect_row is None:
                raise PlatformError("Financial posting effect not found.")
            effect = dict(effect_row)
            evidence = self._validate(
                invoice=invoice,
                effect=effect,
                ap_account_id=normalized_ap_account,
                cash_account_id=normalized_cash_account,
                settlement_actor_id=actor_id,
            )
            existing = self.connection.execute(
                "SELECT id FROM ap_payment_links WHERE finance_effect_id=?", (evidence.finance_effect_id,)
            ).fetchone()
            if existing is not None:
                raise PlatformError("Financial posting effect is already allocated to a supplier invoice.")
            allocated_after = _active_allocation(self.connection, normalized_invoice) + evidence.amount_minor
            invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
            if allocated_after > invoice_total:
                raise PlatformError("Payment allocation exceeds the supplier invoice total.")
            link_id = platform_id("APPAY", workspace_id, normalized_invoice, evidence.finance_effect_id)
            audit_event = audit(
                self.connection,
                actor_label=audit_actor,
                object_type="ap_payment_link",
                object_id=link_id,
                action="ap_payment_linked",
                metadata={
                    "supplier_invoice_id": normalized_invoice,
                    "finance_effect_id": evidence.finance_effect_id,
                    "finance_entry_id": evidence.finance_entry_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                    "invoice_version_before": expected_invoice_version,
                },
            )
            outbox_event_id = platform_id("OBX", "ap.payment_linked", link_id)
            append_outbox_event(
                self.connection,
                event_id=outbox_event_id,
                event_type="ap.payment_linked",
                aggregate_type="ap_payment_link",
                aggregate_id=link_id,
                payload={
                    "audit_event_id": audit_event.id,
                    "payment_link_id": link_id,
                    "supplier_invoice_id": normalized_invoice,
                    "finance_effect_id": evidence.finance_effect_id,
                    "finance_entry_id": evidence.finance_entry_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                },
            )
            self.connection.execute(
                """INSERT INTO ap_payment_links (
                    id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,
                    finance_effect_id,finance_entry_id,ap_account_id,cash_account_id,
                    amount_minor,currency_code,payment_date,finance_validation_digest,
                    finance_posted_actor_id,settlement_actor_id,invoice_version_before,
                    audit_event_id,outbox_event_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    link_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    normalized_invoice,
                    evidence.finance_effect_id,
                    evidence.finance_entry_id,
                    normalized_ap_account,
                    normalized_cash_account,
                    evidence.amount_minor,
                    evidence.currency_code,
                    evidence.payment_date,
                    evidence.validation_digest,
                    evidence.posted_actor_id,
                    actor_id,
                    expected_invoice_version,
                    audit_event.id,
                    outbox_event_id,
                    utc_now_text(),
                ),
            )
            updated = self.connection.execute(
                "SELECT status,row_version FROM ap_supplier_invoices WHERE id=?",
                (normalized_invoice,),
            ).fetchone()
            expected_status = "Paid" if allocated_after == invoice_total else "Approved"
            if (
                updated is None
                or str(updated["status"]) != expected_status
                or _stored_integer(updated["row_version"], "supplier invoice row version")
                != expected_invoice_version + 1
            ):
                raise PlatformError("Supplier invoice payment state was not advanced by retained payment evidence.")
            result = self._result(
                link_id=link_id,
                invoice=invoice,
                evidence=evidence,
                ap_account_id=normalized_ap_account,
                cash_account_id=normalized_cash_account,
                settlement_actor_id=actor_id,
                invoice_version_before=expected_invoice_version,
                invoice_version_after=expected_invoice_version + 1,
                allocated_minor=allocated_after,
                audit_event_id=audit_event.id,
                outbox_event_id=outbox_event_id,
            )
            try:
                receipt = encode_financial_idempotency_response(result)
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link idempotency receipt is invalid.") from exc
            self.connection.execute(
                """INSERT INTO ap_payment_link_commands
                   (workspace_id,command_id,settlement_actor_id,request_digest,result_json,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (workspace_id, normalized_command, actor_id, digest, receipt.text, utc_now_text()),
            )
            self.connection.commit()
            return result
        except (PayablesPaymentLinkError, PlatformError):
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Supplier payment evidence conflicts with retained financial state.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to link supplier payment evidence.") from exc
        except Exception:
            self.connection.rollback()
            raise

    def list_payment_links(self, invoice_id: str, *, actor_label: str = "local-cli") -> list[dict[str, Any]]:
        """Return the immutable payment-evidence links for one supplier invoice."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.read")
        normalized_invoice = _required_text(invoice_id, "supplier invoice id")
        rows = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,
                      finance_effect_id,finance_entry_id,ap_account_id,cash_account_id,amount_minor,
                      currency_code,payment_date,finance_validation_digest,finance_posted_actor_id,
                      settlement_actor_id,invoice_version_before,audit_event_id,outbox_event_id,created_at
               FROM ap_payment_links WHERE supplier_invoice_id=? ORDER BY invoice_version_before,id""",
            (normalized_invoice,),
        ).fetchall()
        return rows_to_dicts(rows)

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
        """Unwind one allocation only after an independently posted full inverse.

        The original allocation, original Finance posting, audit event, and
        outbox event stay immutable.  This creates a separate evidence node
        that points at the one full Finance reversal accepted by the Finance
        posting aggregate.
        """

        actor = require_permission(self.connection, actor_label=actor_label, permission="payables.reverse")
        actor_id = actor.id if actor is not None else _required_text(actor_label, "reversal actor")
        audit_actor = actor.username if actor is not None else _required_text(actor_label, "reversal actor")
        normalized_invoice = _required_text(invoice_id, "supplier invoice id")
        normalized_link = _required_text(payment_link_id, "payment link id")
        normalized_effect = _required_text(reversal_finance_effect_id, "reversal finance effect id")
        normalized_command = _command_id(command_id)
        try:
            digest = payment_link_reversal_request_digest(
                invoice_id=normalized_invoice,
                payment_link_id=normalized_link,
                reversal_finance_effect_id=normalized_effect,
                expected_invoice_version=expected_invoice_version,
                reversal_actor_id=actor_id,
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            invoice_row = self.connection.execute(
                "SELECT * FROM ap_supplier_invoices WHERE id=?", (normalized_invoice,)
            ).fetchone()
            if invoice_row is None:
                raise PlatformError("Supplier invoice not found.")
            invoice = dict(invoice_row)
            workspace_id = _required_text(invoice.get("workspace_id"), "invoice workspace id")
            replay = self._replay_reversal_if_present(
                workspace_id=workspace_id,
                command_id=normalized_command,
                actor_id=actor_id,
                request_digest=digest,
            )
            if replay is not None:
                self.connection.commit()
                return replay
            if _stored_integer(invoice["row_version"], "supplier invoice row version") != expected_invoice_version:
                raise PlatformError("Supplier invoice changed concurrently; reload before reversing payment evidence.")
            link_row = self.connection.execute(
                "SELECT * FROM ap_payment_links WHERE id=? AND supplier_invoice_id=?",
                (normalized_link, normalized_invoice),
            ).fetchone()
            if link_row is None:
                raise PlatformError("Supplier payment link not found for this invoice.")
            link = dict(link_row)
            effect_row = self.connection.execute(
                """SELECT effect.*,entry.validator_actor_id
                   FROM finance_posting_effects effect
                   JOIN ledger_entries entry ON entry.id=effect.entry_id
                   WHERE effect.id=?""",
                (normalized_effect,),
            ).fetchone()
            if effect_row is None:
                raise PlatformError("Finance reversal effect not found.")
            evidence = self._validate_reversal(
                invoice=invoice,
                link=link,
                effect=dict(effect_row),
                reversal_actor_id=actor_id,
            )
            existing = self.connection.execute(
                """SELECT id FROM ap_payment_link_reversals
                   WHERE payment_link_id=? OR reversal_finance_effect_id=?""",
                (normalized_link, evidence.reversal_finance_effect_id),
            ).fetchone()
            if existing is not None:
                raise PlatformError("Supplier payment link or Finance reversal effect is already reversed.")
            allocated_before = _active_allocation(self.connection, normalized_invoice)
            allocated_after = allocated_before - evidence.amount_minor
            if allocated_after < 0:
                raise PlatformError("Retained supplier payment allocation cannot become negative.")
            reversal_id = platform_id(
                "APPAYREV", workspace_id, normalized_link, evidence.reversal_finance_effect_id
            )
            audit_event = audit(
                self.connection,
                actor_label=audit_actor,
                object_type="ap_payment_link_reversal",
                object_id=reversal_id,
                action="ap_payment_link_reversed",
                metadata={
                    "payment_link_id": normalized_link,
                    "supplier_invoice_id": normalized_invoice,
                    "original_finance_effect_id": str(link["finance_effect_id"]),
                    "reversal_finance_effect_id": evidence.reversal_finance_effect_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                    "invoice_version_before": expected_invoice_version,
                },
            )
            outbox_event_id = platform_id("OBX", "ap.payment_link_reversed", reversal_id)
            append_outbox_event(
                self.connection,
                event_id=outbox_event_id,
                event_type="ap.payment_link_reversed",
                aggregate_type="ap_payment_link_reversal",
                aggregate_id=reversal_id,
                payload={
                    "audit_event_id": audit_event.id,
                    "payment_link_reversal_id": reversal_id,
                    "payment_link_id": normalized_link,
                    "supplier_invoice_id": normalized_invoice,
                    "reversal_finance_effect_id": evidence.reversal_finance_effect_id,
                    "reversal_finance_entry_id": evidence.reversal_finance_entry_id,
                    "amount_minor": evidence.amount_minor,
                    "currency_code": evidence.currency_code,
                },
            )
            self.connection.execute(
                """INSERT INTO ap_payment_link_reversals (
                    id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,payment_link_id,
                    reversal_finance_effect_id,reversal_finance_entry_id,amount_minor,currency_code,
                    reversal_date,finance_validation_digest,finance_posted_actor_id,reversal_actor_id,
                    invoice_version_before,audit_event_id,outbox_event_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    reversal_id,
                    evidence.workspace_id,
                    evidence.organization_id,
                    evidence.legal_entity_id,
                    normalized_invoice,
                    normalized_link,
                    evidence.reversal_finance_effect_id,
                    evidence.reversal_finance_entry_id,
                    evidence.amount_minor,
                    evidence.currency_code,
                    evidence.reversal_date,
                    evidence.validation_digest,
                    evidence.posted_actor_id,
                    actor_id,
                    expected_invoice_version,
                    audit_event.id,
                    outbox_event_id,
                    utc_now_text(),
                ),
            )
            updated = self.connection.execute(
                "SELECT status,row_version FROM ap_supplier_invoices WHERE id=?", (normalized_invoice,)
            ).fetchone()
            invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
            expected_status = "Paid" if allocated_after == invoice_total else "Approved"
            if (
                updated is None
                or str(updated["status"]) != expected_status
                or _stored_integer(updated["row_version"], "supplier invoice row version")
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
                audit_event_id=audit_event.id,
                outbox_event_id=outbox_event_id,
            )
            try:
                receipt = encode_financial_idempotency_response(result)
            except PersistedJsonError as exc:
                raise PlatformError("Payment-link reversal idempotency receipt is invalid.") from exc
            self.connection.execute(
                """INSERT INTO ap_payment_link_reversal_commands
                   (workspace_id,command_id,reversal_actor_id,request_digest,result_json,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (workspace_id, normalized_command, actor_id, digest, receipt.text, utc_now_text()),
            )
            self.connection.commit()
            return result
        except (PayablesPaymentLinkError, PlatformError):
            self.connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise PlatformError("Supplier payment-link reversal conflicts with retained financial state.") from exc
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to reverse supplier payment-link evidence.") from exc
        except Exception:
            self.connection.rollback()
            raise

    def list_payment_link_reversals(
        self, invoice_id: str, *, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        """Return immutable allocation-reversal evidence for one invoice."""

        require_permission(self.connection, actor_label=actor_label, permission="payables.read")
        normalized_invoice = _required_text(invoice_id, "supplier invoice id")
        rows = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_invoice_id,payment_link_id,
                      reversal_finance_effect_id,reversal_finance_entry_id,amount_minor,currency_code,
                      reversal_date,finance_validation_digest,finance_posted_actor_id,reversal_actor_id,
                      invoice_version_before,audit_event_id,outbox_event_id,created_at
               FROM ap_payment_link_reversals
               WHERE supplier_invoice_id=? ORDER BY invoice_version_before,id""",
            (normalized_invoice,),
        ).fetchall()
        return rows_to_dicts(rows)

    def _replay_if_present(
        self,
        *,
        workspace_id: str,
        command_id: str,
        actor_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT settlement_actor_id,request_digest,result_json
               FROM ap_payment_link_commands WHERE workspace_id=? AND command_id=?""",
            (workspace_id, command_id),
        ).fetchone()
        if row is None:
            return None
        if str(row["settlement_actor_id"]) != actor_id or str(row["request_digest"]) != request_digest:
            raise PlatformError("Payment-link idempotency key was already used with a different request or actor.")
        try:
            result = decode_financial_idempotency_response(row["result_json"]).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored payment-link idempotency receipt is invalid.") from exc
        self._validate_replay(result, workspace_id=workspace_id, actor_id=actor_id)
        return result

    def _validate(self, *, invoice: Mapping[str, object], effect: Mapping[str, object], ap_account_id: str,
                  cash_account_id: str, settlement_actor_id: str) -> FinancePaymentEvidence:
        try:
            return validate_finance_payment_effect(
                invoice=invoice,
                effect=effect,
                ap_account_id=ap_account_id,
                cash_account_id=cash_account_id,
                settlement_actor_id=settlement_actor_id,
                invoice_creator_actor_id=_canonical_actor_id(self.connection, invoice.get("created_by")),
                invoice_approver_actor_id=_canonical_actor_id(self.connection, invoice.get("approved_by")),
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
        try:
            return validate_finance_payment_reversal_effect(
                invoice=invoice,
                payment_link=link,
                effect=effect,
                reversal_actor_id=reversal_actor_id,
                invoice_creator_actor_id=_canonical_actor_id(self.connection, invoice.get("created_by")),
                invoice_approver_actor_id=_canonical_actor_id(self.connection, invoice.get("approved_by")),
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError(str(exc)) from exc

    def _validate_replay(self, result: Mapping[str, object], *, workspace_id: str, actor_id: str) -> None:
        link_id = result.get("payment_link_id")
        if not isinstance(link_id, str) or not link_id:
            raise PlatformError("Stored payment-link idempotency receipt is invalid.")
        link = self.connection.execute(
            "SELECT * FROM ap_payment_links WHERE id=? AND workspace_id=?", (link_id, workspace_id)
        ).fetchone()
        if link is None or str(link["settlement_actor_id"]) != actor_id:
            raise PlatformError("Stored payment-link idempotency receipt does not match retained evidence.")
        expected = _result_from_link(self.connection, dict(link))
        if dict(result) != expected:
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
            """SELECT reversal_actor_id,request_digest,result_json
               FROM ap_payment_link_reversal_commands WHERE workspace_id=? AND command_id=?""",
            (workspace_id, command_id),
        ).fetchone()
        if row is None:
            return None
        if str(row["reversal_actor_id"]) != actor_id or str(row["request_digest"]) != request_digest:
            raise PlatformError("Payment-link reversal idempotency key was already used with a different request or actor.")
        try:
            result = decode_financial_idempotency_response(row["result_json"]).payload
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
        reversal = self.connection.execute(
            "SELECT * FROM ap_payment_link_reversals WHERE id=? AND workspace_id=?",
            (reversal_id, workspace_id),
        ).fetchone()
        if reversal is None or str(reversal["reversal_actor_id"]) != actor_id:
            raise PlatformError("Stored payment-link reversal receipt does not match retained evidence.")
        expected = _result_from_reversal(self.connection, dict(reversal))
        if dict(result) != expected:
            raise PlatformError("Stored payment-link reversal receipt does not match retained evidence.")

    @staticmethod
    def _result(
        *,
        link_id: str,
        invoice: Mapping[str, object],
        evidence: FinancePaymentEvidence,
        ap_account_id: str,
        cash_account_id: str,
        settlement_actor_id: str,
        invoice_version_before: int,
        invoice_version_after: int,
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
            "invoice_version_after": invoice_version_after,
            "allocated_minor": allocated_minor,
            "outstanding_minor": invoice_total - allocated_minor,
            "invoice_status": "Paid" if allocated_minor == invoice_total else "Approved",
            "audit_event_id": audit_event_id,
            "outbox_event_id": outbox_event_id,
        }


def _result_from_link(connection: sqlite3.Connection, link: Mapping[str, object]) -> dict[str, Any]:
    invoice = connection.execute(
        "SELECT id,total_minor,status,row_version FROM ap_supplier_invoices WHERE id=?", (link["supplier_invoice_id"],)
    ).fetchone()
    if invoice is None:
        raise PlatformError("Retained payment link references a missing supplier invoice.")
    # The receipt records the allocation state at this command, rather than a
    # later invoice balance after additional valid partial payments.  The
    # immutable optimistic version makes that historical state reconstructible.
    allocated = connection.execute(
        """SELECT COALESCE(SUM(history.amount_minor),0) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=? AND history.invoice_version_before<=?
             AND NOT EXISTS(
                SELECT 1 FROM ap_payment_link_reversals reversal
                WHERE reversal.payment_link_id=history.id
                  AND reversal.invoice_version_before<=?
             )""",
        (
            link["supplier_invoice_id"],
            link["invoice_version_before"],
            link["invoice_version_before"],
        ),
    ).fetchone()[0]
    total = _stored_integer(invoice["total_minor"], "supplier invoice total")
    allocated_minor = _stored_integer(allocated, "retained payment-link allocated amount")
    if allocated_minor > total or str(invoice["status"]) not in {"Approved", "Paid"}:
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
        "allocated_minor": allocated_minor,
        "outstanding_minor": total - allocated_minor,
        "invoice_status": "Paid" if allocated_minor == total else "Approved",
        "audit_event_id": str(link["audit_event_id"]),
        "outbox_event_id": str(link["outbox_event_id"]),
    }


def _active_allocation(
    connection: sqlite3.Connection,
    invoice_id: str,
    *,
    through_version: int | None = None,
) -> int:
    """Return active allocation at a deterministic invoice-history version."""

    if through_version is None:
        row = connection.execute(
            """SELECT COALESCE(SUM(link.amount_minor),0) AS amount
               FROM ap_payment_links link
               WHERE link.supplier_invoice_id=?
                 AND NOT EXISTS(
                    SELECT 1 FROM ap_payment_link_reversals reversal
                    WHERE reversal.payment_link_id=link.id
                 )""",
            (invoice_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """SELECT COALESCE(SUM(link.amount_minor),0) AS amount
               FROM ap_payment_links link
               WHERE link.supplier_invoice_id=? AND link.invoice_version_before<=?
                 AND NOT EXISTS(
                    SELECT 1 FROM ap_payment_link_reversals reversal
                    WHERE reversal.payment_link_id=link.id
                      AND reversal.invoice_version_before<=?
                 )""",
            (invoice_id, through_version, through_version),
        ).fetchone()
    return _stored_integer(row["amount"], "retained payment-link allocated amount")


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
    invoice_total = _stored_integer(invoice["total_minor"], "supplier invoice total")
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
        "outstanding_minor": invoice_total - allocated_minor,
        "invoice_status": "Paid" if allocated_minor == invoice_total else "Approved",
        "audit_event_id": audit_event_id,
        "outbox_event_id": outbox_event_id,
    }


def _result_from_reversal(
    connection: sqlite3.Connection, reversal: Mapping[str, object]
) -> dict[str, Any]:
    link = connection.execute(
        "SELECT * FROM ap_payment_links WHERE id=?", (reversal["payment_link_id"],)
    ).fetchone()
    invoice = connection.execute(
        "SELECT id,total_minor,status FROM ap_supplier_invoices WHERE id=?",
        (reversal["supplier_invoice_id"],),
    ).fetchone()
    if link is None or invoice is None:
        raise PlatformError("Retained payment-link reversal references missing evidence.")
    version_before = _stored_integer(
        reversal["invoice_version_before"], "payment-link reversal invoice version"
    )
    allocated_minor = _active_allocation(
        connection, str(reversal["supplier_invoice_id"]), through_version=version_before
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
        link=dict(link),
        invoice=dict(invoice),
        evidence=evidence,
        reversal_actor_id=str(reversal["reversal_actor_id"]),
        invoice_version_before=version_before,
        allocated_minor=allocated_minor,
        audit_event_id=str(reversal["audit_event_id"]),
        outbox_event_id=str(reversal["outbox_event_id"]),
    )


def verify_sqlite_payment_link_storage(connection: sqlite3.Connection) -> None:
    """Replay immutable AP settlement evidence before backup or after restore."""

    tables = ("ap_payment_links", "ap_payment_link_commands")
    present = [
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
        for table in tables
    ]
    if not any(present):
        return
    if not all(present):
        raise PlatformError("Payables payment-link schema is incomplete.")
    reversal_tables = ("ap_payment_link_reversals", "ap_payment_link_reversal_commands")
    reversal_present = [
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
        for table in reversal_tables
    ]
    if any(reversal_present) and not all(reversal_present):
        raise PlatformError("Payables payment-link reversal schema is incomplete.")
    reversal_enabled = all(reversal_present)
    links = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM ap_payment_links ORDER BY supplier_invoice_id,invoice_version_before,id"
        ).fetchall()
    ]
    links_by_id = {str(link["id"]): link for link in links}
    if len(links_by_id) != len(links):
        raise PlatformError("Retained payment-link identifiers are not unique.")
    reversals: list[dict[str, Any]] = []
    if reversal_enabled:
        reversals = [
            dict(row)
            for row in connection.execute(
                """SELECT * FROM ap_payment_link_reversals
                   ORDER BY supplier_invoice_id,invoice_version_before,id"""
            ).fetchall()
        ]
    reversals_by_id = {str(reversal["id"]): reversal for reversal in reversals}
    if len(reversals_by_id) != len(reversals):
        raise PlatformError("Retained payment-link reversal identifiers are not unique.")
    by_invoice: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for link in links:
        by_invoice.setdefault(str(link["supplier_invoice_id"]), []).append(("link", link))
    for reversal in reversals:
        by_invoice.setdefault(str(reversal["supplier_invoice_id"]), []).append(("reversal", reversal))
    for invoice_id, invoice_events in by_invoice.items():
        invoice_row = connection.execute(
            "SELECT * FROM ap_supplier_invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        if invoice_row is None:
            raise PlatformError("Retained payment link references a missing supplier invoice.")
        invoice = dict(invoice_row)
        invoice_events.sort(
            key=lambda event: (
                _stored_integer(event[1]["invoice_version_before"], "payment-link invoice version"),
                event[0],
                str(event[1]["id"]),
            )
        )
        expected_version = _stored_integer(
            invoice_events[0][1]["invoice_version_before"], "payment-link invoice version"
        )
        allocated = 0
        active_links: dict[str, int] = {}
        for event_type, event in invoice_events:
            if _stored_integer(event["invoice_version_before"], "payment-link invoice version") != expected_version:
                raise PlatformError("Retained payment evidence does not form a contiguous invoice version history.")
            if event_type == "link":
                effect_row = connection.execute(
                    """SELECT effect.*,entry.validator_actor_id
                       FROM finance_posting_effects effect
                       JOIN ledger_entries entry ON entry.id=effect.entry_id
                       WHERE effect.id=?""",
                    (event["finance_effect_id"],),
                ).fetchone()
                if effect_row is None:
                    raise PlatformError("Retained payment link references a missing financial effect.")
                try:
                    payment_evidence = validate_finance_payment_effect(
                        invoice={**invoice, "status": "Approved"},
                        effect=dict(effect_row),
                        ap_account_id=event["ap_account_id"],
                        cash_account_id=event["cash_account_id"],
                        settlement_actor_id=event["settlement_actor_id"],
                        invoice_creator_actor_id=_canonical_actor_id(connection, invoice.get("created_by")),
                        invoice_approver_actor_id=_canonical_actor_id(connection, invoice.get("approved_by")),
                    )
                except PayablesPaymentLinkError as exc:
                    raise PlatformError("Retained payment link violates its financial admission contract.") from exc
                expected_fields = {
                    "workspace_id": payment_evidence.workspace_id,
                    "organization_id": payment_evidence.organization_id,
                    "legal_entity_id": payment_evidence.legal_entity_id,
                    "finance_effect_id": payment_evidence.finance_effect_id,
                    "finance_entry_id": payment_evidence.finance_entry_id,
                    "amount_minor": payment_evidence.amount_minor,
                    "currency_code": payment_evidence.currency_code,
                    "payment_date": payment_evidence.payment_date,
                    "finance_validation_digest": payment_evidence.validation_digest,
                    "finance_posted_actor_id": payment_evidence.posted_actor_id,
                }
                if any(event[key] != value for key, value in expected_fields.items()):
                    raise PlatformError("Retained payment link differs from its immutable financial effect.")
                _verify_link_evidence(connection, link=event, invoice=invoice)
                amount = _stored_integer(event["amount_minor"], "payment-link amount")
                active_links[str(event["id"])] = amount
                allocated += amount
            else:
                retained_link = links_by_id.get(str(event["payment_link_id"]))
                if retained_link is None or str(retained_link["id"]) not in active_links:
                    raise PlatformError("Retained payment-link reversal does not identify an active allocation.")
                effect_row = connection.execute(
                    """SELECT effect.*,entry.validator_actor_id
                       FROM finance_posting_effects effect
                       JOIN ledger_entries entry ON entry.id=effect.entry_id
                       WHERE effect.id=?""",
                    (event["reversal_finance_effect_id"],),
                ).fetchone()
                if effect_row is None:
                    raise PlatformError("Retained payment-link reversal references a missing Finance effect.")
                try:
                    reversal_evidence = validate_finance_payment_reversal_effect(
                        invoice={
                            **invoice,
                            "status": "Paid" if allocated == _stored_integer(invoice["total_minor"], "supplier invoice total") else "Approved",
                        },
                        payment_link=retained_link,
                        effect=dict(effect_row),
                        reversal_actor_id=event["reversal_actor_id"],
                        invoice_creator_actor_id=_canonical_actor_id(connection, invoice.get("created_by")),
                        invoice_approver_actor_id=_canonical_actor_id(connection, invoice.get("approved_by")),
                    )
                except PayablesPaymentLinkError as exc:
                    raise PlatformError("Retained payment-link reversal violates its financial admission contract.") from exc
                expected_fields = {
                    "workspace_id": reversal_evidence.workspace_id,
                    "organization_id": reversal_evidence.organization_id,
                    "legal_entity_id": reversal_evidence.legal_entity_id,
                    "reversal_finance_effect_id": reversal_evidence.reversal_finance_effect_id,
                    "reversal_finance_entry_id": reversal_evidence.reversal_finance_entry_id,
                    "amount_minor": reversal_evidence.amount_minor,
                    "currency_code": reversal_evidence.currency_code,
                    "reversal_date": reversal_evidence.reversal_date,
                    "finance_validation_digest": reversal_evidence.validation_digest,
                    "finance_posted_actor_id": reversal_evidence.posted_actor_id,
                }
                if any(event[key] != value for key, value in expected_fields.items()):
                    raise PlatformError("Retained payment-link reversal differs from its Finance effect.")
                _verify_reversal_evidence(
                    connection, reversal=event, link=retained_link, invoice=invoice
                )
                allocated -= active_links.pop(str(retained_link["id"]))
            expected_version += 1
        total = _stored_integer(invoice["total_minor"], "supplier invoice total")
        expected_status = "Paid" if allocated == total else "Approved"
        if (
            allocated > total
            or str(invoice["status"]) != expected_status
            or _stored_integer(invoice["row_version"], "supplier invoice row version") != expected_version
        ):
            raise PlatformError("Supplier invoice state differs from its retained payment-link history.")
    command_links: set[str] = set()
    for command_row in connection.execute(
        "SELECT * FROM ap_payment_link_commands ORDER BY workspace_id,command_id"
    ).fetchall():
        command = dict(command_row)
        try:
            result = decode_financial_idempotency_response(command["result_json"]).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored payment-link idempotency receipt is invalid.") from exc
        link_id = result.get("payment_link_id")
        if not isinstance(link_id, str) or link_id in command_links or link_id not in links_by_id:
            raise PlatformError("Stored payment-link command does not identify one retained link.")
        link = links_by_id[link_id]
        expected = _result_from_link(connection, link)
        try:
            digest = payment_link_request_digest(
                invoice_id=link["supplier_invoice_id"],
                finance_effect_id=link["finance_effect_id"],
                ap_account_id=link["ap_account_id"],
                cash_account_id=link["cash_account_id"],
                expected_invoice_version=link["invoice_version_before"],
                settlement_actor_id=link["settlement_actor_id"],
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError("Retained payment-link command request is invalid.") from exc
        if (
            result != expected
            or str(command["workspace_id"]) != str(link["workspace_id"])
            or str(command["settlement_actor_id"]) != str(link["settlement_actor_id"])
            or str(command["request_digest"]) != digest
        ):
            raise PlatformError("Stored payment-link command differs from retained settlement evidence.")
        command_links.add(link_id)
    if command_links != set(links_by_id):
        raise PlatformError("Retained payment-link evidence is missing its idempotency command.")
    if not reversal_enabled:
        return
    command_reversals: set[str] = set()
    for command_row in connection.execute(
        "SELECT * FROM ap_payment_link_reversal_commands ORDER BY workspace_id,command_id"
    ).fetchall():
        command = dict(command_row)
        try:
            result = decode_financial_idempotency_response(command["result_json"]).payload
        except PersistedJsonError as exc:
            raise PlatformError("Stored payment-link reversal idempotency receipt is invalid.") from exc
        reversal_id = result.get("payment_link_reversal_id")
        if (
            not isinstance(reversal_id, str)
            or reversal_id in command_reversals
            or reversal_id not in reversals_by_id
        ):
            raise PlatformError("Stored payment-link reversal command does not identify one retained reversal.")
        reversal = reversals_by_id[reversal_id]
        expected = _result_from_reversal(connection, reversal)
        try:
            digest = payment_link_reversal_request_digest(
                invoice_id=reversal["supplier_invoice_id"],
                payment_link_id=reversal["payment_link_id"],
                reversal_finance_effect_id=reversal["reversal_finance_effect_id"],
                expected_invoice_version=reversal["invoice_version_before"],
                reversal_actor_id=reversal["reversal_actor_id"],
            )
        except PayablesPaymentLinkError as exc:
            raise PlatformError("Retained payment-link reversal command request is invalid.") from exc
        if (
            result != expected
            or str(command["workspace_id"]) != str(reversal["workspace_id"])
            or str(command["reversal_actor_id"]) != str(reversal["reversal_actor_id"])
            or str(command["request_digest"]) != digest
        ):
            raise PlatformError("Stored payment-link reversal command differs from retained evidence.")
        command_reversals.add(reversal_id)
    if command_reversals != set(reversals_by_id):
        raise PlatformError("Retained payment-link reversal evidence is missing its idempotency command.")


def _verify_link_evidence(
    connection: sqlite3.Connection,
    *,
    link: Mapping[str, object],
    invoice: Mapping[str, object],
) -> None:
    audit_row = connection.execute(
        "SELECT actor_user_id,actor_label,object_type,object_id,action,metadata_json FROM audit_events WHERE id=?",
        (link["audit_event_id"],),
    ).fetchone()
    outbox_row = connection.execute(
        "SELECT event_type,aggregate_type,aggregate_id,payload_json FROM outbox_events WHERE id=?",
        (link["outbox_event_id"],),
    ).fetchone()
    if audit_row is None or outbox_row is None:
        raise PlatformError("Retained payment-link audit or outbox evidence is missing.")
    try:
        metadata = decode_audit_metadata(audit_row["metadata_json"]).payload
        payload = decode_financial_idempotency_response(outbox_row["payload_json"]).payload
    except PersistedJsonError as exc:
        raise PlatformError("Retained payment-link audit or outbox evidence is malformed.") from exc
    amount_minor = _stored_integer(link["amount_minor"], "payment-link amount")
    version_before = _stored_integer(link["invoice_version_before"], "payment-link invoice version")
    expected_metadata = {
        "supplier_invoice_id": str(invoice["id"]),
        "finance_effect_id": str(link["finance_effect_id"]),
        "finance_entry_id": str(link["finance_entry_id"]),
        "amount_minor": amount_minor,
        "currency_code": str(link["currency_code"]),
        "invoice_version_before": version_before,
    }
    expected_payload = {
        "audit_event_id": str(link["audit_event_id"]),
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(invoice["id"]),
        "finance_effect_id": str(link["finance_effect_id"]),
        "finance_entry_id": str(link["finance_entry_id"]),
        "amount_minor": amount_minor,
        "currency_code": str(link["currency_code"]),
    }
    if (
        str(audit_row["object_type"]) != "ap_payment_link"
        or str(audit_row["object_id"]) != str(link["id"])
        or str(audit_row["action"]) != "ap_payment_linked"
        or (
            audit_row["actor_user_id"] != link["settlement_actor_id"]
            and str(audit_row["actor_label"]) != str(link["settlement_actor_id"])
        )
        or metadata != expected_metadata
        or str(outbox_row["event_type"]) != "ap.payment_linked"
        or str(outbox_row["aggregate_type"]) != "ap_payment_link"
        or str(outbox_row["aggregate_id"]) != str(link["id"])
        or payload != expected_payload
    ):
        raise PlatformError("Retained payment-link audit or outbox evidence differs from its settlement link.")


def _verify_reversal_evidence(
    connection: sqlite3.Connection,
    *,
    reversal: Mapping[str, object],
    link: Mapping[str, object],
    invoice: Mapping[str, object],
) -> None:
    audit_row = connection.execute(
        "SELECT actor_user_id,actor_label,object_type,object_id,action,metadata_json FROM audit_events WHERE id=?",
        (reversal["audit_event_id"],),
    ).fetchone()
    outbox_row = connection.execute(
        "SELECT event_type,aggregate_type,aggregate_id,payload_json FROM outbox_events WHERE id=?",
        (reversal["outbox_event_id"],),
    ).fetchone()
    if audit_row is None or outbox_row is None:
        raise PlatformError("Retained payment-link reversal audit or outbox evidence is missing.")
    try:
        metadata = decode_audit_metadata(audit_row["metadata_json"]).payload
        payload = decode_financial_idempotency_response(outbox_row["payload_json"]).payload
    except PersistedJsonError as exc:
        raise PlatformError("Retained payment-link reversal audit or outbox evidence is malformed.") from exc
    amount_minor = _stored_integer(reversal["amount_minor"], "payment-link reversal amount")
    version_before = _stored_integer(
        reversal["invoice_version_before"], "payment-link reversal invoice version"
    )
    expected_metadata = {
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(invoice["id"]),
        "original_finance_effect_id": str(link["finance_effect_id"]),
        "reversal_finance_effect_id": str(reversal["reversal_finance_effect_id"]),
        "amount_minor": amount_minor,
        "currency_code": str(reversal["currency_code"]),
        "invoice_version_before": version_before,
    }
    expected_payload = {
        "audit_event_id": str(reversal["audit_event_id"]),
        "payment_link_reversal_id": str(reversal["id"]),
        "payment_link_id": str(link["id"]),
        "supplier_invoice_id": str(invoice["id"]),
        "reversal_finance_effect_id": str(reversal["reversal_finance_effect_id"]),
        "reversal_finance_entry_id": str(reversal["reversal_finance_entry_id"]),
        "amount_minor": amount_minor,
        "currency_code": str(reversal["currency_code"]),
    }
    if (
        str(audit_row["object_type"]) != "ap_payment_link_reversal"
        or str(audit_row["object_id"]) != str(reversal["id"])
        or str(audit_row["action"]) != "ap_payment_link_reversed"
        or (
            audit_row["actor_user_id"] != reversal["reversal_actor_id"]
            and str(audit_row["actor_label"]) != str(reversal["reversal_actor_id"])
        )
        or metadata != expected_metadata
        or str(outbox_row["event_type"]) != "ap.payment_link_reversed"
        or str(outbox_row["aggregate_type"]) != "ap_payment_link_reversal"
        or str(outbox_row["aggregate_id"]) != str(reversal["id"])
        or payload != expected_payload
    ):
        raise PlatformError("Retained payment-link reversal audit or outbox evidence differs from its reversal.")


def _canonical_actor_id(connection: sqlite3.Connection, actor_value: object) -> str:
    actor_label = _required_text(actor_value, "retained actor")
    user = user_for_actor(connection, actor_label)
    return user.id if user is not None else actor_label


def _stored_integer(value: object, field: str) -> int:
    """Decode persisted integer columns without accepting floats or booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise PlatformError(f"{field.capitalize()} must be an integer.")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PlatformError(f"{field.capitalize()} must be text.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 160
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise PlatformError(f"{field.capitalize()} is required.")
    return normalized


def _command_id(value: object) -> str:
    normalized = _required_text(value, "command id")
    if len(normalized) > 160:
        raise PlatformError("Command id must not exceed 160 characters.")
    return normalized


__all__ = [
    "SQLitePayablesPaymentLinkRepository",
    "_LINK_COLUMNS",
    "_result_from_link",
    "verify_sqlite_payment_link_storage",
]
