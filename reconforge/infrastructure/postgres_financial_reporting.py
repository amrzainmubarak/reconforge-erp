"""Scoped classified reporting and an owner-bound opening journal on the native ledger."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from uuid import uuid4

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.financial_reporting import (
    AccountClassification,
    OpeningPreparation,
    ReportingScope,
    build_financial_report,
    fail,
    validate_mapping_accounts,
)
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import (
    PostgresFinancePostingRepository,
    posting_entry,
    posting_snapshot,
    records,
)
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import current_server_principal
from reconforge.utils.time import utc_now_text


class _OpeningPostingParticipant:
    """Admission exists only while the exact source owner composes its native effect."""

    def __init__(self, owner: PostgresFinancialReportingRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (
            self.owner._participant is self
            and self.owner.connection is connection
            and self.owner.tenant_id == tenant_id
            and self.entry_id == entry_id
        )


class PostgresFinancialReportingRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, validate_tenant_id(tenant_id)
        self.finance = PostgresFinanceCoreRepository(connection, tenant_id)
        self.posting = PostgresFinancePostingRepository(connection, tenant_id)
        self._participant: _OpeningPostingParticipant | None = None

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        try:
            with self.connection.transaction():
                ensure_repository_tenant_scope(self.connection, self.tenant_id)
                if (
                    write
                    and records(self.connection.execute("SHOW transaction_isolation"))[0]["transaction_isolation"]
                    != "read committed"
                ):
                    fail(
                        "Opening and mapping commands require READ COMMITTED.", "financial_reporting_isolation_required"
                    )
                yield
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise FinancePostingError(
                    "financial_reporting_state_conflict",
                    "Reporting source conflicts with retained state; reload the exact source.",
                ) from exc
            raise

    def _actor(self, actor: PostingActor, permission: str, scope: Mapping[str, Any], *, mutation: bool = True) -> None:
        actor.require(permission, mutation=mutation)
        principal = current_server_principal()
        if (
            principal is None
            or principal.user.id != actor.user_id
            or principal.user.username != actor.username
            or principal.user.disabled
            or principal.principal_type != "user"
        ):
            fail("A current bound human identity is required.", "financial_reporting_actor_denied")
        amount = (
            Decimal(exact_minor_text(scope["amount_minor"], scope["currency_precision"]))
            if "amount_minor" in scope
            else None
        )
        persisted = PostgresIdentityRepository(self.connection).user_permissions(
            tenant_id=self.tenant_id, user_id=actor.user_id
        )
        if (
            permission not in principal.permissions
            or permission not in persisted
            or (mutation and not principal.step_up_active)
        ):
            fail(
                "Current persisted permission and recent reauthentication are required.",
                "financial_reporting_actor_denied",
            )
        if not evaluate_principal_access(
            principal,
            required_permission=permission,
            tenant_id=self.tenant_id,
            workspace_id=scope["workspace_id"],
            organization_id=scope["organization_id"],
            entity_id=scope["legal_entity_id"],
            amount=amount,
            authorized_tenant_ids=principal.authorized_tenant_ids or frozenset({self.tenant_id}),
            authorized_workspace_ids=principal.authorized_workspace_ids or frozenset({scope["workspace_id"]}),
            authorized_organization_ids=principal.authorized_organization_ids or frozenset({scope["organization_id"]}),
            authorized_entity_ids=principal.authorized_legal_entity_ids or frozenset({scope["legal_entity_id"]}),
        ).allowed:
            fail("Central authorization denied the reporting hierarchy or amount.", "financial_reporting_scope_denied")
        if (
            self.connection.execute(
                "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND username=%s AND NOT disabled FOR SHARE",
                (self.tenant_id, actor.user_id, actor.username),
            ).fetchone()
            is None
        ):
            fail("Persisted actor is absent or disabled.", "financial_reporting_actor_denied")
        if not records(
            self.connection.execute(
                "SELECT reconforge.irp_scope(%s,%s,%s,%s) AS allowed",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"]),
            )
        )[0]["allowed"]:
            fail("Reporting scope is outside the established execution boundary.", "financial_reporting_scope_denied")

    def _event(
        self, value: Mapping[str, Any], action: str, actor: PostingActor, metadata: dict[str, Any]
    ) -> tuple[str, str]:
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_user_id=actor.user_id,
            actor_label=actor.username,
            object_type="financial_reporting",
            object_id=value["id"],
            action=action,
            metadata=metadata,
        )
        outbox = "OBX-" + uuid4().hex
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
            VALUES(%s,%s,%s,'financial_reporting',%s,%s,%s,%s,%s::jsonb)""",
            (
                self.tenant_id,
                outbox,
                action,
                value["id"],
                value["workspace_id"],
                value["organization_id"],
                value["legal_entity_id"],
                canonical_json({**metadata, "audit_event_id": audit.id}),
            ),
        )
        return audit.id, outbox

    def _command(
        self, scope: Mapping[str, Any], command_id: str, operation: str, actor: PostingActor, request: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(envelope)
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "financial_reporting", command_id]),),
        )
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_reporting_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                (self.tenant_id, scope["workspace_id"], command_id),
            )
        )
        if not rows:
            return envelope, None
        row = rows[0]
        if (row["actor_id"], row["operation"], row["request_digest"]) != (actor.user_id, operation, digest) or row[
            "request_json"
        ] != envelope:
            fail("Command key already binds another actor or exact request.", "financial_reporting_command_conflict")
        if operation in {"prepare_map", "review_map"}:
            self._map(row["object_id"])
        else:
            self._opening(row["object_id"])
        return envelope, row["result_json"]

    def _remember(
        self, value: Mapping[str, Any], command_id: str, envelope: dict[str, Any], result: dict[str, Any]
    ) -> None:
        self.connection.execute(
            """INSERT INTO reconforge.financial_reporting_commands(tenant_id,workspace_id,command_id,operation,actor_id,request_digest,request_json,object_id,result_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""",
            (
                self.tenant_id,
                value["workspace_id"],
                command_id,
                envelope["operation"],
                envelope["actor_id"],
                digest_payload(envelope),
                canonical_json(envelope),
                value["id"],
                canonical_json(result),
            ),
        )

    def _map(self, map_id: str) -> dict[str, Any]:
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_reporting_maps WHERE tenant_id=%s AND id=%s FOR SHARE",
                (self.tenant_id, text(map_id, "map_id")),
            )
        )
        if not rows:
            fail("Reporting map is absent or outside scope.", "financial_reporting_not_found")
        row = rows[0]
        if digest_payload(row["payload"]) != row["map_digest"]:
            fail(
                "Reporting classification digest differs from retained content.",
                "financial_reporting_integrity_invalid",
            )
        validate_mapping_accounts(row["payload"]["accounts"])
        review = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=%s AND map_id=%s",
                (self.tenant_id, map_id),
            )
        )
        return {
            **row["payload"],
            "map_digest": row["map_digest"],
            "status": "Reviewed" if review else "Draft",
            "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
            "review_digest": review[0]["review_digest"] if review else None,
        }

    def prepare_map(
        self,
        scope: ReportingScope,
        *,
        name: str,
        accounts: Sequence[AccountClassification],
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            **scope.payload(),
            "name": text(name, "name", maximum=160),
            "accounts": sorted([account.payload() for account in accounts], key=lambda row: row["account_code"]),
        }
        if not 1 <= len(accounts) <= 1000 or len({row["account_code"] for row in arguments["accounts"]}) != len(
            accounts
        ):
            fail("Reporting map must contain unique bounded account codes.")
        with self._transaction(write=True):
            self._actor(actor, "finance_core.manage", arguments)
            envelope, replay = self._command(arguments, command_id, "prepare_map", actor, arguments)
            if replay is not None:
                return replay
            retained = []
            for account in arguments["accounts"]:
                rows = records(
                    self.connection.execute(
                        "SELECT id,account_code,name,account_type,normal_balance FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND account_code=%s FOR SHARE",
                        (self.tenant_id, scope.workspace_id, account["account_code"]),
                    )
                )
                if len(rows) != 1:
                    fail("Mapped account must identify one native workspace account.")
                row = rows[0]
                retained.append(
                    {
                        **account,
                        "account_id": row["id"],
                        "account_name": row["name"],
                        "account_type": row["account_type"],
                        "normal_balance": row["normal_balance"],
                    }
                )
            validate_mapping_accounts(retained)
            payload = {
                "contract_version": "financial-reporting-map-v1",
                "id": "FRM1-" + digest_payload([self.tenant_id, scope.payload(), command_id])[:32],
                **scope.payload(),
                "name": arguments["name"],
                "accounts": retained,
                "preparer_actor_id": actor.user_id,
            }
            digest = digest_payload(payload)
            audit, outbox = self._event(payload, "financial_reporting_map_prepared", actor, {"map_digest": digest})
            self.connection.execute(
                """INSERT INTO reconforge.financial_reporting_maps(tenant_id,id,workspace_id,organization_id,legal_entity_id,preparer_actor_id,map_digest,payload,audit_event_id,outbox_event_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (
                    self.tenant_id,
                    payload["id"],
                    scope.workspace_id,
                    scope.organization_id,
                    scope.legal_entity_id,
                    actor.user_id,
                    digest,
                    canonical_json(payload),
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._map(payload["id"])
            self._remember(result, command_id, envelope, result)
            return result

    def get_map(self, map_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            result = self._map(map_id)
            self._actor(actor, "finance_core.read", result, mutation=False)
            return result

    def list_maps(self, scope: ReportingScope, *, actor: PostingActor) -> list[dict[str, Any]]:
        with self._transaction():
            self._actor(actor, "finance_core.read", scope.payload(), mutation=False)
            rows = records(
                self.connection.execute(
                    "SELECT id FROM reconforge.financial_reporting_maps WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY created_at DESC,id LIMIT 50",
                    (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id),
                )
            )
            return [self._map(row["id"]) for row in rows]

    def review_map(
        self, map_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction(write=True):
            result = self._map(map_id)
            self._actor(actor, "finance_core.validate", result)
            envelope, replay = self._command(
                result,
                command_id,
                "review_map",
                actor,
                {"map_id": map_id, "expected_digest": expected_digest, "reason": reason},
            )
            if replay is not None:
                return replay
            if (
                result["status"] != "Draft"
                or expected_digest != result["map_digest"]
                or result["preparer_actor_id"] == actor.user_id
            ):
                fail(
                    "Map review requires its current digest and an independent human checker.",
                    "financial_reporting_review_invalid",
                )
            digest = digest_payload(
                {"map_id": map_id, "map_digest": expected_digest, "reviewer_actor_id": actor.user_id, "reason": reason}
            )
            audit, outbox = self._event(
                result,
                "financial_reporting_map_reviewed",
                actor,
                {"map_digest": expected_digest, "review_digest": digest},
            )
            self.connection.execute(
                """INSERT INTO reconforge.financial_reporting_map_reviews(tenant_id,map_id,reviewer_actor_id,map_digest,review_digest,reason,audit_event_id,outbox_event_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, map_id, actor.user_id, expected_digest, digest, reason, audit, outbox, utc_now_text()),
            )
            result = self._map(map_id)
            self._remember(result, command_id, envelope, result)
            return result

    def _opening(self, opening_id: str) -> dict[str, Any]:
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_opening_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, text(opening_id, "opening_id")),
            )
        )
        if not rows:
            fail("Opening source is absent or outside scope.", "financial_reporting_not_found")
        row = rows[0]
        if (
            digest_payload(row["payload"]) != row["plan_digest"]
            or validation_digest(row["payload"]["snapshot"]) != row["validation_digest"]
        ):
            fail("Opening source evidence differs from its retained digests.", "financial_reporting_integrity_invalid")
        review = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_opening_reviews WHERE tenant_id=%s AND plan_id=%s",
                (self.tenant_id, opening_id),
            )
        )
        link = records(
            self.connection.execute(
                "SELECT * FROM reconforge.financial_opening_links WHERE tenant_id=%s AND plan_id=%s",
                (self.tenant_id, opening_id),
            )
        )
        return {
            **row["payload"],
            "plan_digest": row["plan_digest"],
            "validation_digest": row["validation_digest"],
            "status": "Posted" if link else "Reviewed" if review else "Draft",
            "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
            "review_digest": review[0]["review_digest"] if review else None,
            "posting_effect_id": link[0]["posting_effect_id"] if link else None,
        }

    def get_opening(self, opening_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            result = self._opening(opening_id)
            self._actor(actor, "finance_core.read", result, mutation=False)
            return result

    def prepare_opening(self, request: OpeningPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        arguments = request.payload()
        with self._transaction(write=True):
            self._actor(actor, "finance_core.manage", arguments)
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (
                    canonical_json(
                        [self.tenant_id, request.scope.workspace_id, request.scope.legal_entity_id, "financial_opening"]
                    ),
                ),
            )
            envelope, replay = self._command(arguments, command_id, "prepare_opening", actor, arguments)
            if replay is not None:
                self._actor(actor, "finance_core.manage", replay)
                return replay
            mapping = self._map(request.map_id)
            if mapping["status"] != "Reviewed" or any(
                mapping[key] != arguments[key] for key in ("workspace_id", "organization_id", "legal_entity_id")
            ):
                fail("Opening requires an independently reviewed map in the exact entity.")
            known = {row["account_code"]: row for row in mapping["accounts"]}
            if any(
                line["account_code"] not in known
                or known[line["account_code"]]["account_type"] not in {"Asset", "Liability", "Equity"}
                for line in arguments["lines"]
            ):
                fail("Opening balances require explicitly mapped balance-sheet accounts.")
            if self.connection.execute(
                "SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s LIMIT 1",
                (
                    self.tenant_id,
                    request.scope.workspace_id,
                    request.scope.organization_id,
                    request.scope.legal_entity_id,
                ),
            ).fetchone():
                fail(
                    "Opening must precede the entity's retained financial posting history.",
                    "financial_reporting_opening_conflict",
                )
            # Native draft money parsing and currency policy capture remain authoritative.
            periods = records(
                self.connection.execute(
                    "SELECT start_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s AND status='Open' FOR SHARE",
                    (self.tenant_id, request.period_id, request.scope.workspace_id),
                )
            )
            if not periods or str(periods[0]["start_date"]) != request.posting_date:
                fail("Opening date must be the first business date of an open scoped period.")
            currencies = records(
                self.connection.execute(
                    "SELECT c.minor_units FROM reconforge.legal_entities e JOIN reconforge.currencies c ON c.tenant_id=e.tenant_id AND c.code=e.currency_code AND c.active WHERE e.tenant_id=%s AND e.id=%s FOR SHARE OF e,c",
                    (self.tenant_id, request.scope.legal_entity_id),
                )
            )
            if not currencies:
                fail("Opening requires the entity's active functional currency.")
            precision = currencies[0]["minor_units"]
            number = "OB1-" + digest_payload([self.tenant_id, request.scope.payload()])[:32].upper()
            entry = self.finance.create_entry(
                entry_number=number,
                organization_code=request.organization_code,
                entity_code=request.entity_code,
                period_id=request.period_id,
                journal_code=request.journal_code,
                posting_date=request.posting_date,
                description=request.reason,
                lines=[
                    {
                        "account_code": line["account_code"],
                        "debit": exact_minor_text(line["debit_minor"], precision) if line["debit_minor"] else "0",
                        "credit": exact_minor_text(line["credit_minor"], precision) if line["credit_minor"] else "0",
                        "description": request.reason,
                    }
                    for line in arguments["lines"]
                ],
                workspace=request.scope.workspace_id,
                external_reference=number,
                source_type="Manual",
                actor_label=actor.username,
            )
            snapshot = posting_snapshot(
                self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"])
            )
            amount = sum(line["debit_minor"] for line in snapshot["lines"])
            self._actor(
                actor, "finance_core.manage", {**arguments, "amount_minor": amount, "currency_precision": precision}
            )
            payload = {
                "contract_version": "financial-opening-v1",
                "id": number,
                "entry_id": entry["id"],
                **arguments,
                "amount_minor": amount,
                "currency_code": snapshot["entry"]["currency_code"],
                "currency_precision": precision,
                "map_digest": mapping["map_digest"],
                "preparer_actor_id": actor.user_id,
                "snapshot": snapshot,
            }
            digest, seal = digest_payload(payload), validation_digest(snapshot)
            audit, outbox = self._event(
                payload, "financial_opening_prepared", actor, {"plan_digest": digest, "validation_digest": seal}
            )
            self.connection.execute(
                """INSERT INTO reconforge.financial_opening_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id,map_id,entry_id,preparer_actor_id,plan_digest,validation_digest,payload,audit_event_id,outbox_event_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (
                    self.tenant_id,
                    number,
                    request.scope.workspace_id,
                    request.scope.organization_id,
                    request.scope.legal_entity_id,
                    request.map_id,
                    entry["id"],
                    actor.user_id,
                    digest,
                    seal,
                    canonical_json(payload),
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._opening(number)
            self._remember(result, command_id, envelope, result)
            return result

    def review_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction(write=True):
            result = self._opening(opening_id)
            self._actor(actor, "finance_core.validate", result)
            envelope, replay = self._command(
                result,
                command_id,
                "review_opening",
                actor,
                {"opening_id": opening_id, "expected_digest": expected_digest, "reason": reason},
            )
            if replay is not None:
                return replay
            if (
                result["status"] != "Draft"
                or expected_digest != result["plan_digest"]
                or result["preparer_actor_id"] == actor.user_id
            ):
                fail(
                    "Opening review requires exact current content and an independent checker.",
                    "financial_reporting_review_invalid",
                )
            self.finance.validate_entry(result["entry_id"], reason=reason, actor_label=actor.username)
            seal = digest_payload(
                {
                    "opening_id": opening_id,
                    "plan_digest": expected_digest,
                    "reviewer_actor_id": actor.user_id,
                    "reason": reason,
                }
            )
            audit, outbox = self._event(
                result, "financial_opening_reviewed", actor, {"plan_digest": expected_digest, "review_digest": seal}
            )
            self.connection.execute(
                """INSERT INTO reconforge.financial_opening_reviews(tenant_id,plan_id,reviewer_actor_id,plan_digest,review_digest,reason,audit_event_id,outbox_event_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    opening_id,
                    actor.user_id,
                    expected_digest,
                    seal,
                    reason,
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._opening(opening_id)
            self._remember(result, command_id, envelope, result)
            return result

    def post_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction(write=True):
            result = self._opening(opening_id)
            self._actor(actor, "finance_core.post", result)
            envelope, replay = self._command(
                result,
                command_id,
                "post_opening",
                actor,
                {"opening_id": opening_id, "expected_digest": expected_digest, "reason": reason},
            )
            if replay is not None:
                return replay
            if (
                result["status"] != "Reviewed"
                or expected_digest != result["plan_digest"]
                or actor.user_id in {result["preparer_actor_id"], result["reviewer_actor_id"]}
            ):
                fail(
                    "Opening posting requires a third authorized human and the exact reviewed source.",
                    "financial_reporting_review_invalid",
                )
            self._participant = _OpeningPostingParticipant(self, result["entry_id"])
            try:
                effect = self.posting.post(
                    result["entry_id"],
                    command_id="OB1:" + command_id,
                    expected_validation_digest=result["validation_digest"],
                    reason=reason,
                    actor=actor,
                    _source_owner=self._participant,
                )
            finally:
                self._participant = None
            audit, outbox = self._event(
                result,
                "financial_opening_posted",
                actor,
                {
                    "plan_digest": expected_digest,
                    "review_digest": result["review_digest"],
                    "posting_effect_id": effect["id"],
                },
            )
            self.connection.execute(
                """INSERT INTO reconforge.financial_opening_links(tenant_id,plan_id,posting_effect_id,posted_actor_id,plan_digest,review_digest,reason,audit_event_id,outbox_event_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    opening_id,
                    effect["id"],
                    actor.user_id,
                    expected_digest,
                    result["review_digest"],
                    reason,
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._opening(opening_id)
            self._remember(result, command_id, envelope, result)
            return result

    def report(
        self,
        *,
        map_id: str,
        period_id: str,
        as_of_date: str,
        organization_code: str,
        entity_code: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        with self._transaction():
            mapping = self._map(map_id)
            self._actor(actor, "finance_core.read", mapping, mutation=False)
            if mapping["status"] != "Reviewed":
                fail("Financial statements require an independently reviewed classification map.")
            balances = self.posting.posted_balances_as_of(
                period_id=period_id,
                as_of_date=as_of_date,
                organization_code=organization_code,
                entity_code=entity_code,
                workspace=mapping["workspace_id"],
                actor=actor,
            )
            result = build_financial_report(balances, mapping)
            self._actor(actor, "finance_core.read", result, mutation=False)
            return result

    def list_openings(self, scope: ReportingScope, *, actor: PostingActor) -> list[dict[str, Any]]:
        with self._transaction():
            self._actor(actor, "finance_core.read", scope.payload(), mutation=False)
            rows = records(
                self.connection.execute(
                    "SELECT id FROM reconforge.financial_opening_plans WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s",
                    (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id),
                )
            )
            return [self._opening(row["id"]) for row in rows]

    def catalog(self, scope: ReportingScope, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            self._actor(actor, "finance_core.read", scope.payload(), mutation=False)
            accounts = records(
                self.connection.execute(
                    "SELECT id AS account_id,account_code,name AS account_name,account_type,normal_balance FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND active AND allow_posting ORDER BY account_code,id LIMIT 1001",
                    (self.tenant_id, scope.workspace_id),
                )
            )
            if len(accounts) > 1000:
                fail("Account catalog exceeds the bounded statement classification budget.")
            periods = records(
                self.connection.execute(
                    "SELECT id,name,start_date::text,end_date::text,status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s ORDER BY start_date,id LIMIT 200",
                    (self.tenant_id, scope.workspace_id),
                )
            )
            journals = records(
                self.connection.execute(
                    "SELECT journal_code,name,currency_code FROM reconforge.finance_journals WHERE tenant_id=%s AND workspace_id=%s AND active ORDER BY journal_code LIMIT 200",
                    (self.tenant_id, scope.workspace_id),
                )
            )
            return {**scope.payload(), "accounts": accounts, "periods": periods, "journals": journals}
