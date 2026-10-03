"""Transaction-owned SQLite operational postings and exact full reversals."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.audit import append_audit_event
from reconforge.domain.finance_policy import FinancePolicyError
from reconforge.domain.finance_posting import (
    PROVENANCE_FIELDS,
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    make_entry_snapshot,
    require_full_reversal,
    require_reviewed,
    text,
    validation_digest,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.io.finance_posting import decode_posting_receipt
from reconforge.platform.common import append_outbox_event, platform_id


def posting_entry(connection: sqlite3.Connection, entry_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT *,finance_journal_id AS journal_id FROM ledger_entries WHERE id=?", (entry_id,)
    ).fetchone()
    if row is None:
        raise FinancePostingError("posting_entry_not_found", "Entry is absent from the selected local database.")
    return dict(row)


def posting_snapshot(connection: sqlite3.Connection, entry: Mapping[str, Any]) -> dict[str, Any]:
    FinancePolicyStore(connection).entry(entry)
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM ledger_lines WHERE entry_id=? ORDER BY line_number", (entry["id"],)
        )
    ]
    for row in rows:
        links = connection.execute(
            "SELECT v.dimension_id,l.dimension_value_id FROM ledger_line_dimensions l JOIN accounting_dimension_values v ON v.id=l.dimension_value_id WHERE l.line_id=? ORDER BY v.dimension_id",
            (row["id"],),
        ).fetchall()
        row["dimensions"] = {link["dimension_id"]: link["dimension_value_id"] for link in links}
        if len(row["dimensions"]) != len(links):
            raise FinancePostingError(
                "posting_content_invalid", "A line cannot contain multiple values of one dimension."
            )
    return make_entry_snapshot({**entry, "journal_id": entry["finance_journal_id"]}, rows)


def _stored_json(raw: str) -> dict[str, Any]:
    try:
        return decode_posting_receipt(raw).payload
    except (TypeError, ValueError) as exc:
        raise FinancePostingError("posting_evidence_invalid", "Stored posting evidence is malformed.") from exc


def verify_posting_storage(connection: sqlite3.Connection) -> None:
    """Verify retained financial records before publishing an export or restore."""
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='finance_posting_effects'"
        ).fetchone()
        is None
    ):
        return
    repository = SQLiteFinancePostingRepository(connection)
    for row in connection.execute("SELECT id FROM finance_posting_effects ORDER BY id").fetchall():
        effect = repository._get_effect(row["id"])
        if effect["reverses_effect_id"]:
            original = repository._get_effect(effect["reverses_effect_id"])
            if original["reverses_effect_id"] is not None:
                raise FinancePostingError(
                    "posting_evidence_invalid", "A retained reversal must reference an original posting."
                )
            require_full_reversal(original["snapshot"], effect["snapshot"])
    for row in connection.execute("SELECT * FROM finance_posting_commands ORDER BY workspace_id,command_id").fetchall():
        result = _stored_json(row["result_json"])
        if row["operation"] == "post":
            effect = repository._get_effect(text(result.get("id"), "effect_id"))
        else:
            reversal = posting_entry(connection, text(result.get("entry_id"), "entry_id"))
            effect = repository._get_effect(text(reversal["reverses_posting_id"], "effect_id"))
        entry = posting_entry(connection, effect["entry_id"])
        if entry["workspace_id"] != row["workspace_id"]:
            raise FinancePostingError(
                "posting_evidence_invalid", "Stored receipt workspace does not match its financial record."
            )
        repository._verify_receipt_result(entry, row["operation"], row["actor_id"], result)


class SQLiteFinancePostingUnitOfWork:
    """Explicit writer owner; bound repositories cannot commit or roll back it."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.active = False
        self.rollback_only = False

    def __enter__(self) -> SQLiteFinancePostingUnitOfWork:
        if self.active or self.connection.in_transaction:
            raise FinancePostingError(
                "posting_transaction_owned",
                "Posting requires an explicit transaction owner; pending caller work was not changed.",
            )
        self.connection.execute("BEGIN IMMEDIATE")
        self.active = True
        self.rollback_only = False
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if exc_type is not None or self.rollback_only:
                self.connection.rollback()
                if exc_type is None:
                    raise FinancePostingError(
                        "posting_transaction_failed",
                        "A failed bound operation requires rollback of the entire posting unit of work.",
                    )
            else:
                try:
                    self.connection.commit()
                except Exception:
                    self.connection.rollback()
                    raise
        finally:
            self.active = False

    def repository(self) -> SQLiteFinancePostingRepository:
        if not self.active or not self.connection.in_transaction or self.rollback_only:
            raise FinancePostingError("posting_transaction_required", "An active posting unit of work is required.")
        return SQLiteFinancePostingRepository(self.connection, unit_of_work=self)


