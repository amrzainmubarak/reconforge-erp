"""Scoped, atomic PostgreSQL manual posting and exact full reversals."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_balances import (
    MAX_BALANCE_EFFECTS,
    balance_window,
    build_posted_balances,
    business_date,
    collect_balance_effects,
)
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
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository, _entry_number, _iso_date
from reconforge.infrastructure.postgres_repository_scope import (
    PostgresRepositoryScopeError,
    ensure_repository_tenant_scope,
)
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import code


def records(cursor: Any) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(row) if isinstance(row, Mapping) else dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def posting_entry(connection: Any, tenant_id: str, entry_id: str, *, lock: bool = False) -> dict[str, Any]:
    query = """SELECT e.*,o.id AS organization_id,le.id AS legal_entity_id FROM reconforge.finance_entries e
      JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.organization_code=e.organization_code
       AND o.application_workspace_id=e.workspace_id
      JOIN reconforge.legal_entities le ON le.tenant_id=o.tenant_id AND le.organization_id=o.id AND le.entity_code=e.entity_code
      WHERE e.tenant_id=%s AND e.id=%s"""
    if lock:
        query += " FOR UPDATE OF e"
    rows = records(connection.execute(query, (tenant_id, entry_id)))
    if not rows:
        raise FinancePostingError("posting_entry_not_found", "Entry is absent or outside the authorized scope.")
    return rows[0]


def posting_snapshot(connection: Any, tenant_id: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    FinancePolicyStore(connection, tenant_id=tenant_id).entry(entry)
    rows = records(
        connection.execute(
            "SELECT id,line_number,account_id,description,debit_minor,credit_minor FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number",
            (tenant_id, entry["id"]),
        )
    )
    for row in rows:
        links = records(
            connection.execute(
                "SELECT dimension_id,dimension_value_id FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND entry_line_id=%s ORDER BY dimension_id",
                (tenant_id, row["id"]),
            )
        )
        row["dimensions"] = {link["dimension_id"]: link["dimension_value_id"] for link in links}
    return make_entry_snapshot(entry, rows)


class PostgresFinancePostingRepository:
    """Own a transaction or savepoint on the caller's already scoped connection."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.finance = PostgresFinanceCoreRepository(connection, self.tenant_id)

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        try:
            with self.connection.transaction():
                ensure_repository_tenant_scope(self.connection, self.tenant_id)
                if write:
                    row = self.connection.execute("SHOW transaction_isolation").fetchone()
                    isolation = row["transaction_isolation"] if isinstance(row, Mapping) else row[0]
                    if isolation != "read committed":
                        raise FinancePostingError(
                            "posting_isolation_required", "Operational posting requires READ COMMITTED."
                        )
                yield
        except FinancePolicyError as exc:
            raise FinancePostingError(
                "posting_policy_unverified",
                "Retained currency policy is unverified; prepare a new authenticated draft.",
            ) from exc
        except PostgresRepositoryScopeError as exc:
            raise FinancePostingError(
                "posting_scope_denied", "Posting repository does not match the established execution scope."
            ) from exc
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23505", "23514", "40001", "40P01"}:
                raise FinancePostingError(
                    "posting_state_invalid",
                    "Posting conflicts with retained financial state; reload the entry and review the current result.",
                ) from exc
            raise

    @staticmethod
    def _read(actor: PostingActor) -> None:
        permission = next(
            (
                p
                for p in ("finance_core.read", "finance_core.post", "finance_core.validate", "finance_core.manage")
                if p in actor.permissions
            ),
            "finance_core.read",
        )
        actor.require(permission, mutation=False)

    def _period(self, period_id: str, workspace_id: str, posting_date: str) -> None:
        rows = records(
            self.connection.execute(
                "SELECT status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                (self.tenant_id, period_id, workspace_id),
            )
        )
        if (
            not rows
            or rows[0]["status"] != "Open"
            or not str(rows[0]["start_date"]) <= posting_date <= str(rows[0]["end_date"])
        ):
            raise FinancePostingError(
                "posting_period_closed", "Posting requires an Open scoped fiscal period containing the business date."
            )

    def _command(
        self, entry: Mapping[str, Any], command_id: str, operation: str, actor: PostingActor, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "command_id")
        digest = digest_payload(
            {"operation": operation, "actor_id": actor.user_id, "workspace_id": entry["workspace_id"], **payload}
        )
        # Serialize acknowledgement retries even when a reused key names another entry.
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, entry["workspace_id"], command_id]),),
        )
        rows = records(
            self.connection.execute(
                "SELECT request_digest,actor_id,operation,result_json FROM reconforge.finance_posting_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                (self.tenant_id, entry["workspace_id"], command_id),
            )
        )
        if rows:
            row = rows[0]
            if (row["request_digest"], row["actor_id"], row["operation"]) != (digest, actor.user_id, operation):
                raise FinancePostingError(
                    "posting_command_conflict", "Command identifier already refers to different content or actor."
                )
            result = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else row["result_json"]
            self._verify_replay(entry, operation, actor, payload, result)
            return digest, result
        return digest, None

    def _verify_replay(
        self, source: Mapping[str, Any], operation: str, actor: PostingActor, payload: Mapping[str, Any], result: Any
    ) -> None:
        """A stored acknowledgement cannot stand in for its real financial source."""
        try:
            if not isinstance(result, dict):
                raise ValueError("invalid receipt")
            if operation == "post":
                effect = self._get_effect(result["id"])
                bound = effect
                valid = (
                    effect == result
                    and effect["entry_id"] == source["id"]
                    and effect["posted_actor_id"] == actor.user_id
                    and effect["validation_digest"] == payload["expected_validation_digest"]
                    and effect["reason"] == payload["reason"]
                )
            else:
                entry = posting_entry(self.connection, self.tenant_id, result["entry_id"])
                bound = entry
                original = self._get_effect(entry["reverses_posting_id"])
                expected = {
                    "entry_id": entry["id"],
                    "entry_number": entry["entry_number"],
                    "status": "Draft",
                    "reverses_posting_id": entry["reverses_posting_id"],
                    "preparer_actor_id": entry["preparer_actor_id"],
                }
                valid = (
                    result == expected
                    and entry["preparer_actor_id"] == actor.user_id
                    and original["entry_id"] == source["id"]
                    and original["id"] == payload["effect_id"]
                    and entry["entry_number"] == payload["entry_number"]
                )
            valid = valid and all(
                bound[key] == source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancePostingError(
                "posting_evidence_invalid", "Command receipt has no verified financial source."
            ) from exc
        if not valid:
            raise FinancePostingError(
                "posting_evidence_invalid", "Command receipt does not match its requested financial source."
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
            """INSERT INTO reconforge.finance_posting_commands
         (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,result_json,created_at)
         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
            (
                self.tenant_id,
                entry["workspace_id"],
                entry["organization_id"],
                entry["legal_entity_id"],
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
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_user_id=actor.user_id,
            actor_label=actor.username,
            object_type="finance_posting",
            object_id=identifier,
            action=action,
            metadata={"entry_id": entry["id"], "content_digest": digest},
        )
        outbox_id = "OBX-" + uuid4().hex
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events
         (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,workspace_id,organization_id,legal_entity_id)
         VALUES(%s,%s,%s,'finance_posting',%s,%s::jsonb,%s,%s,%s)""",
            (
                self.tenant_id,
                outbox_id,
                action,
                identifier,
                canonical_json({"entry_id": entry["id"], "audit_event_id": audit.id, "content_digest": digest}),
                entry["workspace_id"],
                entry["organization_id"],
                entry["legal_entity_id"],
            ),
        )
        return audit.id, outbox_id

    def preview(self, entry_id: str, *, actor: PostingActor) -> dict[str, Any]:
        self._read(actor)
        with self._transaction():
            entry = posting_entry(self.connection, self.tenant_id, text(entry_id, "entry_id"))
            if entry["entry_number"].upper().startswith("FI1-") or entry["id"].upper().startswith("FI1-"):
                from reconforge.infrastructure.postgres_financial_installments import _InstallmentPostingParticipant

                if not isinstance(_source_owner, _InstallmentPostingParticipant) or not _source_owner.admits(
                    self.connection, self.tenant_id, entry["id"]
                ):
                    raise FinancePostingError(
                        "posting_source_unsupported", "Installments must post through their complete settlement owner."
                    )
            snapshot = posting_snapshot(self.connection, self.tenant_id, entry)
            return {
                "entry_id": entry["id"],
                "status": entry["status"],
                **{key: entry[key] for key in PROVENANCE_FIELDS},
                "current_content_digest": validation_digest(snapshot),
                "snapshot": snapshot,
            }

    def _get_effect(self, effect_id: str) -> dict[str, Any]:
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, effect_id),
            )
        )
        if not rows:
            raise FinancePostingError("posting_effect_not_found", "Posting is absent or outside the authorized scope.")
        row = rows[0]
        row.pop("tenant_id")
        raw = row.pop("snapshot_json")
        row["snapshot"] = raw if isinstance(raw, dict) else json.loads(raw)
        if validation_digest(row["snapshot"]) != row["validation_digest"]:
            raise FinancePostingError("posting_evidence_invalid", "Retained posting evidence failed verification.")
        evidence = self.connection.execute(
            """SELECT 1 FROM reconforge.domain_audit_events a
             JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
             WHERE a.tenant_id=%s AND a.id=%s AND o.event_id=%s
             AND a.actor_user_id=%s AND a.object_type='finance_posting' AND a.object_id=%s
             AND a.action='finance_entry_posted' AND a.metadata_json=%s::jsonb
             AND o.event_type='finance_entry_posted' AND o.aggregate_type='finance_posting' AND o.aggregate_id=%s
             AND o.payload=%s::jsonb AND o.workspace_id=%s AND o.organization_id=%s AND o.legal_entity_id=%s""",
            (
                self.tenant_id,
                row["audit_event_id"],
                row["outbox_event_id"],
                row["posted_actor_id"],
                row["id"],
                canonical_json({"entry_id": row["entry_id"], "content_digest": row["validation_digest"]}),
                row["id"],
                canonical_json(
                    {
                        "entry_id": row["entry_id"],
                        "content_digest": row["validation_digest"],
                        "audit_event_id": row["audit_event_id"],
                    }
                ),
                row["workspace_id"],
                row["organization_id"],
                row["legal_entity_id"],
            ),
        ).fetchone()
        if not evidence:
            raise FinancePostingError("posting_evidence_invalid", "Retained posting evidence failed verification.")
        if row["source_kind"] in {"InventoryReceipt", "InventoryReceiptReversal"}:
            from reconforge.infrastructure.postgres_inventory_receipt_posting import (
                verify_inventory_receipt_finance_effect,
            )

            verify_inventory_receipt_finance_effect(self.connection, self.tenant_id, row)
        return row

    def get_effect(self, effect_id: str, *, actor: PostingActor) -> dict[str, Any]:
        self._read(actor)
        with self._transaction():
            return self._get_effect(text(effect_id, "effect_id"))

    def post(
        self,
        entry_id: str,
        *,
        command_id: str,
        expected_validation_digest: str,
        reason: str,
        actor: PostingActor,
        _source_owner: object | None = None,
    ) -> dict[str, Any]:
        actor.require("finance_core.post")
        reason = text(reason, "reason", maximum=500)
        with self._transaction(write=True):
            entry = posting_entry(self.connection, self.tenant_id, text(entry_id, "entry_id"))
            if entry["entry_number"].upper().startswith("OB1-") or entry["id"].upper().startswith("OB1-"):
                from reconforge.infrastructure.postgres_financial_reporting import _OpeningPostingParticipant

                if not isinstance(_source_owner, _OpeningPostingParticipant) or not _source_owner.admits(
                    self.connection, self.tenant_id, entry["id"]
                ):
                    raise FinancePostingError(
                        "posting_source_unsupported", "Opening balances must post through their complete reviewed source owner."
                    )
            if entry["entry_number"].upper().startswith("OPS1-") or entry["id"].upper().startswith("OPS1-"):
                from reconforge.infrastructure.postgres_operational_finance import _OperationalPostingParticipant

                if not isinstance(_source_owner, _OperationalPostingParticipant) or not _source_owner.admits(
                    self.connection, self.tenant_id, entry["id"]
                ):
                    raise FinancePostingError(
                        "posting_source_unsupported",
                        "Operational sources must post through their complete source owner.",
                    )
            if entry["id"].upper().startswith("IRP1-") or entry["entry_number"].upper().startswith("IRP1-"):
                raise FinancePostingError("posting_source_unsupported", "Reviewed inventory sources must post through their complete source command.")
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
            entry = posting_entry(self.connection, self.tenant_id, entry_id, lock=True)
            snapshot = posting_snapshot(self.connection, self.tenant_id, entry)
            reviewed = require_reviewed(entry, snapshot, actor)
            if reviewed != expected_validation_digest:
                raise FinancePostingError(
                    "posting_review_changed", "Expected validation digest does not match the current reviewed entry."
                )
            self.finance._validate_entry_integrity(entry_id)
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
                "SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND (entry_id=%s OR reverses_effect_id=%s)",
                (self.tenant_id, entry_id, reversal),
            ).fetchone():
                raise FinancePostingError(
                    "posting_source_conflict", "The source already has a committed operational effect."
                )
            effect_id, now = "PST-" + uuid4().hex, utc_now_text()
            # Force a parent row version change before sealing, including against stale RR child writers.
            self.connection.execute(
                "UPDATE reconforge.finance_entries SET updated_at=%s WHERE tenant_id=%s AND id=%s",
                (now, self.tenant_id, entry_id),
            )
            audit_id, outbox_id = self._evidence(entry, effect_id, "finance_entry_posted", actor, reviewed)
            self.connection.execute(
                """INSERT INTO reconforge.finance_posting_effects
             (tenant_id,id,workspace_id,organization_id,legal_entity_id,entry_id,source_kind,source_id,purpose,reverses_effect_id,
              validation_digest,validation_contract_version,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,
              snapshot_json,posted_actor_id,posted_at,reason,audit_event_id,outbox_event_id)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'operational_posting',%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
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
        actor.require("finance_core.reverse")
        actor.require("finance_core.manage")
        reason = text(reason, "reason", maximum=500)
        number = _entry_number(entry_number)
        posting_date = _iso_date(posting_date, "Posting date").isoformat()
        with self._transaction(write=True):
            original = self._get_effect(text(effect_id, "effect_id"))
            if original["source_kind"] not in {"Manual", "Reversal"}:
                raise FinancePostingError("posting_source_unsupported", "Inventory postings require a reviewed full source inverse.")
            source = posting_entry(self.connection, self.tenant_id, original["entry_id"])
            if source["entry_number"].upper().startswith(("OPS1-", "OB1-", "FI1-")) or source["id"].upper().startswith(("OPS1-", "OB1-", "FI1-")):
                raise FinancePostingError(
                    "posting_source_unsupported", "Operational sources require a reviewed native source inverse."
                )
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
            self._period(text(period_id, "period_id"), source["workspace_id"], text(posting_date, "posting_date"))
            entry_id, now = platform_id("GLE", source["workspace_id"], number), utc_now_text()
            self.connection.execute(
                """INSERT INTO reconforge.finance_entries
             (tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,posting_date,description,external_reference,source_type,status,
              currency_code,total_debit_minor,total_credit_minor,created_by,created_at,updated_at,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,preparer_actor_id,reverses_posting_id)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Generated','Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    entry_id,
                    source["workspace_id"],
                    source["journal_id"],
                    source["organization_code"],
                    source["entity_code"],
                    period_id,
                    number,
                    posting_date,
                    reason,
                    effect_id,
                    source["currency_code"],
                    source["total_credit_minor"],
                    source["total_debit_minor"],
                    actor.user_id,
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
                    "INSERT INTO reconforge.finance_entry_lines(tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.tenant_id,
                        line_id,
                        entry_id,
                        line["line_number"],
                        line["account_id"],
                        line["description"],
                        line["credit_minor"],
                        line["debit_minor"],
                        source["currency_code"],
                    ),
                )
                for dimension, value in line["dimensions"].items():
                    self.connection.execute(
                        "INSERT INTO reconforge.finance_entry_line_dimensions(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)",
                        (self.tenant_id, line_id, dimension, value),
                    )
            self.finance._validate_entry_integrity(entry_id)
            new_entry = posting_entry(self.connection, self.tenant_id, entry_id)
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

    def posted_balances_as_of(
        self, *, period_id: str, as_of_date: str, organization_code: str,
        entity_code: str, workspace: str = "default", actor: PostingActor,
    ) -> dict[str, Any]:
        self._read(actor)
        period_id = text(period_id, "period_id")
        cutoff = business_date(as_of_date)
        organization_code, entity_code = code(organization_code, "Organization code"), code(entity_code, "Entity code")
        with self._transaction():
            workspace_id = self.finance._required_workspace_id(workspace)
            scopes = records(self.connection.execute(
                """SELECT o.id AS organization_id,le.id AS legal_entity_id FROM reconforge.organizations o
                JOIN reconforge.legal_entities le ON le.tenant_id=o.tenant_id AND le.organization_id=o.id
                WHERE o.tenant_id=%s AND o.application_workspace_id=%s AND o.organization_code=%s AND le.entity_code=%s""",
                (self.tenant_id, workspace_id, organization_code, entity_code),
            ))
            periods = records(self.connection.execute(
                "SELECT start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                (self.tenant_id, period_id, workspace_id),
            ))
            if not scopes or not periods:
                raise FinancePostingError("posting_scope_denied", "The selected entity and period must exist in the authorized workspace.")
            scope, period = scopes[0], periods[0]
            start, end, cutoff = balance_window(str(period["start_date"]), str(period["end_date"]), cutoff)
            rows = records(self.connection.execute(
                """SELECT p.id,e.posting_date,fp.start_date,fp.end_date FROM reconforge.finance_posting_effects p
                JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.id=p.entry_id
                LEFT JOIN reconforge.fiscal_periods fp ON fp.tenant_id=e.tenant_id AND fp.id=e.period_id
                 AND fp.application_workspace_id=p.workspace_id
                WHERE p.tenant_id=%s AND p.workspace_id=%s AND p.organization_id=%s AND p.legal_entity_id=%s AND e.posting_date<=%s
                ORDER BY p.id LIMIT %s""",
                (self.tenant_id, workspace_id, scope["organization_id"], scope["legal_entity_id"], cutoff, MAX_BALANCE_EFFECTS + 1),
            ))
            if len(rows) > MAX_BALANCE_EFFECTS:
                raise FinancePostingError("posting_balance_limit", "The bounded balance report exceeds its effect limit.")
            for row in rows:
                balance_window(str(row["start_date"]), str(row["end_date"]), str(row["posting_date"]))
            return build_posted_balances(
                workspace_id=workspace_id, organization_code=organization_code, entity_code=entity_code,
                organization_id=scope["organization_id"], legal_entity_id=scope["legal_entity_id"], period_id=period_id,
                period_start=start, period_end=end, as_of_date=cutoff,
                effects=collect_balance_effects(self._get_effect(row["id"]) for row in rows),
            )

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
            workspace_id = self.finance._required_workspace_id(workspace)
            rows = records(
                self.connection.execute(
                    """SELECT p.id FROM reconforge.finance_posting_effects p JOIN reconforge.finance_entries e
             ON e.tenant_id=p.tenant_id AND e.id=p.entry_id WHERE p.tenant_id=%s AND p.workspace_id=%s
             AND e.organization_code=%s AND e.entity_code=%s AND e.period_id=%s ORDER BY p.id""",
                    (self.tenant_id, workspace_id, organization_code, entity_code, period_id),
                )
            )
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
                if policy is not None and policy != selected:
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
            debit, credit = (
                sum(a["debit_minor"] for a in accounts.values()),
                sum(a["credit_minor"] for a in accounts.values()),
            )
            for account in accounts.values():
                account["debit_balance_minor"] = max(account["balance_minor"], 0)
                account["credit_balance_minor"] = max(-account["balance_minor"], 0)
            debit_balance = sum(a["debit_balance_minor"] for a in accounts.values())
            credit_balance = sum(a["credit_balance_minor"] for a in accounts.values())
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
