"""Reviewed native source posting participants on one caller-owned transaction."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, NoReturn
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
from reconforge.domain.operational_finance import SOURCE_PERMISSIONS, OperationalFinancePreparation, exact_minor_text
from reconforge.domain.payables_payment_link import payment_external_reference
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


def _fail(message: str, code: str = "operational_source_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


class _OperationalPostingParticipant:
    """Unexported, exact connection/plan owner; never a general source bypass."""

    def __init__(self, owner: PostgresOperationalFinanceRepository, entry_id: str) -> None:
        self.owner = owner
        self.entry_id = entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (
            self.owner._participant is self
            and self.owner.connection is connection
            and self.owner.tenant_id == tenant_id
            and self.entry_id == entry_id
        )


class PostgresOperationalFinanceRepository:
    """Exact native AR/AP sources; outer service owns all participant effects.

    Standalone prepare/review commands may commit their own complete phase.
    Payments and collections must be composed in an enclosing transaction with
    the actual AP link / AR receipt. Deferred guards reject incomplete effects.
    """

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.finance = PostgresFinanceCoreRepository(connection, tenant_id)
        self.posting = PostgresFinancePostingRepository(connection, tenant_id)
        self._participant: _OperationalPostingParticipant | None = None
        self._requests: dict[tuple[str, str], dict[str, Any]] = {}

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                ensure_repository_tenant_scope(self.connection, self.tenant_id)
                if (
                    records(self.connection.execute("SHOW transaction_isolation"))[0]["transaction_isolation"]
                    != "read committed"
                ):
                    _fail("Operational finance requires READ COMMITTED.", "operational_isolation_required")
                yield
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise FinancePostingError(
                    "operational_state_conflict",
                    "Source conflicts with retained financial state; reload before retrying.",
                ) from exc
            raise

    def _actor(
        self,
        actor: PostingActor,
        permission: str,
        scope: Mapping[str, Any],
        *,
        mutation: bool = True,
        source: bool = False,
    ) -> None:
        principal = current_server_principal()
        permissions = {permission}
        if source:
            permissions.add(SOURCE_PERMISSIONS[str(scope["source_kind"])])
        if (
            principal is None
            or principal.user.id != actor.user_id
            or principal.user.username != actor.username
            or principal.user.disabled
        ):
            _fail("A current bound human identity is required.", "operational_actor_denied")
        for required in permissions:
            actor.require(required, mutation=mutation)
            if (
                required not in principal.permissions
                or required
                not in PostgresIdentityRepository(self.connection).user_permissions(
                    tenant_id=self.tenant_id, user_id=actor.user_id
                )
                or not evaluate_principal_access(principal, required_permission=required).allowed
            ):
                _fail("Central authorization denied this source command.", "operational_actor_denied")
        if principal.principal_type != "user" or (mutation and not principal.step_up_active):
            _fail("Recent human reauthentication is required.", "operational_actor_denied")
        for field, grants in (
            ("tenant_id", principal.authorized_tenant_ids),
            ("workspace_id", principal.authorized_workspace_ids),
            ("organization_id", principal.authorized_organization_ids),
            ("legal_entity_id", principal.authorized_legal_entity_ids),
        ):
            value = self.tenant_id if field == "tenant_id" else scope[field]
            if grants and value not in grants:
                _fail("Source is outside current authority.", "operational_scope_denied")
        if (
            self.connection.execute(
                "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND username=%s AND NOT disabled FOR SHARE",
                (self.tenant_id, actor.user_id, actor.username),
            ).fetchone()
            is None
        ):
            _fail("Persisted human identity is disabled or absent.", "operational_actor_denied")
        if not records(
            self.connection.execute(
                "SELECT reconforge.irp_scope(%s,%s,%s,%s) AS allowed",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"]),
            )
        )[0]["allowed"]:
            _fail("Canonical source hierarchy is unauthorized.", "operational_scope_denied")

    def _source(self, kind: str, source_id: str, *, final: bool = False, settlement: bool = False) -> dict[str, Any]:
        # The closed source kind selects an internal constant, never SQL input.
        table = "ar_invoices" if kind in {"ARInvoice", "ARReceipt"} else "ap_supplier_invoices"
        rows = records(
            self.connection.execute(
                f"SELECT status FROM reconforge.{table} WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, source_id),
            )
        )
        if not rows:
            _fail("Native source is absent or outside scope.", "operational_source_not_found")
        states = {"Approved", "PartiallyPaid", "Paid"} if table == "ar_invoices" else {"Approved", "Paid"}
        if not final and kind == "ARInvoice":
            states |= {"Submitted"}
        if rows[0]["status"] not in states:
            _fail("A submitted/approved native source is required.", "operational_source_state_invalid")
        source = records(
            self.connection.execute(
                "SELECT reconforge.ops_source(%s,%s,%s) AS payload", (self.tenant_id, kind, source_id)
            )
        )[0]["payload"]
        if (
            not isinstance(source, dict)
            or type(source.get("amount_minor")) is not int
            or source["amount_minor"] <= 0
            or source["tax_minor"] != 0
        ):
            _fail("This source contract requires positive exact functional-currency money and zero tax.")
        if len(source.get("lines") or []) > 64:
            _fail("This source contract admits at most 64 retained invoice lines.")
        if (
            kind == "ARReceipt"
            and not settlement
            and self.connection.execute(
                "SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND invoice_id=%s",
                (self.tenant_id, source_id),
            ).fetchone()
        ):
            _fail("This collection contract requires a wholly unpaid invoice.", "operational_source_changed")
        if (
            kind == "APPayment"
            and not settlement
            and self.connection.execute(
                "SELECT 1 FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s",
                (self.tenant_id, source_id),
            ).fetchone()
        ):
            _fail("This payment contract requires a wholly unpaid invoice.", "operational_source_changed")
        return source

    def _event(
        self, plan: Mapping[str, Any], action: str, actor: PostingActor, metadata: dict[str, Any]
    ) -> tuple[str, str]:
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_user_id=actor.user_id,
            actor_label=actor.username,
            object_type="operational_finance",
            object_id=plan["id"],
            action=action,
            metadata=metadata,
        )
        outbox = "OBX-" + uuid4().hex
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
        VALUES(%s,%s,%s,'operational_finance',%s,%s,%s,%s,%s::jsonb)""",
            (
                self.tenant_id,
                outbox,
                action,
                plan["id"],
                plan["workspace_id"],
                plan["organization_id"],
                plan["legal_entity_id"],
                canonical_json({**metadata, "audit_event_id": audit.id}),
            ),
        )
        return audit.id, outbox

    def _command(
        self, scope: Mapping[str, Any], command_id: str, operation: str, actor: PostingActor, request: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        envelope = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        self._requests[(operation, command_id)] = envelope
        digest = digest_payload(envelope)
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "operational_finance", command_id]),),
        )
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.operational_finance_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                (self.tenant_id, scope["workspace_id"], command_id),
            )
        )
        if rows:
            retained = rows[0]
            if (retained["actor_id"], retained["operation"], retained["request_digest"]) != (
                actor.user_id,
                operation,
                digest,
            ):
                _fail("Command key already binds another actor or content.", "operational_command_conflict")
            self._get(retained["plan_id"])
            return digest, retained["result_json"]
        return digest, None

    def _remember(
        self,
        plan: Mapping[str, Any],
        command_id: str,
        operation: str,
        actor: PostingActor,
        digest: str,
        result: dict[str, Any],
    ) -> None:
        self.connection.execute(
            """INSERT INTO reconforge.operational_finance_commands(tenant_id,workspace_id,command_id,operation,actor_id,request_digest,request_json,plan_id,result_json)
        VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)""",
            (
                self.tenant_id,
                plan["workspace_id"],
                command_id,
                operation,
                actor.user_id,
                digest,
                canonical_json(self._requests.pop((operation, command_id))),
                plan["id"],
                canonical_json(result),
            ),
        )

    def _get(self, plan_id: str) -> dict[str, Any]:
        rows = records(
            self.connection.execute(
                "SELECT * FROM reconforge.operational_finance_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, text(plan_id, "plan_id")),
            )
        )
        if not rows:
            _fail("Source plan is absent or outside scope.", "operational_source_not_found")
        row = rows[0]
        payload = row["payload"]
        if (
            digest_payload(payload) != row["plan_digest"]
            or validation_digest(payload["snapshot"]) != row["validation_digest"]
        ):
            _fail("Retained operational evidence failed verification.", "operational_evidence_invalid")
        review = records(
            self.connection.execute(
                "SELECT reviewer_actor_id,review_digest FROM reconforge.operational_finance_reviews WHERE tenant_id=%s AND plan_id=%s",
                (self.tenant_id, plan_id),
            )
        )
        link = records(
            self.connection.execute(
                "SELECT posting_effect_id,source_effect_id,posted_actor_id FROM reconforge.operational_finance_links WHERE tenant_id=%s AND plan_id=%s",
                (self.tenant_id, plan_id),
            )
        )
        return {
            **payload,
            "plan_digest": row["plan_digest"],
            "validation_digest": row["validation_digest"],
            "status": "Posted" if link else "Reviewed" if review else "Draft",
            "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
            "review_digest": review[0]["review_digest"] if review else None,
            "posting_effect_id": link[0]["posting_effect_id"] if link else None,
            "source_effect_id": link[0]["source_effect_id"] if link else None,
        }

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self._transaction():
            plan = self._get(plan_id)
            self._actor(actor, "finance_core.read", plan, mutation=False)
            self.connection.execute("SELECT reconforge.ops_close_plan(%s,%s)", (self.tenant_id, plan_id))
            return plan

    def list(
        self, *, workspace_id: str, organization_id: str, legal_entity_id: str, actor: PostingActor, limit: int = 50
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            _fail("Source list is bounded to 100 plans.")
        with self._transaction():
            self._actor(actor, "finance_core.read", locals(), mutation=False)
            rows = records(
                self.connection.execute(
                    "SELECT id FROM reconforge.operational_finance_plans WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY created_at DESC,id LIMIT %s",
                    (self.tenant_id, workspace_id, organization_id, legal_entity_id, limit),
                )
            )
            return [self._get(row["id"]) for row in rows]

    def prepare(
        self, request: OperationalFinancePreparation, *, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        arguments = request.payload()
        with self._transaction():
            self._actor(actor, "finance_core.manage", arguments)
            digest, replay = self._command(arguments, command_id, "prepare", actor, arguments)
            if replay is not None:
                return replay
            source = self._source(request.source_kind, request.source_id)
            if any(source[k] != arguments[k] for k in ("workspace_id", "organization_id", "legal_entity_id")):
                _fail("Native source belongs to another canonical hierarchy.", "operational_scope_denied")
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(%s::text,'currency_registry_binding',%s::text)::text,0))",
                (self.tenant_id, request.workspace_id),
            )
            currency = records(
                self.connection.execute(
                    "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                    (self.tenant_id, source["currency_code"]),
                )
            )
            if len(currency) != 1:
                _fail("Source currency is inactive or absent.")
            precision = currency[0]["minor_units"]
            amount = exact_minor_text(source["amount_minor"], precision)
            plan_id = "OPS1-" + digest_payload([request.workspace_id, request.source_kind, request.source_id])[:32]
            entry_number = plan_id.upper()
            entry = self.finance.create_entry(
                entry_number=entry_number,
                organization_code=request.organization_code,
                entity_code=request.entity_code,
                period_id=request.period_id,
                journal_code=request.journal_code,
                posting_date=request.posting_date,
                description=request.reason,
                lines=[
                    {
                        "account_code": request.debit_account_code,
                        "debit": amount,
                        "credit": "0",
                        "description": request.reason,
                    },
                    {
                        "account_code": request.credit_account_code,
                        "debit": "0",
                        "credit": amount,
                        "description": request.reason,
                    },
                ],
                workspace=request.workspace_id,
                external_reference=payment_external_reference(request.source_id)
                if request.source_kind == "APPayment"
                else plan_id,
                actor_label=actor.username,
            )
            snapshot = posting_snapshot(
                self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"])
            )
            if (
                source["currency_code"] != snapshot["entry"]["currency_code"]
                or source.get("currency_registry_digest", snapshot["entry"]["currency_registry_digest"])
                != snapshot["entry"]["currency_registry_digest"]
            ):
                _fail("Native source and GL must retain the same verified functional currency policy.")
            payload = {
                "schema_version": "operational-finance-v1",
                "id": plan_id,
                "entry_id": entry["id"],
                **arguments,
                "amount_minor": source["amount_minor"],
                "currency_code": source["currency_code"],
                "currency_precision": precision,
                "preparer_actor_id": actor.user_id,
                "source_snapshot": source,
                "snapshot": snapshot,
            }
            seal = digest_payload(payload)
            validation = validation_digest(snapshot)
            audit, outbox = self._event(
                payload, "operational_finance_prepared", actor, {"plan_digest": seal, "validation_digest": validation}
            )
            self.connection.execute(
                """INSERT INTO reconforge.operational_finance_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id,source_kind,source_id,
            entry_id,entry_number,preparer_actor_id,amount_minor,currency_code,currency_precision,plan_digest,validation_digest,payload,audit_event_id,outbox_event_id,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (
                    self.tenant_id,
                    plan_id,
                    request.workspace_id,
                    request.organization_id,
                    request.legal_entity_id,
                    request.source_kind,
                    request.source_id,
                    entry["id"],
                    entry_number,
                    actor.user_id,
                    source["amount_minor"],
                    source["currency_code"],
                    precision,
                    seal,
                    validation,
                    canonical_json(payload),
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._get(plan_id)
            self._remember(result, command_id, "prepare", actor, digest, result)
            return result

    def review(
        self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            plan = self._get(plan_id)
            self._actor(actor, "finance_core.validate", plan)
            digest, replay = self._command(
                plan,
                command_id,
                "review",
                actor,
                {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason},
            )
            if replay is not None:
                return replay
            if (
                expected_plan_digest != plan["plan_digest"]
                or plan["status"] != "Draft"
                or actor.user_id == plan["preparer_actor_id"]
            ):
                _fail("A current source digest and distinct human checker are required.", "operational_review_invalid")
            if self._source(plan["source_kind"], plan["source_id"]) != plan["source_snapshot"]:
                _fail("Source changed after preparation.", "operational_source_changed")
            self.finance.validate_entry(plan["entry_id"], reason=reason, actor_label=actor.username)
            seal = digest_payload(
                {
                    "plan_id": plan_id,
                    "plan_digest": plan["plan_digest"],
                    "reviewer_actor_id": actor.user_id,
                    "reason": reason,
                }
            )
            audit, outbox = self._event(
                plan, "operational_finance_reviewed", actor, {"plan_digest": plan["plan_digest"], "review_digest": seal}
            )
            self.connection.execute(
                "INSERT INTO reconforge.operational_finance_reviews(tenant_id,plan_id,reviewer_actor_id,plan_digest,reason,review_digest,audit_event_id,outbox_event_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    plan_id,
                    actor.user_id,
                    plan["plan_digest"],
                    reason,
                    seal,
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._get(plan_id)
            self._remember(result, command_id, "review", actor, digest, result)
            return result

    def post(
        self,
        plan_id: str,
        *,
        expected_plan_digest: str,
        command_id: str,
        reason: str,
        actor: PostingActor,
        source_effect_id: str | None = None,
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        with self._transaction():
            plan = self._get(plan_id)
            self._actor(actor, "finance_core.post", plan, source=True)
            digest, replay = self._command(
                plan,
                command_id,
                "post",
                actor,
                {
                    "plan_id": plan_id,
                    "expected_plan_digest": expected_plan_digest,
                    "reason": reason,
                    "source_effect_id": source_effect_id,
                },
            )
            if replay is not None:
                return replay
            if (
                expected_plan_digest != plan["plan_digest"]
                or plan["status"] != "Reviewed"
                or actor.user_id == plan["preparer_actor_id"]
            ):
                _fail("A current independently reviewed source is required.", "operational_review_invalid")
            source = self._source(
                plan["source_kind"], plan["source_id"], final=True, settlement=plan["source_kind"] == "ARReceipt"
            )
            if source != plan["source_snapshot"]:
                _fail("Native source changed after independent review.", "operational_source_changed")
            if plan["source_kind"] == "ARReceipt" and source_effect_id is None:
                _fail("Collection must bind its real native receipt.")
            self._participant = _OperationalPostingParticipant(self, plan["entry_id"])
            try:
                effect = self.posting.post(
                    plan["entry_id"],
                    command_id="OPS1:" + command_id,
                    expected_validation_digest=plan["validation_digest"],
                    reason=reason,
                    actor=actor,
                    _source_owner=self._participant,
                )
            finally:
                self._participant = None
            native = (
                effect["id"]
                if plan["source_kind"] == "APPayment"
                else source_effect_id
                if plan["source_kind"] == "ARReceipt"
                else plan["source_id"]
            )
            audit, outbox = self._event(
                plan,
                "operational_finance_posted",
                actor,
                {
                    "plan_digest": plan["plan_digest"],
                    "review_digest": plan["review_digest"],
                    "posting_effect_id": effect["id"],
                    "source_effect_id": native,
                },
            )
            self.connection.execute(
                "INSERT INTO reconforge.operational_finance_links(tenant_id,plan_id,posting_effect_id,source_effect_id,posted_actor_id,plan_digest,review_digest,audit_event_id,outbox_event_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    plan_id,
                    effect["id"],
                    native,
                    actor.user_id,
                    plan["plan_digest"],
                    plan["review_digest"],
                    audit,
                    outbox,
                    utc_now_text(),
                ),
            )
            result = self._get(plan_id)
            self._remember(result, command_id, "post", actor, digest, result)
            return result
