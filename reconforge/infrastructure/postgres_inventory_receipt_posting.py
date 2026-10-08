"""Atomic, source-reviewed Inventory receipt posting on one scoped connection."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, cast
from uuid import uuid4

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import (
    COMMIT_PERMISSIONS,
    PREPARE_PERMISSIONS,
    READ_PERMISSIONS,
    REVIEW_PERMISSIONS,
    InventoryReceiptPostingError,
    ReceiptEffect,
    ReceiptPlan,
    ReceiptPlanView,
    ReceiptPreparation,
    ReceiptReversalPreparation,
    ReceiptReview,
    exact_date,
    exact_int,
    exact_text,
    fail,
    make_effect,
    make_plan,
    make_review,
    source_plan_id,
    verify_effect,
    verify_inverse,
    verify_plan,
    verify_review,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import (
    PostgresFinancePostingRepository,
    posting_entry,
    posting_snapshot,
    records,
)
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.io.inventory_receipt_posting import decode_receipt_json, encode_receipt_json
from reconforge.platform.common import current_server_principal
from reconforge.platform.inventory_values import code, document_number, quantity_to_scaled, scaled_to_text
from reconforge.utils.time import utc_now_text


class PostgresInventoryReceiptPostingRepository:
    """Own each complete command; internal participants cannot finalize the transaction."""

    def __init__(self, connection: Any, tenant_id: str, *, strict_command_actor: bool = False) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.strict_command_actor = strict_command_actor
        self._active = False
        self._rollback_only = False
        self.inventory = PostgresInventoryCoreRepository(connection, tenant_id)
        self.finance = PostgresFinancePostingRepository(connection, tenant_id)

    @contextmanager
    def _transaction(self, *, write: bool = True) -> Iterator[None]:
        try:
            with self._owned_transaction(write=write):
                yield
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise InventoryReceiptPostingError(
                    "inventory_receipt_state_conflict",
                    "Receipt source conflicts with current retained state; reload its verified result before retrying.",
                ) from exc
            raise

    @contextmanager
    def _owned_transaction(self, *, write: bool = True) -> Iterator[None]:
        if self._active:
            fail("A receipt owner cannot be reentered.", "inventory_receipt_owner_invalid")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            isolation = records(self.connection.execute("SHOW transaction_isolation"))[0]["transaction_isolation"]
            if write and isolation != "read committed":
                fail("Receipt mutations require READ COMMITTED.", "inventory_receipt_isolation_required")
            self._active = True
            self._rollback_only = False
            try:
                yield
                if self._rollback_only:
                    fail("A failed receipt participant requires the complete owner to roll back.", "inventory_receipt_rollback_only")
            finally:
                self._active = False

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if not self._active:
            fail("Receipt participant requires an active exact owner.", "inventory_receipt_owner_invalid")
        try:
            yield
        except BaseException:
            self._rollback_only = True
            raise

    def _actor(self, actor: PostingActor, permissions: frozenset[str], *, mutation: bool = True) -> None:
        principal = current_server_principal()
        if (principal is None or principal.principal_type != "user"
                or principal.user.id != actor.user_id or principal.user.username != actor.username
                or principal.user.disabled or (mutation and not principal.step_up_active)
                or not permissions.issubset(principal.permissions)):
            fail("A current authenticated human with the required authority is required.", "inventory_receipt_actor_denied")
        for permission in permissions:
            actor.require(permission, mutation=mutation)
            if not evaluate_principal_access(principal, required_permission=permission).allowed:
                fail("Central authorization denied this receipt command.", "inventory_receipt_actor_denied")
        if principal.authorized_tenant_ids and self.tenant_id not in principal.authorized_tenant_ids:
            fail("Receipt tenant is outside current authority.", "inventory_receipt_scope_denied")
        row = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND username=%s AND NOT disabled FOR SHARE",
            (self.tenant_id, actor.user_id, actor.username),
        ).fetchone()
        if row is None:
            fail("Receipt actor has no active persisted identity.", "inventory_receipt_actor_denied")

    def _scope(self, scope: Mapping[str, Any]) -> None:
        principal = current_server_principal()
        if principal is None:
            fail("Receipt scope needs a bound principal.")
        for field, grants in (("workspace_id", principal.authorized_workspace_ids),
                              ("organization_id", principal.authorized_organization_ids),
                              ("legal_entity_id", principal.authorized_legal_entity_ids)):
            if grants and scope[field] not in grants:
                fail("Receipt is outside current human scope.", "inventory_receipt_scope_denied")
        row = self.connection.execute(
            """SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e
            ON e.tenant_id=o.tenant_id AND e.organization_id=o.id WHERE o.tenant_id=%s
            AND o.id=%s AND e.id=%s AND o.application_workspace_id=%s
            AND o.organization_code=%s AND e.entity_code=%s""",
            (self.tenant_id, scope["organization_id"], scope["legal_entity_id"], scope["workspace_id"],
             scope["organization_code"], scope["entity_code"]),
        ).fetchone()
        if row is None:
            fail("Receipt canonical hierarchy is absent or unauthorized.", "inventory_receipt_scope_denied")

    def _one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        rows = records(self.connection.execute(query, parameters))
        if len(rows) != 1:
            fail("Receipt backing reference is absent, ambiguous or unauthorized.")
        return rows[0]

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        return decode_receipt_json(value if isinstance(value, str) else encode_receipt_json(value))

    def _insert(self, table: str, values: Mapping[str, Any], *, json_fields: tuple[str, ...] = ()) -> None:
        # Identifiers are solely internal constants; values always use driver parameters.
        from psycopg import sql
        names = list(values)
        statement = sql.SQL("INSERT INTO reconforge.{} ({}) VALUES ({})").format(
            sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, names)),
            sql.SQL(",").join(sql.SQL("%s::jsonb" if key in json_fields else "%s") for key in names),
        )
        self.connection.execute(statement, tuple(encode_receipt_json(values[key]) if key in json_fields else values[key] for key in names))

    def _command(self, scope: Mapping[str, Any], operation: str, command_id: str,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        exact_text(command_id)
        digest = digest_payload({"operation": operation, "scope": dict(scope), "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, scope["workspace_id"], operation, command_id]),))
        rows = records(self.connection.execute(
            """SELECT * FROM reconforge.inventory_receipt_commands WHERE tenant_id=%s
            AND workspace_id=%s AND operation=%s AND command_id=%s""",
            (self.tenant_id, scope["workspace_id"], operation, command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if row["request_digest"] != digest or any(row[k] != scope[k] for k in ("workspace_id", "organization_id", "legal_entity_id")):
            fail("Receipt command already binds different content.", "inventory_receipt_command_conflict")
        if self.strict_command_actor:
            principal = current_server_principal()
            if principal is None or row["actor_user_id"] != principal.user.id:
                fail("Receipt command belongs to another authenticated human.", "inventory_receipt_command_actor_denied")
        return digest, self._json(row["result_json"])

    def _remember(self, plan: ReceiptPlan, operation: str, command_id: str, digest: str,
                  actor: PostingActor, result: Mapping[str, Any]) -> None:
        self._insert("inventory_receipt_commands", {
            "tenant_id": self.tenant_id, **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
            "command_id": command_id, "operation": operation, "request_digest": digest,
            "plan_id": plan["plan_id"], "actor_user_id": actor.user_id, "created_at": utc_now_text(), "result_json": result,
        }, json_fields=("result_json",))

    def _event(self, plan: ReceiptPlan, action: str, actor: PostingActor, metadata: dict[str, Any]) -> tuple[str, str]:
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_user_id=actor.user_id, actor_label=actor.username, object_type="inventory_receipt_posting",
            object_id=plan["plan_id"], action=action, metadata=metadata)
        outbox_id = "OBX-" + uuid4().hex
        self._insert("outbox_events", {"tenant_id": self.tenant_id, "event_id": outbox_id, "event_type": action,
                    "aggregate_type": "inventory_receipt_posting", "aggregate_id": plan["plan_id"],
                    **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
                    "payload": {**metadata, "audit_event_id": audit.id}}, json_fields=("payload",))
        return audit.id, outbox_id

    def _check_event(self, plan: ReceiptPlan, audit_id: str, outbox_id: str, action: str,
                     actor_id: str, metadata: dict[str, Any]) -> None:
        scope = plan["scope"]
        row = self.connection.execute(
            """SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o
            ON o.tenant_id=a.tenant_id WHERE a.tenant_id=%s AND a.id=%s AND o.event_id=%s
            AND a.actor_user_id=%s AND a.object_type='inventory_receipt_posting' AND a.object_id=%s
            AND a.action=%s AND a.metadata_json=%s::jsonb AND o.event_type=%s
            AND o.aggregate_type='inventory_receipt_posting' AND o.aggregate_id=%s AND o.payload=%s::jsonb
            AND o.workspace_id=%s AND o.organization_id=%s AND o.legal_entity_id=%s""",
            (self.tenant_id, audit_id, outbox_id, actor_id, plan["plan_id"], action, canonical_json(metadata),
             action, plan["plan_id"], canonical_json({**metadata, "audit_event_id": audit_id}),
             scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])).fetchone()
        if row is None:
            fail("Receipt evidence does not bind the exact retained source.")

    @staticmethod
    def _metadata(plan: ReceiptPlan, review: ReceiptReview | None = None, *, committed: bool = False) -> dict[str, Any]:
        result = {"plan_digest": plan["plan_digest"], "finance_validation_digest": plan["finance_validation_digest"]}
        if review is not None:
            result["review_digest"] = review["review_digest"]
        if committed:
            result["effect_id"] = cast(str, plan["artifacts"]["posting_effect_id"])
        return result

    @staticmethod
    def _plan_columns(plan: ReceiptPlan) -> dict[str, Any]:
        source, mapping, original = plan["source"], plan["mapping"], plan["original"]
        return {"id": plan["plan_id"], **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
                "source_number": source["number"], "operation": plan["operation"], "plan_version": 1,
                **{k: source[k] for k in ("period_id", "posting_date", "item_id", "uom_id", "location_id", "quantity_scaled", "quantity_precision", "total_value_minor")},
                "preparer_actor_id": plan["preparer"]["user_id"], "preparer_username": plan["preparer"]["username"],
                "prepared_at": plan["prepared_at"], "reason": plan["reason"], **plan["currency_policy"],
                **{k: mapping[k] for k in ("policy_id", "journal_id", "inventory_account_id", "receipt_clearing_account_id")},
                "mapping_digest": plan["mapping_digest"], "original_plan_id": original["plan_id"] if original else None,
                "original_posting_effect_id": original["posting_effect_id"] if original else None, **plan["artifacts"],
                "finance_validation_digest": plan["finance_validation_digest"], "plan_digest": plan["plan_digest"],
                "preparation_audit_event_id": plan["preparation_audit_event_id"], "preparation_outbox_event_id": plan["preparation_outbox_event_id"]}

    def _plan(self, plan_id: str, *, lock: bool = False) -> ReceiptPlan:
        query = "SELECT * FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s AND id=%s"
        if lock:
            query = "SELECT * FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s AND id=%s FOR UPDATE"
        row = self._one(query, (self.tenant_id, exact_text(plan_id)))
        plan = verify_plan(self._json(row["plan_json"]))
        self._scope(plan["scope"])
        for key, expected in self._plan_columns(plan).items():
            actual = row[key]
            if key == "posting_date":
                actual = str(actual)
            if actual != expected:
                fail("Receipt plan scalar and retained evidence disagree.")
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(plan["currency_policy"])
        self._check_event(plan, plan["preparation_audit_event_id"], plan["preparation_outbox_event_id"],
                          "inventory_receipt_prepared", plan["preparer"]["user_id"], self._metadata(plan))
        return plan

    def _review(self, plan: ReceiptPlan, *, required: bool = True) -> ReceiptReview | None:
        rows = records(self.connection.execute("SELECT * FROM reconforge.inventory_receipt_reviews WHERE tenant_id=%s AND plan_id=%s",
                                               (self.tenant_id, plan["plan_id"])))
        if not rows:
            if required:
                fail("Receipt requires an independent persisted review.")
            return None
        row = rows[0]
        review = verify_review(self._json(row["review_json"]), plan)
        expected = {"id": review["review_id"], "reviewer_actor_id": review["reviewer"]["user_id"],
                    "reviewer_username": review["reviewer"]["username"],
                    **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")}, **{k: review[k] for k in (
                        "plan_id", "plan_version", "plan_digest", "finance_validation_digest", "reviewed_at", "reason", "review_digest", "audit_event_id", "outbox_event_id")}}
        if any(row[k] != v for k, v in expected.items()):
            fail("Receipt review scalar and retained evidence disagree.")
        self._check_event(plan, review["audit_event_id"], review["outbox_event_id"], "inventory_receipt_reviewed",
                          review["reviewer"]["user_id"], self._metadata(plan, review))
        return review

    def _period(self, plan: ReceiptPlan) -> None:
        target = plan["source"]["period_id"]
        periods = {target}
        if plan["original"]:
            original = self._plan(plan["original"]["plan_id"])
            periods.add(original["source"]["period_id"])
        for period_id in sorted(periods):
            period = self._one("SELECT status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                               (self.tenant_id, period_id, plan["scope"]["workspace_id"]))
            if period_id == target and (period["status"] != "Open" or not str(period["start_date"]) <= plan["source"]["posting_date"] <= str(period["end_date"])):
                fail("Receipt requires an Open target period containing its business date.")

    def _new_plan(self, request: ReceiptPreparation, actor: PostingActor) -> tuple[dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any]]:
        workspace = self.inventory._workspace_id(request.workspace)
        org = self.inventory._organization(workspace, request.organization_code)
        entity = self.inventory._entity(org["id"], request.entity_code)
        if entity is None:
            fail("Receipt requires a canonical legal entity.")
        scope = {"workspace_id": workspace, "organization_id": org["id"], "legal_entity_id": entity["id"],
                 "organization_code": org["organization_code"], "entity_code": entity["entity_code"]}
        self._scope(scope)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(%s::text,%s::text,%s::text)::text,0))",
                                (self.tenant_id, "currency_registry_bindings", workspace))
        item = self.inventory._item(workspace, request.item_code, active=True)
        if item["item_type"] not in {"Stock", "Consumable"} or item["tracking_mode"] != "None" or not item["uom_active"] or item["organization_id"] not in (None, org["id"]):
            fail("This receipt contract requires an active untracked Stock or Consumable item in its canonical organization.")
        location = self.inventory._location_reference(workspace, org["id"], entity["id"], request.location_code)
        if location is None or location["location_type"] != "Internal" or location["allow_negative"]:
            fail("Receipt requires an active Internal destination that prohibits negative stock.")
        policy = self._one("""SELECT * FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s
          AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s AND active FOR SHARE""",
          (self.tenant_id, workspace, org["id"], entity["id"], code(request.policy_code, "Policy code")))
        mapping = {"policy_id": policy["id"], "costing_method": policy["costing_method"], "currency_code": policy["currency_code"],
                   "journal_id": policy["finance_journal_id"], "inventory_account_id": item["inventory_account_id"],
                   **{k: policy[k] for k in ("receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id")}}
        currency = self._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                             (self.tenant_id, policy["currency_code"]))
        captured, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(
            workspace_id=workspace, currency_code=policy["currency_code"], minor_units=currency["minor_units"], actor_label=actor.username)
        quantity = quantity_to_scaled(request.quantity, item["decimal_places"])
        source = {"number": document_number(request.receipt_number, "Receipt number"), "posting_date": exact_date(request.posting_date),
                  "period_id": exact_text(request.period_id), "item_id": item["id"], "uom_id": item["uom_id"], "location_id": location["id"],
                  "quantity_scaled": quantity, "quantity_precision": item["decimal_places"], "quantity_text": scaled_to_text(quantity, item["decimal_places"]),
                  "total_value_minor": exact_int(request.total_value_minor)}
        return scope, source, mapping, {"currency_code": captured.currency_code, **captured.metadata()}

    def prepare_receipt(self, request: ReceiptPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan:
        with self._transaction():
            self._actor(actor, PREPARE_PERMISSIONS)
            # Resolve scope before key lookup; retries never take authority from cached IDs.
            workspace = self.inventory._workspace_id(request.workspace)
            org = self._one("SELECT id,organization_code FROM reconforge.organizations WHERE tenant_id=%s AND application_workspace_id=%s AND organization_code=%s",
                            (self.tenant_id, workspace, code(request.organization_code, "Organization code")))
            entity = self._one("SELECT id,entity_code FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s",
                               (self.tenant_id, org["id"], code(request.entity_code, "Entity code")))
            scope = {"workspace_id": workspace, "organization_id": org["id"], "legal_entity_id": entity["id"],
                     "organization_code": org["organization_code"], "entity_code": entity["entity_code"]}
            self._scope(scope)
            requested_id = source_plan_id(scope, document_number(request.receipt_number, "Receipt number"))
            existing = self.connection.execute("SELECT 1 FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s AND id=%s", (self.tenant_id, requested_id)).fetchone()
            retained = self._plan(requested_id) if existing else None
            identity = self._preparation_identity(request, scope, retained)
            digest, replay = self._command(scope, "prepare_receipt", command_id, identity)
            if replay is not None:
                plan = self._plan(requested_id)
                if replay != plan or plan["operation"] != "Receipt" or identity != {**plan["source"], "policy_id": plan["mapping"]["policy_id"], "reason": plan["reason"]}:
                    fail("Preparation acknowledgement differs from its requested immutable source.")
                return plan
            scope, source, mapping, policy = self._new_plan(request, actor)
            plan = make_plan(operation="Receipt", scope=scope, source=source, mapping=mapping, currency_policy=policy,
                             actor=actor, prepared_at=utc_now_text(), reason=exact_text(request.reason, maximum=500),
                             audit_event_id="pending", outbox_event_id="pending")
            self._admit(plan)
            self._persist_preparation(plan, actor)
            self._remember(plan, "prepare_receipt", command_id, digest, actor, plan)
            return plan

    def _preparation_identity(self, request: ReceiptPreparation, scope: Mapping[str, str], retained: ReceiptPlan | None) -> dict[str, Any]:
        """Resolve request identity without consulting mutable Active or current registry state."""
        item = self.inventory._item(scope["workspace_id"], request.item_code)
        parts = exact_text(request.location_code, maximum=129).split("/")
        if len(parts) != 2:
            fail("Location references require WAREHOUSE/LOCATION.")
        warehouse = self.inventory._warehouse(scope["workspace_id"], scope["organization_id"], parts[0])
        if warehouse["legal_entity_id"] not in (None, scope["legal_entity_id"]):
            fail("Requested warehouse is outside the source entity.")
        location = self.inventory._location(warehouse["id"], parts[1])
        policy = self._one("SELECT id FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s",
                           (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], code(request.policy_code, "Policy code")))
        precision = retained["source"]["quantity_precision"] if retained else item["decimal_places"]
        quantity = quantity_to_scaled(request.quantity, precision)
        return {"number": document_number(request.receipt_number, "Receipt number"), "posting_date": exact_date(request.posting_date),
                "period_id": exact_text(request.period_id), "item_id": item["id"], "uom_id": item["uom_id"], "location_id": location["id"],
                "quantity_scaled": quantity, "quantity_precision": precision, "quantity_text": scaled_to_text(quantity, precision),
                "total_value_minor": exact_int(request.total_value_minor), "policy_id": policy["id"], "reason": exact_text(request.reason, maximum=500)}

    def _persist_preparation(self, plan: ReceiptPlan, actor: PostingActor) -> None:
        audit, outbox = self._event(plan, "inventory_receipt_prepared", actor, self._metadata(plan))
        plan["preparation_audit_event_id"], plan["preparation_outbox_event_id"] = audit, outbox
        verify_plan(plan)
        self._insert("inventory_receipt_plans", {"tenant_id": self.tenant_id, **self._plan_columns(plan), "plan_json": plan}, json_fields=("plan_json",))

    def _admit(self, plan: ReceiptPlan) -> None:
        """Current mutable references are checked only for a new financial action."""
        scope, source, mapping = plan["scope"], plan["source"], plan["mapping"]
        # Bindings and required dimensions can be newly inserted, so locking
        # existing rows cannot protect absence. Paired mutation triggers acquire
        # these exact workspace keys before changing the respective contents.
        for namespace in ("currency_registry_bindings", "finance_dimensions"):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(%s::text,%s::text,%s::text)::text,0))",
                                    (self.tenant_id, namespace, scope["workspace_id"]))
        self._period(plan)
        entity = self._one("""SELECT e.currency_code FROM reconforge.legal_entities e JOIN reconforge.organizations o
            ON o.tenant_id=e.tenant_id AND o.id=e.organization_id WHERE e.tenant_id=%s AND e.id=%s AND o.id=%s AND e.active AND o.active FOR SHARE OF e,o""",
            (self.tenant_id, scope["legal_entity_id"], scope["organization_id"]))
        item = self._one("""SELECT i.*,u.decimal_places FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u
            ON u.tenant_id=i.tenant_id AND u.id=i.uom_id WHERE i.tenant_id=%s AND i.id=%s AND i.active AND u.active FOR SHARE OF i,u""",
            (self.tenant_id, source["item_id"]))
        if (item["uom_id"] != source["uom_id"] or item["decimal_places"] != source["quantity_precision"]
                or item["inventory_account_id"] != mapping["inventory_account_id"] or item["tracking_mode"] != "None"
                or item["item_type"] not in {"Stock", "Consumable"} or item["workspace_id"] != scope["workspace_id"]
                or item["organization_id"] not in (None, scope["organization_id"])):
            fail("Current stock master differs from the reviewed plan.")
        self._one("""SELECT l.id FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w
          ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id WHERE l.tenant_id=%s AND l.id=%s AND l.active AND w.active
          AND l.location_type='Internal' AND NOT l.allow_negative AND w.workspace_id=%s AND w.organization_id=%s
          AND (w.legal_entity_id IS NULL OR w.legal_entity_id=%s) FOR SHARE OF l,w""",
          (self.tenant_id, source["location_id"], scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"]))
        current = self._one("SELECT * FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND id=%s AND active FOR SHARE",
                            (self.tenant_id, mapping["policy_id"]))
        expected = {"currency_code": mapping["currency_code"], "costing_method": "FIFO", "finance_journal_id": mapping["journal_id"],
                    **{k: mapping[k] for k in ("receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id")},
                    **{k: scope[k] for k in ("workspace_id", "organization_id", "legal_entity_id")}}
        if any(current[k] != v for k, v in expected.items()) or entity["currency_code"] != mapping["currency_code"]:
            fail("Current valuation mapping differs from the independently reviewed source.")
        chart = self._one("SELECT chart_id FROM reconforge.finance_journals WHERE tenant_id=%s AND id=%s", (self.tenant_id, mapping["journal_id"]))
        # Entity reference reads cannot use FOR SHARE on shared Finance metadata:
        # that also applies the intentionally narrower UPDATE RLS policy. Paired
        # metadata mutation triggers use these exact keys without widening scope.
        accounts = {mapping[k] for k in ("inventory_account_id", "receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id")}
        references = [("finance_charts", chart["chart_id"]), ("finance_journals", mapping["journal_id"])]
        references.extend(("finance_accounts", account) for account in accounts)
        for table, identifier in sorted(references):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array(%s::text,%s::text,%s::text)::text,0))",
                                    (self.tenant_id, table, identifier))
        journal = self._one("""SELECT j.* FROM reconforge.finance_journals j JOIN reconforge.finance_charts c
          ON c.tenant_id=j.tenant_id AND c.id=j.chart_id WHERE j.tenant_id=%s AND j.id=%s AND j.active AND c.active""",
          (self.tenant_id, mapping["journal_id"]))
        if journal["currency_code"] != mapping["currency_code"] or journal["workspace_id"] != scope["workspace_id"] or journal["organization_code"] != scope["organization_code"]:
            fail("Current journal is incompatible with the reviewed source.")
        for account in sorted(accounts):
            self._one("SELECT id FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s AND chart_id=%s AND active AND allow_posting",
                      (self.tenant_id, account, journal["chart_id"]))
        if self.connection.execute("SELECT 1 FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s AND active AND required_on_entries AND organization_code IN ('',%s)",
                                   (self.tenant_id, scope["workspace_id"], scope["organization_code"])).fetchone():
            fail("This receipt version does not support required Finance dimensions.")
        master = self._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                           (self.tenant_id, mapping["currency_code"]))
        if master["minor_units"] != plan["currency_policy"]["currency_precision"]:
            fail("Current currency precision differs from the reviewed monetary policy.")
        principal = current_server_principal()
        if principal is None:
            fail("Current monetary policy admission requires the authenticated receipt owner.")
        captured, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(
            workspace_id=scope["workspace_id"], currency_code=mapping["currency_code"],
            minor_units=master["minor_units"], actor_label=principal.user.username,
        )
        if {"currency_code": captured.currency_code, **captured.metadata()} != plan["currency_policy"]:
            fail("Current monetary policy changed after receipt preparation; prepare and review a new source.")

    def review(self, plan_id: str, *, command_id: str, expected_plan_digest: str, reason: str, actor: PostingActor) -> ReceiptReview:
        with self._transaction():
            self._actor(actor, REVIEW_PERMISSIONS)
            plan = self._plan(plan_id, lock=True)
            self._independent(plan, actor, stage="review")
            reason = exact_text(reason, maximum=500)
            digest, replay = self._command(plan["scope"], "review", command_id, {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason})
            if replay is not None:
                retained = self._review(plan)
                if replay != retained or retained is None or retained["reason"] != reason or plan["plan_digest"] != expected_plan_digest:
                    fail("Review acknowledgement differs from its immutable source.")
                return cast(ReceiptReview, retained)
            if plan["plan_digest"] != expected_plan_digest:
                fail("Review expected digest differs from the source plan.")
            if self._review(plan, required=False) is not None:
                fail("An immutable review already exists; recover it using its original command.", "inventory_receipt_command_conflict")
            self._admit(plan)
            review = make_review(plan, actor=actor, reviewed_at=utc_now_text(), reason=reason, audit_event_id="pending", outbox_event_id="pending")
            audit, outbox = self._event(plan, "inventory_receipt_reviewed", actor, self._metadata(plan, review))
            review["audit_event_id"], review["outbox_event_id"] = audit, outbox
            self._insert("inventory_receipt_reviews", {"tenant_id": self.tenant_id, "id": review["review_id"],
                **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
                **{k: review[k] for k in ("plan_id", "plan_version", "plan_digest", "finance_validation_digest", "reviewed_at", "reason", "review_digest", "audit_event_id", "outbox_event_id")},
                "reviewer_actor_id": actor.user_id, "reviewer_username": actor.username, "review_json": review}, json_fields=("review_json",))
            self._remember(plan, "review", command_id, digest, actor, review)
            return review

    def _independent(self, plan: ReceiptPlan, actor: PostingActor, *, stage: str) -> None:
        if actor.user_id == plan["preparer"]["user_id"]:
            fail("A receipt preparer cannot review or post their own source.", "inventory_receipt_sod_denied")
        if plan["operation"] == "FullReceiptReversal":
            self._actor(actor, frozenset({"inventory.valuation.reverse.approve", "finance_core.reverse"}))

    def _locks(self, plan: ReceiptPlan) -> None:
        scope, source = plan["scope"], plan["source"]
        # These literals intentionally match legacy physical and FIFO writers.
        for key in (f"{scope['workspace_id']}|{scope['legal_entity_id']}|{source['location_id']}|{source['item_id']}|",
                    f"{scope['legal_entity_id']}|{source['item_id']}|"):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        if plan["original"]:
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (plan["original"]["cost_layer_id"],))

    def _chronology(self, plan: ReceiptPlan) -> None:
        scope, source = plan["scope"], plan["source"]
        if self.connection.execute("""SELECT 1 FROM reconforge.inventory_movements m WHERE m.tenant_id=%s
          AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND m.movement_type<>'Transfer'
          AND (m.movement_date,m.movement_number)<(%s::date,%s)
          AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents v WHERE v.tenant_id=m.tenant_id AND v.movement_id=m.id AND v.status='Approved')
          AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=m.tenant_id AND r.reversal_movement_id=m.id AND r.status='Approved') LIMIT 1""",
          (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], source["posting_date"], plan["artifacts"]["movement_number"])).fetchone():
            fail("FIFO posting requires earlier physical movements to be valued first.")
        if self.connection.execute("""SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_valuation_documents v
          ON v.tenant_id=m.tenant_id AND v.movement_id=m.id WHERE m.tenant_id=%s AND m.workspace_id=%s
          AND m.organization_id=%s AND m.legal_entity_id=%s AND v.status='Approved'
          AND (m.movement_date,m.movement_number)>(%s::date,%s) LIMIT 1""",
          (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], source["posting_date"], plan["artifacts"]["movement_number"])).fetchone():
            fail("Backdated receipt posting conflicts with a later Approved valuation.")

    def _unused(self, original: ReceiptPlan, *, inverse_movement: str | None = None) -> None:
        source, scope, artifacts = original["source"], original["scope"], original["artifacts"]
        layer = self._one("SELECT * FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                          (self.tenant_id, artifacts["cost_layer_id"]))
        if layer["remaining_quantity_scaled"] != source["quantity_scaled"] or layer["remaining_value_minor"] != source["total_value_minor"]:
            fail("Only the entire unused original receipt can be reversed.", "inventory_receipt_not_unused")
        if self.connection.execute("SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s AND cost_layer_id=%s UNION ALL SELECT 1 FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s AND cost_layer_id=%s LIMIT 1",
                                   (self.tenant_id, artifacts["cost_layer_id"], self.tenant_id, artifacts["cost_layer_id"])).fetchone():
            fail("Receipt has retained consumption or correction history.", "inventory_receipt_not_unused")
        if self.connection.execute("""SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines l
            ON l.tenant_id=m.tenant_id AND l.movement_id=m.id WHERE m.tenant_id=%s AND m.workspace_id=%s
            AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status IN ('Posted','Voided') AND l.item_id=%s
            AND l.from_location_id IS NOT NULL AND m.id IS DISTINCT FROM %s LIMIT 1""",
            (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], source["item_id"], inverse_movement)).fetchone():
            fail("This inverse version refuses any retained outbound item history.", "inventory_receipt_not_unused")

    def prepare_reversal(self, request: ReceiptReversalPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan:
        with self._transaction():
            self._actor(actor, PREPARE_PERMISSIONS | frozenset({"inventory.valuation.reverse.manage", "finance_core.reverse"}))
            original = self._plan(request.original_plan_id)
            self._effect(original)
            if original["operation"] != "Receipt":
                fail("A receipt inverse cannot itself be reversed.")
            digest, replay = self._command(original["scope"], "prepare_reversal", command_id, asdict(request))
            plan_id = source_plan_id(original["scope"], document_number(request.reversal_number, "Reversal number"))
            if replay is not None:
                retained = self._plan(plan_id)
                verify_inverse(retained, original)
                if (replay != retained or retained["reason"] != request.reason or retained["source"]["posting_date"] != request.posting_date
                        or retained["source"]["period_id"] != request.period_id):
                    fail("Inverse preparation acknowledgement differs from the requested source.")
                return retained
            source = {**original["source"], "number": document_number(request.reversal_number, "Reversal number"),
                      "posting_date": exact_date(request.posting_date), "period_id": exact_text(request.period_id)}
            prior = {"plan_id": original["plan_id"], **{k: cast(str, original["artifacts"][k]) for k in (
                "posting_effect_id", "valuation_document_id", "valuation_line_id", "cost_layer_id")}}
            plan = make_plan(operation="FullReceiptReversal", scope=original["scope"], source=source,
                             mapping=original["mapping"], currency_policy=original["currency_policy"], original=prior,
                             actor=actor, prepared_at=utc_now_text(), reason=exact_text(request.reason, maximum=500),
                             audit_event_id="pending", outbox_event_id="pending")
            verify_inverse(plan, original)
            self._admit(plan)
            self._locks(plan)
            self._unused(original)
            self._persist_preparation(plan, actor)
            self._remember(plan, "prepare_reversal", command_id, digest, actor, plan)
            return plan

    def commit(self, plan_id: str, *, command_id: str, expected_review_digest: str, reason: str, actor: PostingActor) -> ReceiptEffect:
        with self._transaction():
            self._actor(actor, COMMIT_PERMISSIONS)
            plan = self._plan(plan_id, lock=True)
            self._independent(plan, actor, stage="commit")
            review = cast(ReceiptReview, self._review(plan))
            reason = exact_text(reason, maximum=500)
            digest, replay = self._command(plan["scope"], "commit", command_id,
                {"plan_id": plan_id, "expected_review_digest": expected_review_digest, "reason": reason})
            if replay is not None:
                retained = self._effect(plan)
                if replay != retained or retained["review_digest"] != expected_review_digest or retained["finance_effect"]["reason"] != reason:
                    fail("Commit acknowledgement differs from verified all-layer backing.")
                return retained
            if review["review_digest"] != expected_review_digest:
                fail("Commit expected review differs from the independently reviewed source.")
            self._admit(plan)
            self._locks(plan)
            self._chronology(plan)
            if plan["original"]:
                original = self._plan(plan["original"]["plan_id"])
                verify_inverse(plan, original)
                self._effect(original)
                self._unused(original)
            now = utc_now_text()
            audit, outbox = self._event(plan, "inventory_receipt_committed", actor, self._metadata(plan, review, committed=True))
            link = {"tenant_id": self.tenant_id, "id": plan_id, "plan_id": plan_id,
                **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
                "review_id": review["review_id"], "plan_digest": plan["plan_digest"], "review_digest": review["review_digest"],
                **{k: v for k, v in plan["artifacts"].items() if k.endswith("_id")},
                "original_plan_id": plan["original"]["plan_id"] if plan["original"] else None,
                "original_posting_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
                "posted_actor_id": actor.user_id, "posted_at": now, "reason": reason, "audit_event_id": audit, "outbox_event_id": outbox}
            self._insert("inventory_receipt_links", link)
            self._materialize_stock(plan, actor, now, reason)
            participant = _ReceiptFinanceParticipant(self)
            participant.materialize_draft(plan_id, expected_review_digest=expected_review_digest, actor=actor)
            self._approve_valuation(plan, actor, now, reason)
            participant.seal_and_post(plan_id, expected_review_digest=expected_review_digest, actor=actor)
            result = self._effect(plan)
            self._remember(plan, "commit", command_id, digest, actor, result)
            # Deferred complete-link constraints remain owned by this transaction.
            return result

    def _materialize_stock(self, plan: ReceiptPlan, actor: PostingActor, now: str, reason: str) -> None:
        scope, source, a, mapping = plan["scope"], plan["source"], plan["artifacts"], plan["mapping"]
        inverse = plan["operation"] == "FullReceiptReversal"
        base = {"tenant_id": self.tenant_id, **{k: scope[k] for k in ("workspace_id", "organization_id", "legal_entity_id")}}
        self._insert("inventory_movements", {**base, "id": a["movement_id"], "period_id": source["period_id"],
            "movement_number": a["movement_number"], "movement_type": "Delivery" if inverse else "Receipt",
            "movement_date": source["posting_date"], "source_reference": plan["plan_id"], "description": plan["reason"],
            "source_type": "Generated", "created_by": plan["preparer"]["username"]})
        self._insert("inventory_movement_lines", {"tenant_id": self.tenant_id, "id": a["movement_line_id"], "movement_id": a["movement_id"],
            "line_number": 1, "item_id": source["item_id"], "uom_id": source["uom_id"],
            "from_location_id": source["location_id"] if inverse else None, "to_location_id": None if inverse else source["location_id"],
            "quantity_scaled": source["quantity_scaled"], "quantity_precision": source["quantity_precision"], "description": plan["reason"]})
        movement = {**base, "id": a["movement_id"]}
        self.inventory._verify_stock(movement, direction=1)
        self.connection.execute("""UPDATE reconforge.inventory_movements SET status='Posted',posted_by=%s,posted_at=%s,
            post_reason=%s,updated_at=%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
            (actor.username, now, reason, now, self.tenant_id, a["movement_id"]))
        if not inverse:
            self._insert("inventory_valuation_documents", {**base, "id": a["valuation_document_id"], "period_id": source["period_id"],
                "movement_id": a["movement_id"], "policy_id": mapping["policy_id"], "valuation_number": a["valuation_number"],
                "valuation_date": source["posting_date"], **plan["currency_policy"], "created_by": plan["preparer"]["username"]})
            self._insert("inventory_valuation_input_costs", {"tenant_id": self.tenant_id, "id": a["input_cost_id"],
                "valuation_document_id": a["valuation_document_id"], "movement_line_id": a["movement_line_id"], "total_cost_minor": source["total_value_minor"]})
            self._insert("inventory_valuation_lines", {"tenant_id": self.tenant_id, "id": a["valuation_line_id"],
                "valuation_document_id": a["valuation_document_id"], "movement_line_id": a["movement_line_id"], "line_number": 1,
                "flow_direction": "Inbound", **{k: source[k] for k in ("item_id", "uom_id", "quantity_scaled", "quantity_precision")},
                "value_minor": source["total_value_minor"], "inventory_account_id": mapping["inventory_account_id"], "offset_account_id": mapping["receipt_clearing_account_id"]})
            self._insert("inventory_cost_layers", {"tenant_id": self.tenant_id, "id": a["cost_layer_id"], "workspace_id": scope["workspace_id"],
                "source_valuation_line_id": a["valuation_line_id"], "legal_entity_id": scope["legal_entity_id"],
                **{k: source[k] for k in ("item_id", "uom_id", "quantity_precision")}, "original_quantity_scaled": source["quantity_scaled"],
                "remaining_quantity_scaled": source["quantity_scaled"], "original_value_minor": source["total_value_minor"],
                "remaining_value_minor": source["total_value_minor"], "currency_code": mapping["currency_code"]})
        else:
            original = cast(dict[str, str], plan["original"])
            self._insert("inventory_valuation_reversals", {**base, "id": a["valuation_reversal_id"], "period_id": source["period_id"],
                "original_valuation_document_id": original["valuation_document_id"], "reversal_movement_id": a["movement_id"],
                "reversal_number": a["valuation_number"], "reversal_date": source["posting_date"], "currency_code": mapping["currency_code"],
                "created_by": plan["preparer"]["username"]})
            self._insert("inventory_valuation_reversal_effects", {"tenant_id": self.tenant_id, "id": a["reversal_effect_id"],
                "reversal_id": a["valuation_reversal_id"], "original_valuation_line_id": original["valuation_line_id"],
                "cost_layer_id": original["cost_layer_id"], "effect_type": "Remove", "quantity_scaled": source["quantity_scaled"], "value_minor": source["total_value_minor"]})
            self.connection.execute("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=0,remaining_value_minor=0,row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, original["cost_layer_id"]))

    def _approve_valuation(self, plan: ReceiptPlan, actor: PostingActor, now: str, reason: str) -> None:
        from psycopg import sql
        inverse = plan["operation"] == "FullReceiptReversal"
        table = "inventory_valuation_reversals" if inverse else "inventory_valuation_documents"
        identifier = plan["artifacts"]["valuation_reversal_id" if inverse else "valuation_document_id"]
        self.connection.execute(sql.SQL("""UPDATE reconforge.{} SET status='Approved',approved_by=%s,approved_at=%s,
            approval_reason=%s,total_value_minor=%s,finance_entry_id=%s,updated_at=%s,row_version=row_version+1
            WHERE tenant_id=%s AND id=%s""").format(sql.Identifier(table)),
            (actor.username, now, reason, plan["source"]["total_value_minor"], plan["artifacts"]["finance_entry_id"], now, self.tenant_id, identifier))

    def _link(self, plan: ReceiptPlan, review: ReceiptReview) -> dict[str, Any]:
        link = self._one("SELECT * FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan["plan_id"]))
        expected = {"id": plan["plan_id"], "review_id": review["review_id"], "plan_digest": plan["plan_digest"], "review_digest": review["review_digest"],
            **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
            **{k: v for k, v in plan["artifacts"].items() if k.endswith("_id")},
            "original_plan_id": plan["original"]["plan_id"] if plan["original"] else None,
            "original_posting_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None}
        if any(link[k] != value for k, value in expected.items()) or link["posted_actor_id"] == plan["preparer"]["user_id"]:
            fail("Receipt output link differs from its independently reviewed source.")
        self._check_event(plan, link["audit_event_id"], link["outbox_event_id"], "inventory_receipt_committed",
                          link["posted_actor_id"], self._metadata(plan, review, committed=True))
        return link

    def _backing(self, plan: ReceiptPlan, review: ReceiptReview, finance: Mapping[str, Any]) -> ReceiptEffect:
        link = self._link(plan, review)
        scope, source, a, mapping = plan["scope"], plan["source"], plan["artifacts"], plan["mapping"]
        inverse = plan["operation"] == "FullReceiptReversal"
        common = {k: scope[k] for k in ("workspace_id", "organization_id", "legal_entity_id")}

        def assert_row(table: str, identifier: str | None, expected: Mapping[str, Any]) -> None:
            from psycopg import sql
            statement = sql.SQL("SELECT * FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(sql.Identifier(table))
            rows = records(self.connection.execute(statement, (self.tenant_id, identifier)))
            if len(rows) != 1:
                fail("Receipt output backing is absent or outside the authorized scope.")
            row = rows[0]
            for key, value in expected.items():
                actual = str(row[key]) if key.endswith("_date") else row[key]
                if actual != value:
                    fail("Receipt output backing disagrees with the reviewed source.")

        assert_row("inventory_movements", a["movement_id"], {**common, "period_id": source["period_id"], "status": "Posted",
            "movement_number": a["movement_number"], "movement_type": "Delivery" if inverse else "Receipt", "movement_date": source["posting_date"],
            "source_type": "Generated", "source_reference": plan["plan_id"], "description": plan["reason"], "created_by": plan["preparer"]["username"]})
        assert_row("inventory_movement_lines", a["movement_line_id"], {"movement_id": a["movement_id"], "line_number": 1,
            **{k: source[k] for k in ("item_id", "uom_id", "quantity_scaled", "quantity_precision")}, "inventory_lot_id": None,
            "from_location_id": source["location_id"] if inverse else None, "to_location_id": None if inverse else source["location_id"], "description": plan["reason"]})
        if self.connection.execute("SELECT count(*) n FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s", (self.tenant_id, a["movement_id"])).fetchone()["n"] != 1:
            fail("Receipt has unreviewed physical lines.")
        if not inverse:
            assert_row("inventory_valuation_documents", a["valuation_document_id"], {**common, "movement_id": a["movement_id"],
                "policy_id": mapping["policy_id"], "period_id": source["period_id"], "valuation_date": source["posting_date"],
                "valuation_number": a["valuation_number"], "status": "Approved", **plan["currency_policy"],
                "total_value_minor": source["total_value_minor"], "finance_entry_id": a["finance_entry_id"], "created_by": plan["preparer"]["username"]})
            assert_row("inventory_valuation_input_costs", a["input_cost_id"], {"valuation_document_id": a["valuation_document_id"],
                "movement_line_id": a["movement_line_id"], "total_cost_minor": source["total_value_minor"]})
            assert_row("inventory_valuation_lines", a["valuation_line_id"], {"valuation_document_id": a["valuation_document_id"],
                "movement_line_id": a["movement_line_id"], "line_number": 1, "flow_direction": "Inbound", "inventory_lot_id": None,
                **{k: source[k] for k in ("item_id", "uom_id", "quantity_scaled", "quantity_precision")}, "value_minor": source["total_value_minor"],
                "inventory_account_id": mapping["inventory_account_id"], "offset_account_id": mapping["receipt_clearing_account_id"]})
            assert_row("inventory_cost_layers", a["cost_layer_id"], {"workspace_id": scope["workspace_id"], "source_valuation_line_id": a["valuation_line_id"],
                "legal_entity_id": scope["legal_entity_id"], **{k: source[k] for k in ("item_id", "uom_id", "quantity_precision")},
                "original_quantity_scaled": source["quantity_scaled"], "original_value_minor": source["total_value_minor"], "currency_code": mapping["currency_code"], "inventory_lot_id": None})
            counts = self._one("""SELECT (SELECT count(*) FROM reconforge.inventory_valuation_lines WHERE tenant_id=%s AND valuation_document_id=%s) lines,
                (SELECT count(*) FROM reconforge.inventory_valuation_input_costs WHERE tenant_id=%s AND valuation_document_id=%s) inputs""",
                (self.tenant_id, a["valuation_document_id"], self.tenant_id, a["valuation_document_id"]))
            if counts["lines"] != 1 or counts["inputs"] != 1:
                fail("Receipt valuation has missing or additional source detail.")
        else:
            original = cast(dict[str, str], plan["original"])
            original_plan = self._plan(original["plan_id"])
            verify_inverse(plan, original_plan)
            original_effect = self._effect(original_plan)
            if original_effect["effect_id"] != original["posting_effect_id"]:
                fail("Receipt inverse lacks its verified complete original effect.")
            assert_row("inventory_valuation_reversals", a["valuation_reversal_id"], {**common, "period_id": source["period_id"],
                "original_valuation_document_id": original["valuation_document_id"], "reversal_movement_id": a["movement_id"],
                "reversal_number": a["valuation_number"], "reversal_date": source["posting_date"], "status": "Approved",
                "total_value_minor": source["total_value_minor"], "currency_code": mapping["currency_code"], "finance_entry_id": a["finance_entry_id"]})
            assert_row("inventory_valuation_reversal_effects", a["reversal_effect_id"], {"reversal_id": a["valuation_reversal_id"],
                "original_valuation_line_id": original["valuation_line_id"], "original_consumption_id": None, "cost_layer_id": original["cost_layer_id"],
                "effect_type": "Remove", "quantity_scaled": source["quantity_scaled"], "value_minor": source["total_value_minor"]})
            if self._one("SELECT count(*) n FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s AND reversal_id=%s", (self.tenant_id, a["valuation_reversal_id"]))["n"] != 1:
                fail("Receipt inverse has missing or additional layer effects.")
        layer = self._one("""SELECT l.*,l.original_quantity_scaled
            -(SELECT COALESCE(sum(quantity_scaled),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=l.tenant_id AND cost_layer_id=l.id)
            +(SELECT COALESCE(sum(CASE effect_type WHEN 'Restore' THEN quantity_scaled ELSE -quantity_scaled END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=l.tenant_id AND cost_layer_id=l.id) expected_quantity,
            l.original_value_minor
            -(SELECT COALESCE(sum(value_minor),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=l.tenant_id AND cost_layer_id=l.id)
            +(SELECT COALESCE(sum(CASE effect_type WHEN 'Restore' THEN value_minor ELSE -value_minor END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=l.tenant_id AND cost_layer_id=l.id) expected_value
            FROM reconforge.inventory_cost_layers l WHERE l.tenant_id=%s AND l.id=%s""", (self.tenant_id, a["cost_layer_id"]))
        if layer["remaining_quantity_scaled"] != layer["expected_quantity"] or layer["remaining_value_minor"] != layer["expected_value"]:
            fail("Receipt layer residual differs from its immutable consumption and correction history.")
        entry = posting_entry(self.connection, self.tenant_id, cast(str, a["finance_entry_id"]))
        if (entry["status"] != "Validated" or entry["validator_actor_id"] != review["reviewer"]["user_id"]
                or entry["validation_digest"] != plan["finance_validation_digest"]
                or entry["validated_by"] != review["reviewer"]["username"] or entry["validated_at"] != review["reviewed_at"] or entry["validation_reason"] != review["reason"]
                or posting_snapshot(self.connection, self.tenant_id, entry) != plan["finance_snapshot"]
                or finance["posted_actor_id"] != link["posted_actor_id"] or finance["posted_at"] != link["posted_at"]
                or finance["reason"] != link["reason"]):
            fail("Receipt Finance backing differs from its review and complete-source link.")
        for number in (1, 2):
            assert_row("finance_entry_lines", a[f"finance_line_{number}_id"], {"entry_id": a["finance_entry_id"], "line_number": number})
        return verify_effect(make_effect(plan, review, finance, audit_event_id=link["audit_event_id"], outbox_event_id=link["outbox_event_id"]), plan, review)

    def _effect(self, plan: ReceiptPlan) -> ReceiptEffect:
        review = cast(ReceiptReview, self._review(plan))
        finance = self.finance._get_effect(cast(str, plan["artifacts"]["posting_effect_id"]))
        return self._backing(plan, review, finance)

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> ReceiptPlanView:
        with self._transaction(write=False):
            self._actor(actor, READ_PERMISSIONS, mutation=False)
            plan = self._plan(plan_id)
            review = self._review(plan, required=False)
            exists = self.connection.execute("SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)).fetchone()
            return {"plan": plan, "review": review, "effect": self._effect(plan) if exists else None}

    def get_effect(self, plan_id: str, *, actor: PostingActor) -> ReceiptEffect:
        with self._transaction(write=False):
            self._actor(actor, READ_PERMISSIONS, mutation=False)
            return self._effect(self._plan(plan_id))


class _ReceiptFinanceParticipant:
    """Private non-finalizing participant bound to the exact live receipt owner."""

    def __init__(self, owner: PostgresInventoryReceiptPostingRepository) -> None:
        self.owner = owner

    def _source(self, plan_id: str, expected: str, actor: PostingActor) -> tuple[ReceiptPlan, ReceiptReview, dict[str, Any]]:
        owner = self.owner
        if not owner._active:
            fail("Finance source participant requires its active receipt owner.", "inventory_receipt_owner_invalid")
        owner._actor(actor, COMMIT_PERMISSIONS)
        plan = owner._plan(plan_id)
        owner._independent(plan, actor, stage="commit")
        review = cast(ReceiptReview, owner._review(plan))
        if review["review_digest"] != expected:
            fail("Finance participant review digest changed.")
        link = owner._link(plan, review)
        if link["posted_actor_id"] != actor.user_id:
            fail("Finance participant actor differs from its owner link.")
        return plan, review, link

    def materialize_draft(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> str:
        with self.owner._operation():
            return self._materialize_draft(plan_id, expected_review_digest=expected_review_digest, actor=actor)

    def _materialize_draft(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> str:
        plan, _, link = self._source(plan_id, expected_review_digest, actor)
        owner = self.owner
        header = plan["finance_snapshot"]["entry"]
        fields = {k: value for k, value in header.items() if k not in {"organization_id", "legal_entity_id"}}
        owner._insert("finance_entries", {"tenant_id": owner.tenant_id, **fields, "status": "Draft",
            "organization_code": plan["scope"]["organization_code"], "entity_code": plan["scope"]["entity_code"],
            "total_debit_minor": plan["source"]["total_value_minor"], "total_credit_minor": plan["source"]["total_value_minor"],
            "created_by": plan["preparer"]["username"], "created_at": link["posted_at"], "updated_at": link["posted_at"]})
        for line in plan["finance_snapshot"]["lines"]:
            number = line["line_number"]
            owner._insert("finance_entry_lines", {"tenant_id": owner.tenant_id,
                "id": plan["artifacts"][f"finance_line_{number}_id"], "entry_id": header["id"],
                **{k: v for k, v in line.items() if k != "dimensions"}, "currency_code": header["currency_code"]})
        return cast(str, header["id"])

    def seal_and_post(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._operation():
            return self._seal_and_post(plan_id, expected_review_digest=expected_review_digest, actor=actor)

    def _seal_and_post(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> dict[str, Any]:
        plan, review, link = self._source(plan_id, expected_review_digest, actor)
        owner, a = self.owner, plan["artifacts"]
        entry = posting_entry(owner.connection, owner.tenant_id, cast(str, a["finance_entry_id"]), lock=True)
        if entry["status"] != "Draft" or posting_snapshot(owner.connection, owner.tenant_id, entry) != plan["finance_snapshot"]:
            fail("Generated Finance Draft differs from its independently reviewed source.")
        owner.finance.finance._validate_entry_integrity(entry["id"])
        owner.connection.execute("""UPDATE reconforge.finance_entries SET status='Validated',validated_by=%s,validated_at=%s,
            validation_reason=%s,updated_at=%s,validator_actor_id=%s,validation_digest=%s,validation_contract_version='finance-entry-review-v1'
            WHERE tenant_id=%s AND id=%s""", (review["reviewer"]["username"], review["reviewed_at"], review["reason"], link["posted_at"],
                review["reviewer"]["user_id"], plan["finance_validation_digest"], owner.tenant_id, entry["id"]))
        audit, outbox = owner.finance._evidence(entry, cast(str, a["posting_effect_id"]), "finance_entry_posted", actor, plan["finance_validation_digest"])
        owner._insert("finance_posting_effects", {"tenant_id": owner.tenant_id, "id": a["posting_effect_id"],
            **{k: plan["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")}, "entry_id": entry["id"],
            "source_kind": "InventoryReceipt" if plan["operation"] == "Receipt" else "InventoryReceiptReversal",
            "source_id": plan_id, "purpose": "operational_posting", "reverses_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
            "validation_digest": plan["finance_validation_digest"], "validation_contract_version": "finance-entry-review-v1", **plan["currency_policy"],
            "snapshot_json": plan["finance_snapshot"], "posted_actor_id": actor.user_id, "posted_at": link["posted_at"], "reason": link["reason"],
            "audit_event_id": audit, "outbox_event_id": outbox}, json_fields=("snapshot_json",))
        return owner.finance._get_effect(cast(str, a["posting_effect_id"]))


def verify_inventory_receipt_finance_effect(connection: Any, tenant_id: str, effect: Mapping[str, Any]) -> None:
    """Finance reads use exact source proof without recursively reading the effect."""
    repository = PostgresInventoryReceiptPostingRepository(connection, tenant_id)
    plan = repository._plan(effect["source_id"])
    review = cast(ReceiptReview, repository._review(plan))
    repository._backing(plan, review, effect)
