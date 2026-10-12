"""Typed nonfinalizing Finance participant bound to the exact Inventory owner."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.inventory_receipt_posting import COMMIT_PERMISSIONS, ReceiptPlan, ReceiptReview
from reconforge.infrastructure.sqlite_finance_posting import (
    SQLiteFinancePostingRepository,
    posting_entry,
    posting_snapshot,
)
from reconforge.infrastructure.sqlite_inventory_receipt_posting import (
    SQLiteInventoryReceiptPostingRepository,
    _fail,
    _insert,
    verify_inventory_backing,
)
from reconforge.infrastructure.sqlite_inventory_unit_of_work import SQLiteInventoryUnitOfWork
from reconforge.io.inventory_receipt_posting import encode_receipt_json


class SQLiteInventoryReceiptFinanceParticipant:
    """Neither method starts, commits, rolls back or receipts a public command."""

    def __init__(self, connection: sqlite3.Connection, *, unit_of_work: SQLiteInventoryUnitOfWork) -> None:
        unit_of_work.require_active(connection)
        self.connection = connection
        self.owner = unit_of_work

    def _source(
        self, plan_id: str, expected_review_digest: str, actor: PostingActor
    ) -> tuple[SQLiteInventoryReceiptPostingRepository, ReceiptPlan, ReceiptReview, dict[str, Any]]:
        self.owner.require_active(self.connection)
        if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail("Reviewed source participation requires foreign_keys=ON.", "inventory_receipt_foreign_keys_required")
        repository = SQLiteInventoryReceiptPostingRepository(self.connection, unit_of_work=self.owner)
        plan = repository._plan(plan_id)
        permissions = COMMIT_PERMISSIONS | (
            {"inventory.valuation.reverse.approve", "finance_core.reverse"} if plan["original"] else set()
        )
        repository._authority(actor, frozenset(permissions), mutation=True)
        repository._checker(plan, actor)
        review = repository._review(plan)
        link = repository._one("SELECT * FROM inventory_receipt_links WHERE plan_id=?", (plan_id,))
        if (
            review["review_digest"] != expected_review_digest
            or link["review_id"] != review["review_id"]
            or link["review_digest"] != expected_review_digest
            or link["posted_actor_id"] != actor.user_id
        ):
            _fail(
                "Finance participation requires its exact persisted reviewed source and owner.",
                "inventory_receipt_review_changed",
            )
        return repository, plan, review, link

    def materialize_draft(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> str:
        with self.owner.operation(self.connection):
            repository, plan, _review, link = self._source(plan_id, expected_review_digest, actor)
            header = plan["finance_snapshot"]["entry"]
            journal = repository._one("SELECT chart_id FROM finance_journals WHERE id=?", (header["journal_id"],))
            record = {key: value for key, value in header.items() if key != "journal_id"}
            record.update(
                chart_id=journal["chart_id"],
                finance_journal_id=header["journal_id"],
                status="Draft",
                created_by=plan["preparer"]["username"],
                validated_by="",
                validated_at=None,
                validation_reason="",
                voided_by="",
                voided_at=None,
                void_reason="",
                created_at=link["posted_at"],
                updated_at=link["posted_at"],
                validator_actor_id=None,
                validation_digest=None,
                validation_contract_version=None,
            )
            _insert(self.connection, "ledger_entries", record)
            for line in plan["finance_snapshot"]["lines"]:
                line_record = {key: value for key, value in line.items() if key != "dimensions"}
                line_record.update(
                    id=plan["artifacts"][f"finance_line_{line['line_number']}_id"],
                    entry_id=header["id"],
                    created_at=link["posted_at"],
                )
                _insert(self.connection, "ledger_lines", line_record)
            if (
                posting_snapshot(self.connection, posting_entry(self.connection, header["id"]))
                != plan["finance_snapshot"]
            ):
                _fail("Materialized Finance draft differs from the reviewed source.")
            return str(header["id"])

    def seal_and_post(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner.operation(self.connection):
            repository, plan, review, link = self._source(plan_id, expected_review_digest, actor)
            verify_inventory_backing(repository, plan, review, link)
            entry_id = str(plan["artifacts"]["finance_entry_id"])
            entry = posting_entry(self.connection, entry_id)
            if entry["status"] != "Draft" or posting_snapshot(self.connection, entry) != plan["finance_snapshot"]:
                _fail("Only the exact reviewed Generated draft can acquire its source seal.")
            finance = SQLiteFinancePostingRepository(self.connection)
            finance._period(entry["period_id"], entry["workspace_id"], entry["posting_date"])
            finance._integrity(entry)
            self.connection.execute(
                "UPDATE ledger_entries SET status='Validated',validated_by=?,validated_at=?,validation_reason=?,"
                "validator_actor_id=?,validation_digest=?,validation_contract_version='finance-entry-review-v1' WHERE id=? AND status='Draft'",
                (
                    review["reviewer"]["username"],
                    review["reviewed_at"],
                    review["reason"],
                    review["reviewer"]["user_id"],
                    plan["finance_validation_digest"],
                    entry_id,
                ),
            )
            effect_id = str(plan["artifacts"]["posting_effect_id"])
            audit, outbox = finance._evidence(
                entry, effect_id, "finance_entry_posted", actor, plan["finance_validation_digest"]
            )
            effect = {
                "id": effect_id,
                **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                "entry_id": entry_id,
                "source_kind": "InventoryReceipt" if plan["operation"] == "Receipt" else "InventoryReceiptReversal",
                "source_id": plan_id,
                "purpose": "operational_posting",
                "reverses_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
                "validation_digest": plan["finance_validation_digest"],
                "validation_contract_version": "finance-entry-review-v1",
                **plan["currency_policy"],
                "snapshot_json": encode_receipt_json(plan["finance_snapshot"]),
                "posted_actor_id": actor.user_id,
                "posted_at": link["posted_at"],
                "reason": link["reason"],
                "audit_event_id": audit,
                "outbox_event_id": outbox,
            }
            _insert(self.connection, "finance_posting_effects", effect)
            return finance._get_effect(effect_id)