class SQLiteFinancePostingRepository:
    """Use one writer transaction per command or an explicit active posting UoW."""

    def __init__(
        self, connection: sqlite3.Connection, *, unit_of_work: SQLiteFinancePostingUnitOfWork | None = None
    ) -> None:
        from reconforge.infrastructure.sqlite_finance_core import SQLiteFinanceCoreRepository

        self.connection = connection
        self.finance = SQLiteFinanceCoreRepository(connection)
        self.unit_of_work = unit_of_work
        if unit_of_work is not None and (unit_of_work.connection is not connection or not unit_of_work.active):
            raise FinancePostingError(
                "posting_transaction_required", "The posting unit of work must own this connection."
            )

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        try:
            with self._owned_transaction(write=write):
                yield
        except FinancePolicyError as exc:
            raise FinancePostingError(
                "posting_policy_unverified",
                "Retained currency policy is unverified; prepare a new authenticated draft.",
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise FinancePostingError(
                "posting_storage_failed",
                "Posting could not be committed; reload the financial state before retrying the same command.",
            ) from exc

    @contextmanager
    def _owned_transaction(self, *, write: bool = False) -> Iterator[None]:
        if self.unit_of_work is not None:
            owner = self.unit_of_work
            if not owner.active or not self.connection.in_transaction or owner.rollback_only:
                raise FinancePostingError("posting_transaction_required", "An active posting unit of work is required.")
            try:
                yield
            except Exception:
                owner.rollback_only = True
                raise
        elif write:
            with SQLiteFinancePostingUnitOfWork(self.connection):
                yield
        else:
            owns = not self.connection.in_transaction
            if owns:
                self.connection.execute("BEGIN")
            try:
                yield
            finally:
                if owns:
                    self.connection.rollback()

    @staticmethod
    def _read(actor: PostingActor) -> None:
        permission = next(
            (
                item
                for item in ("finance_core.read", "finance_core.post", "finance_core.validate", "finance_core.manage")
                if item in actor.permissions
            ),
            "finance_core.read",
        )
        actor.require(permission, mutation=False)

    def _period(self, period_id: str, workspace_id: str, posting_date: str) -> None:
        row = self.connection.execute(
            "SELECT status,start_date,end_date FROM periods WHERE id=? AND workspace_id=?", (period_id, workspace_id)
        ).fetchone()
        if row is None or row["status"] != "Open" or not row["start_date"] <= posting_date <= row["end_date"]:
            raise FinancePostingError(
                "posting_period_closed", "Posting requires an Open scoped fiscal period containing the business date."
            )

    def _integrity(self, entry: dict[str, Any]) -> None:
        self.finance._validate_entry_integrity(entry)
        row = self.connection.execute(
            """SELECT 1 FROM organizations o JOIN legal_entities e ON e.organization_id=o.id
          JOIN finance_journals j ON j.organization_id=o.id AND j.workspace_id=o.workspace_id
          JOIN charts_of_accounts c ON c.id=j.chart_id AND c.workspace_id=o.workspace_id
          WHERE o.id=? AND e.id=? AND j.id=? AND o.workspace_id=?
           AND (c.organization_id IS NULL OR c.organization_id=o.id)""",
            (entry["organization_id"], entry["legal_entity_id"], entry["finance_journal_id"], entry["workspace_id"]),
        ).fetchone()
        if row is None:
            raise FinancePostingError(
                "posting_scope_denied", "Posting references inconsistent canonical finance parents."
            )

    def _command(
        self, entry: Mapping[str, Any], command_id: str, operation: str, actor: PostingActor, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "command_id")
        digest = digest_payload(
            {"operation": operation, "actor_id": actor.user_id, "workspace_id": entry["workspace_id"], **payload}
        )
        row = self.connection.execute(
            "SELECT request_digest,actor_id,operation,result_json FROM finance_posting_commands WHERE workspace_id=? AND command_id=?",
            (entry["workspace_id"], command_id),
        ).fetchone()
        if row is not None:
            if (row["request_digest"], row["actor_id"], row["operation"]) != (digest, actor.user_id, operation):
                raise FinancePostingError(
                    "posting_command_conflict", "Command identifier already refers to different content or actor."
                )
            result = _stored_json(row["result_json"])
            self._verify_receipt_result(entry, operation, actor.user_id, result, payload=payload)
            return digest, result
        return digest, None

    def _verify_receipt_result(
        self,
        entry: Mapping[str, Any],
        operation: str,
        actor_id: str,
        result: dict[str, Any],
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if operation == "post":
            effect = self._get_effect(text(result.get("id"), "effect_id"))
            valid = (
                result == effect
                and effect["workspace_id"] == entry["workspace_id"]
                and effect["posted_actor_id"] == actor_id
            )
            valid = valid and effect["entry_id"] == entry["id"]
            if payload is not None:
                valid = (
                    valid
                    and effect["validation_digest"] == payload["expected_validation_digest"]
                    and effect["reason"] == payload["reason"]
                )
        else:
            reversal = posting_entry(self.connection, text(result.get("entry_id"), "entry_id"))
            valid = result == {
                "entry_id": reversal["id"],
                "entry_number": reversal["entry_number"],
                "status": "Draft",
                "reverses_posting_id": reversal["reverses_posting_id"],
                "preparer_actor_id": reversal["preparer_actor_id"],
            }
            valid = (
                valid
                and reversal["workspace_id"] == entry["workspace_id"]
                and reversal["preparer_actor_id"] == actor_id
                and reversal["reverses_posting_id"] is not None
            )
            original = self._get_effect(text(reversal["reverses_posting_id"], "effect_id"))
            valid = valid and original["entry_id"] == entry["id"]
            if payload is not None:
                valid = (
                    valid
                    and reversal["reverses_posting_id"] == payload["effect_id"]
                    and all(reversal[key] == payload[key] for key in ("entry_number", "period_id", "posting_date"))
                    and reversal["description"] == payload["reason"]
                )
        if not valid:
            raise FinancePostingError(
                "posting_evidence_invalid", "Stored command receipt does not match its committed financial record."
            )

    def _receipt(
        self,
        entry: Mapping[str, Any],
        command_id: str,
        operation: str,
        actor: PostingActor,
        digest: str,
        result: dict[str, Any],
    ) -> None:
        self.connection.execute(
            "INSERT INTO finance_posting_commands(workspace_id,command_id,operation,actor_id,request_digest,result_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                entry["workspace_id"],
                text(command_id, "command_id"),
                operation,
                actor.user_id,
                digest,
                canonical_json(result),
                utc_now_text(),
            ),
        )

    def _evidence(
        self, entry: Mapping[str, Any], identifier: str, action: str, actor: PostingActor, digest: str
    ) -> tuple[str, str]:
        event = append_audit_event(
            self.connection,
            actor_user_id=actor.user_id,
            actor_label=actor.username,
            object_type="finance_posting",
            object_id=identifier,
            action=action,
            metadata={"entry_id": entry["id"], "content_digest": digest},
        )
        outbox_id = "OBX-" + uuid4().hex
        append_outbox_event(
            self.connection,
            event_id=outbox_id,
            event_type=action,
            aggregate_type="finance_posting",
            aggregate_id=identifier,
            payload={"entry_id": entry["id"], "audit_event_id": event.id, "content_digest": digest},
        )
        return event.id, outbox_id

    def preview(self, entry_id: str, *, actor: PostingActor) -> dict[str, Any]:
        self._read(actor)
        with self._transaction():
            entry = posting_entry(self.connection, text(entry_id, "entry_id"))
            snapshot = posting_snapshot(self.connection, entry)
            return {
                "entry_id": entry["id"],
                "status": entry["status"],
                **{key: entry[key] for key in PROVENANCE_FIELDS},
                "current_content_digest": validation_digest(snapshot),
                "snapshot": snapshot,
            }

    def _get_effect(self, effect_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM finance_posting_effects WHERE id=?", (effect_id,)).fetchone()
        if row is None:
            raise FinancePostingError("posting_effect_not_found", "Posting is absent from the selected local database.")
        effect = dict(row)
        effect["snapshot"] = _stored_json(effect.pop("snapshot_json"))
        entry = posting_entry(self.connection, effect["entry_id"])
        policy_fields = (
            "workspace_id",
            "organization_id",
            "legal_entity_id",
            "validation_digest",
            "validation_contract_version",
            "currency_code",
            "currency_precision",
            "currency_rounding_policy",
            "currency_registry_version",
            "currency_registry_digest",
        )
        valid = validation_digest(effect["snapshot"]) == effect["validation_digest"] and effect[
            "snapshot"
        ] == posting_snapshot(self.connection, entry)
        valid = valid and entry["status"] == "Validated" and all(effect[key] == entry[key] for key in policy_fields)
        valid = (
            valid
            and entry["preparer_actor_id"] is not None
            and entry["validator_actor_id"] is not None
            and entry["preparer_actor_id"] not in (entry["validator_actor_id"], effect["posted_actor_id"])
        )
        valid = (
            valid
            and effect["reverses_effect_id"] == entry["reverses_posting_id"]
            and effect["source_id"] == (entry["reverses_posting_id"] or entry["id"])
        )
        valid = valid and effect["source_kind"] == ("Reversal" if entry["reverses_posting_id"] else "Manual")
        audit = self.connection.execute("SELECT * FROM audit_events WHERE id=?", (effect["audit_event_id"],)).fetchone()
        outbox = self.connection.execute(
            "SELECT * FROM outbox_events WHERE id=?", (effect["outbox_event_id"],)
        ).fetchone()
        expected_metadata = {"entry_id": entry["id"], "content_digest": effect["validation_digest"]}
        valid = valid and audit is not None and outbox is not None
        if audit is not None and outbox is not None:
            valid = valid and (audit["actor_user_id"], audit["object_type"], audit["object_id"], audit["action"]) == (
                effect["posted_actor_id"],
                "finance_posting",
                effect["id"],
                "finance_entry_posted",
            )
            valid = valid and _stored_json(audit["metadata_json"]) == expected_metadata
            valid = valid and (outbox["aggregate_type"], outbox["aggregate_id"], outbox["event_type"]) == (
                "finance_posting",
                effect["id"],
                "finance_entry_posted",
            )
            valid = valid and _stored_json(outbox["payload_json"]) == {
                **expected_metadata,
                "audit_event_id": effect["audit_event_id"],
            }
        if not valid:
            raise FinancePostingError("posting_evidence_invalid", "Retained posting evidence failed verification.")
        return effect

    def get_effect(self, effect_id: str, *, actor: PostingActor) -> dict[str, Any]:
        self._read(actor)
        with self._transaction():
            return self._get_effect(text(effect_id, "effect_id"))

    def post(
        self, entry_id: str, *, command_id: str, expected_validation_digest: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        actor.require("finance_core.post")
        reason = text(reason, "reason", maximum=500)
        with self._transaction(write=True):
            entry = posting_entry(self.connection, text(entry_id, "entry_id"))
            if entry["reverses_posting_id"]:
                actor.require("finance_core.reverse")
            digest, replay = self._command(
                entry,
                command_id,
                "post",
                actor,
                {"entry_id": entry_id, "expected_validation_digest": expected_validation_digest, "reason": reason},
            )
            if replay is not None:
                return replay
            self._period(entry["period_id"], entry["workspace_id"], entry["posting_date"])
            snapshot = posting_snapshot(self.connection, entry)
            reviewed = require_reviewed(entry, snapshot, actor)
            if reviewed != expected_validation_digest:
                raise FinancePostingError(
                    "posting_review_changed", "Expected validation digest does not match the current reviewed entry."
                )
            self._integrity(entry)
            reversal = entry["reverses_posting_id"]
            if reversal:
                actor.require("finance_core.reverse")
                original = self._get_effect(reversal)
                if original["reverses_effect_id"] is not None:
                    raise FinancePostingError(
                        "posting_reversal_invalid", "A reversal cannot itself be reversed in this contract."
                    )
                require_full_reversal(original["snapshot"], snapshot)
            elif entry["source_type"] != "Manual":
                raise FinancePostingError(
                    "posting_source_unsupported", "Only Manual entries and prepared full reversals can be posted."
                )
            if self.connection.execute(
                "SELECT 1 FROM finance_posting_effects WHERE entry_id=? OR reverses_effect_id=?", (entry_id, reversal)
            ).fetchone():
                raise FinancePostingError(
                    "posting_source_conflict", "The source already has a committed operational effect."
                )
            effect_id, now = "PST-" + uuid4().hex, utc_now_text()
            self.connection.execute("UPDATE ledger_entries SET updated_at=? WHERE id=?", (now, entry_id))
            audit_id, outbox_id = self._evidence(entry, effect_id, "finance_entry_posted", actor, reviewed)
            self.connection.execute(
                """INSERT INTO finance_posting_effects
             (id,workspace_id,organization_id,legal_entity_id,entry_id,source_kind,source_id,purpose,reverses_effect_id,
              validation_digest,validation_contract_version,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,
              snapshot_json,posted_actor_id,posted_at,reason,audit_event_id,outbox_event_id)
             VALUES(?,?,?,?,?,?,?,'operational_posting',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    effect_id,
                    entry["workspace_id"],
                    entry["organization_id"],
                    entry["legal_entity_id"],
                    entry_id,
                    "Reversal" if reversal else "Manual",
                    reversal or entry_id,
                    reversal,
                    reviewed,
                    entry["validation_contract_version"],
                    entry["currency_code"],
                    entry["currency_precision"],
                    entry["currency_rounding_policy"],
                    entry["currency_registry_version"],
                    entry["currency_registry_digest"],
                    canonical_json(snapshot),
                    actor.user_id,
                    now,
                    reason,
                    audit_id,
                    outbox_id,
                ),
            )
            result = self._get_effect(effect_id)
            self._receipt(entry, command_id, "post", actor, digest, result)
            return result

    def prepare_reversal(
        self,
        effect_id: str,
        *,
        command_id: str,
        entry_number: str,
        period_id: str,
        posting_date: str,
        reason: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        from reconforge.infrastructure.sqlite_finance_core import _entry_number, _iso_date

        actor.require("finance_core.reverse")
        actor.require("finance_core.manage")
        reason, number = text(reason, "reason", maximum=500), _entry_number(entry_number)
        posting_date = _iso_date(posting_date, "Posting date").isoformat()
        with self._transaction(write=True):
            original = self._get_effect(text(effect_id, "effect_id"))
            source = posting_entry(self.connection, original["entry_id"])
            digest, replay = self._command(
                source,
                command_id,
                "prepare_reversal",
                actor,
                {
                    "effect_id": effect_id,
                    "entry_number": number,
                    "period_id": period_id,
                    "posting_date": posting_date,
                    "reason": reason,
                },
            )
            if replay is not None:
                return replay
            if original["reverses_effect_id"] is not None:
                raise FinancePostingError(
                    "posting_reversal_invalid", "A reversal cannot itself be reversed in this contract."
                )
            self._period(text(period_id, "period_id"), source["workspace_id"], posting_date)
            entry_id, now = platform_id("GLE", source["workspace_id"], number), utc_now_text()
            if self.connection.execute("SELECT 1 FROM ledger_entries WHERE id=?", (entry_id,)).fetchone():
                raise FinancePostingError(
                    "posting_source_conflict", "The requested reversal entry number already exists."
                )
            self.connection.execute(
                """INSERT INTO ledger_entries
             (id,workspace_id,organization_id,chart_id,legal_entity_id,period_id,finance_journal_id,entry_number,posting_date,description,external_reference,source_type,status,
              currency_code,created_by,created_at,updated_at,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,preparer_actor_id,reverses_posting_id)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,'Generated','Draft',?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id,
                    source["workspace_id"],
                    source["organization_id"],
                    source["chart_id"],
                    source["legal_entity_id"],
                    period_id,
                    source["finance_journal_id"],
                    number,
                    posting_date,
                    reason,
                    effect_id,
                    source["currency_code"],
                    actor.username,
                    now,
                    now,
                    source["currency_precision"],
                    source["currency_rounding_policy"],
                    source["currency_registry_version"],
                    source["currency_registry_digest"],
                    actor.user_id,
                    effect_id,
                ),
            )
            for line in original["snapshot"]["lines"]:
                line_id = platform_id("GLL", entry_id, line["line_number"])
                self.connection.execute(
                    "INSERT INTO ledger_lines(id,entry_id,line_number,account_id,description,debit_minor,credit_minor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        line_id,
                        entry_id,
                        line["line_number"],
                        line["account_id"],
                        line["description"],
                        line["credit_minor"],
                        line["debit_minor"],
                        now,
                    ),
                )
                for value in line["dimensions"].values():
                    self.connection.execute(
                        "INSERT INTO ledger_line_dimensions(line_id,dimension_value_id) VALUES(?,?)", (line_id, value)
                    )
            new_entry = posting_entry(self.connection, entry_id)
            self._integrity(new_entry)
            require_full_reversal(original["snapshot"], posting_snapshot(self.connection, new_entry))
            self._evidence(new_entry, entry_id, "finance_reversal_prepared", actor, digest)
            result = {
                "entry_id": entry_id,
                "entry_number": number,
                "status": "Draft",
                "reverses_posting_id": effect_id,
                "preparer_actor_id": actor.user_id,
            }
            self._receipt(new_entry, command_id, "prepare_reversal", actor, digest, result)
            return result

    def posted_trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor: PostingActor,
    ) -> dict[str, Any]:
        self._read(actor)
        with self._transaction():
            workspace_id = self.finance._workspace_id(workspace)
            if workspace_id is None:
                raise FinancePostingError("posting_scope_denied", "The selected workspace does not exist.")
            rows = self.connection.execute(
                """SELECT p.id FROM finance_posting_effects p JOIN ledger_entries e ON e.id=p.entry_id
              JOIN organizations o ON o.id=p.organization_id JOIN legal_entities le ON le.id=p.legal_entity_id
              WHERE p.workspace_id=? AND o.organization_code=? AND le.entity_code=? AND e.period_id=? ORDER BY p.id""",
                (workspace_id, organization_code, entity_code, period_id),
            ).fetchall()
            accounts: dict[str, dict[str, Any]] = {}
            policy = None
            for row in rows:
                effect = self._get_effect(row["id"])
                selected = {
                    key: effect[key]
                    for key in (
                        "currency_code",
                        "currency_precision",
                        "currency_rounding_policy",
                        "currency_registry_version",
                        "currency_registry_digest",
                    )
                }
                if policy is not None and selected != policy:
                    raise FinancePostingError(
                        "posting_policy_mismatch", "Posted balances require compatible retained currency policies."
                    )
                policy = selected
                for line in effect["snapshot"]["lines"]:
                    account = accounts.setdefault(
                        line["account_id"],
                        {
                            "account_id": line["account_id"],
                            "debit_minor": 0,
                            "credit_minor": 0,
                            "balance_minor": 0,
                            "postings": [],
                        },
                    )
                    account["debit_minor"] += line["debit_minor"]
                    account["credit_minor"] += line["credit_minor"]
                    account["balance_minor"] = account["debit_minor"] - account["credit_minor"]
                    account["postings"].append(
                        {
                            "effect_id": effect["id"],
                            "entry_id": effect["entry_id"],
                            "line_number": line["line_number"],
                            "debit_minor": line["debit_minor"],
                            "credit_minor": line["credit_minor"],
                        }
                    )
            for account in accounts.values():
                account["debit_balance_minor"] = max(account["balance_minor"], 0)
                account["credit_balance_minor"] = max(-account["balance_minor"], 0)
            debit, credit = (
                sum(a["debit_minor"] for a in accounts.values()),
                sum(a["credit_minor"] for a in accounts.values()),
            )
            debit_balance, credit_balance = (
                sum(a["debit_balance_minor"] for a in accounts.values()),
                sum(a["credit_balance_minor"] for a in accounts.values()),
            )
            return {
                "workspace_id": workspace_id,
                "organization_code": organization_code,
                "entity_code": entity_code,
                "period_id": period_id,
                "currency_policy": policy,
                "effect_count": len(rows),
                "accounts": [accounts[key] for key in sorted(accounts)],
                "totals": {"debit_minor": debit, "credit_minor": credit, "balanced": debit == credit},
                "balance_totals": {
                    "debit_minor": debit_balance,
                    "credit_minor": credit_balance,
                    "balanced": debit_balance == credit_balance,
                },
            }
