"""Shared infrastructure algorithm; application/domain have no SQL dependencies.

The two concrete drivers supply parameter binding, locks, identity persistence,
canonical references and event writes. All SQL identifiers below are constants.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import uuid4

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.budget_control import (
    BudgetControlError,
    BudgetDefinition,
    BudgetScope,
    CommitmentAction,
    conservation,
    digest,
    text,
    transition,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.platform.common import current_server_principal

_BUDGET_TABLES = frozenset({"budget_envelopes", "budget_commitment_events", "budget_commands"})
_BUDGET_COLUMNS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "period_id", "budget_code", "name",
        "currency_code", "limit_minor", "reserved_minor", "consumed_minor", "currency_precision", "currency_rounding_policy",
        "currency_registry_version", "currency_registry_digest", "status", "created_by", "submitted_by", "approved_by", "reason",
        "created_at", "updated_at", "row_version", "budget_id", "commitment_id", "operation", "amount_minor", "remaining_minor",
        "operation_date", "source_reference", "actor_id", "budget_version", "audit_event_id", "outbox_event_id", "request_digest",
        "command_id", "request_json", "result_json", "result_digest",
    }
)


@dataclass(frozen=True)
class BudgetCurrentAuthority:
    """Live authorization facts captured under the command transaction lock.

    The request principal remains useful for session and assurance state, but
    its permissions and hierarchy grants are only an authentication snapshot.
    A financial mutation or recovery must re-read the revocable authority from
    the owning store before it touches retained budget state.
    """

    permissions: frozenset[str]
    workspace_ids: frozenset[str]
    organization_ids: frozenset[str]
    legal_entity_ids: frozenset[str]


class BudgetControlRepositoryBase:
    connection: Any
    tenant_id: str | None

    def _transaction(self, *, write: bool) -> AbstractContextManager[None]:
        raise NotImplementedError

    def _execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        raise NotImplementedError

    def _identity(self, user_id: str, username: str) -> bool:
        raise NotImplementedError

    def _assert_write_session(self, principal: Any) -> None:
        """Revalidate a server-bound privileged session before a financial write.

        Local mode has no separately persisted privileged-session ledger.  The
        PostgreSQL adapter overrides this hook when it is reached through the
        server boundary, so the authorization snapshot cannot outlive a
        revoked session or expired stronger-authentication assertion.
        """

        return None

    def _authority(self, scope: BudgetScope, user_id: str, username: str) -> BudgetCurrentAuthority | None:
        raise NotImplementedError

    def _canonical(self, scope: BudgetScope, *, period_id: str | None = None, currency_code: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def _event(self, scope: BudgetScope, budget_id: str, action: str, actor: Any, metadata: dict[str, Any]) -> tuple[str, str]:
        raise NotImplementedError

    def _where(self) -> tuple[str, tuple[Any, ...]]:
        return ("tenant_id=? AND ", (self.tenant_id,)) if self.tenant_id is not None else ("", ())

    def _lock(self) -> str:
        return " FOR UPDATE" if self.tenant_id is not None else ""

    def _actor(self, scope: BudgetScope, permission: str, *, write: bool, amount: Decimal | None = None) -> Any:
        principal = current_server_principal()
        if principal is None or principal.user.disabled or principal.principal_type != "user":
            raise BudgetControlError("An authenticated persisted human identity is required.")
        if write and not principal.step_up_active:
            raise BudgetControlError("A current stronger authentication session is required.")
        if write:
            self._assert_write_session(principal)
        for value, grants in (
            (scope.workspace_id, principal.authorized_workspace_ids),
            (scope.organization_id, principal.authorized_organization_ids),
            (scope.legal_entity_id, principal.authorized_legal_entity_ids),
        ):
            if grants and value not in grants:
                raise BudgetControlError("Budget scope is outside current authority.")
        if self.tenant_id is not None and principal.authorized_tenant_ids and self.tenant_id not in principal.authorized_tenant_ids:
            raise BudgetControlError("Budget tenant is outside current authority.")
        if not self._identity(principal.user.id, principal.user.username):
            raise BudgetControlError("Budget actor has no active persisted identity.")
        authority = self._authority(scope, principal.user.id, principal.user.username)
        if authority is None or permission not in authority.permissions:
            raise BudgetControlError("Budget actor has no active persisted identity or authority.")
        live_principal = replace(
            principal,
            permissions=authority.permissions,
            authorized_tenant_ids=(frozenset({self.tenant_id}) if self.tenant_id is not None else principal.authorized_tenant_ids),
            authorized_workspace_ids=authority.workspace_ids,
            authorized_organization_ids=authority.organization_ids,
            authorized_legal_entity_ids=authority.legal_entity_ids,
        )
        if not evaluate_principal_access(live_principal, required_permission=permission, tenant_id=self.tenant_id,
                workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id,
                amount=amount, object_type="budget_control", authorized_tenant_ids=live_principal.authorized_tenant_ids,
                authorized_workspace_ids=live_principal.authorized_workspace_ids,
                authorized_organization_ids=live_principal.authorized_organization_ids,
                authorized_entity_ids=live_principal.authorized_legal_entity_ids).allowed:
            raise BudgetControlError("Budget permission denied by current policy.")
        self._canonical(scope)
        return live_principal.user

    def _insert(self, table: str, values: dict[str, Any]) -> None:
        if table not in _BUDGET_TABLES:
            raise BudgetControlError("Budget storage target is not recognized.")
        if self.tenant_id is not None:
            values = {"tenant_id": self.tenant_id, **values}
        names = tuple(values)
        if not set(names).issubset(_BUDGET_COLUMNS):
            raise BudgetControlError("Budget storage columns are not recognized.")
        # Names are closed repository constants; every value is driver-bound.
        self._execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(values.values()))  # nosec B608

    def _row(self, scope: BudgetScope, budget_id: str, *, lock: bool = False) -> dict[str, Any]:
        text(budget_id, "Budget ID")
        where, parameters = self._where()
        # `where` and the lock suffix are internal backend constants.
        row = self._execute(f"SELECT * FROM budget_envelopes WHERE {where}id=? AND workspace_id=? AND organization_id=? AND legal_entity_id=?" + (self._lock() if lock else ""),  # nosec B608
            (*parameters, budget_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id)).fetchone()
        if row is None:
            raise BudgetControlError("Budget was not found in the authorized scope.")
        return dict(row)

    def _command(self, scope: BudgetScope, command_id: str, actor_id: str, request: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "Command ID", 200)
        request_digest = digest({"scope": asdict(scope), "actor_id": actor_id, "request": request})
        where, parameters = self._where()
        if self.tenant_id is not None:
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (json.dumps([self.tenant_id, scope.workspace_id, command_id]),))
        # `where` is the closed SQLite/PostgreSQL tenant predicate; values bind.
        row = self._execute(f"SELECT * FROM budget_commands WHERE {where}workspace_id=? AND command_id=?", (*parameters, scope.workspace_id, command_id)).fetchone()  # nosec B608
        if row is None:
            return request_digest, None
        if row["request_digest"] != request_digest:
            raise BudgetControlError("Command ID already binds a different actor, scope or exact request.")
        payload = row["result_json"]
        result = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(result, dict) or digest(result) != row["result_digest"]:
            raise BudgetControlError("Retained command evidence is malformed.")
        return request_digest, result

    def _remember(self, scope: BudgetScope, command_id: str, request_digest: str, actor_id: str, request: dict[str, Any], result: dict[str, Any]) -> None:
        self._insert("budget_commands", {**asdict(scope), "command_id": command_id, "request_digest": request_digest,
            "budget_id": result["id"], "actor_id": actor_id, "request_json": json.dumps(request, sort_keys=True, separators=(",", ":")),
            "result_json": json.dumps(result, sort_keys=True, separators=(",", ":")), "result_digest": digest(result), "created_at": utc_now_text()})

    def _authoritative_replay(self, scope: BudgetScope, result: dict[str, Any]) -> dict[str, Any]:
        """Refuse a cached acknowledgement until live retained evidence verifies.

        Idempotency never authorizes a stale cached receipt by itself.  The
        caller has already been checked against the live identity, role and
        hierarchy state; this re-read additionally proves that the original
        command and every later immutable effect still form one valid budget
        ledger under that same scope.
        """

        budget_id = result.get("id")
        if not isinstance(budget_id, str):
            raise BudgetControlError("Budget cached acknowledgement has no canonical identifier.")
        text(budget_id, "Budget ID")
        self._public(self._row(scope, budget_id, lock=True))
        return result

    def _public(self, row: dict[str, Any], *, pending_version: int | None = None) -> dict[str, Any]:
        from reconforge.infrastructure.budget_control_verification import verify_budget_envelope

        verify_budget_envelope(self, row, pending_version=pending_version)
        policy, _context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(row)
        available = conservation(row["limit_minor"], row["reserved_minor"], row["consumed_minor"])
        keys = ("id", "workspace_id", "organization_id", "legal_entity_id", "period_id", "budget_code", "name", "currency_code",
                "status", "created_by", "submitted_by", "approved_by", "reason", "created_at", "updated_at", "row_version")
        result = {key: row[key] for key in keys}
        for key in ("limit_minor", "reserved_minor", "consumed_minor"):
            result[key] = str(row[key])
        result["available_minor"] = str(available)
        result["monetary_policy"] = {"precision": policy.precision, "rounding_policy": policy.rounding_policy,
            "registry_version": policy.registry_version, "registry_digest": policy.registry_digest}
        return result

    def create(self, scope: BudgetScope, definition: BudgetDefinition, *, command_id: str) -> dict[str, Any]:
        with self._transaction(write=True):
            actor = self._actor(scope, "budget_control.manage", write=True)
            request = {"operation": "create", **asdict(definition)}
            request_digest, replay = self._command(scope, command_id, actor.id, request)
            if replay is not None:
                return self._authoritative_replay(scope, replay)
            reference = self._canonical(scope, period_id=definition.period_id, currency_code=definition.currency_code)
            policy, _context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(workspace_id=scope.workspace_id,
                currency_code=definition.currency_code, minor_units=reference["minor_units"], actor_label=actor.username)
            amount = Decimal((0, tuple(map(int, str(definition.limit_minor))), -policy.precision))
            self._actor(scope, "budget_control.manage", write=True, amount=amount)
            budget_id = "BGT-" + uuid4().hex
            now = utc_now_text()
            self._insert("budget_envelopes", {"id": budget_id, **asdict(scope), **asdict(definition), **policy.metadata(),
                "status": "Draft", "created_by": actor.id, "submitted_by": None, "approved_by": None,
                "reason": "", "created_at": now, "updated_at": now, "row_version": 1})
            audit_id, outbox_id = self._event(scope, budget_id, "budget.created", actor, {"request_digest": request_digest, "row_version": 1})
            result = self._public(self._row(scope, budget_id), pending_version=1)
            result["evidence"] = {"audit_event_id": audit_id, "outbox_event_id": outbox_id, "request_digest": request_digest}
            self._remember(scope, command_id, request_digest, actor.id, request, result)
            self._public(self._row(scope, budget_id))
            return result

    def transition(self, scope: BudgetScope, budget_id: str, *, action: str, expected_version: int, reason: str, command_id: str) -> dict[str, Any]:
        if action not in {"submit", "approve"}:
            raise BudgetControlError("Unsupported budget lifecycle command.")
        text(reason, "Review reason", 500)
        self._version(expected_version)
        with self._transaction(write=True):
            actor = self._actor(scope, "budget_control.approve" if action == "approve" else "budget_control.manage", write=True)
            row = self._row(scope, budget_id, lock=True)
            policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(row)
            self._actor(scope, "budget_control.approve" if action == "approve" else "budget_control.manage", write=True,
                amount=Decimal((0, tuple(map(int, str(row["limit_minor"]))), -policy.precision)))
            request = {"operation": action, "budget_id": budget_id, "expected_version": expected_version, "reason": reason}
            request_digest, replay = self._command(scope, command_id, actor.id, request)
            if replay is not None:
                return self._authoritative_replay(scope, replay)
            self._canonical(scope, period_id=row["period_id"])
            if row["row_version"] != expected_version:
                raise BudgetControlError("Budget version changed; reload current authoritative balances.")
            status = transition(row["status"], action, preparer_id=row["created_by"], submitter_id=row["submitted_by"], actor_id=actor.id)
            where, parameters = self._where()
            field = "submitted_by" if action == "submit" else "approved_by"
            # `field` has two lifecycle-owned values and `where` is closed.
            self._execute(f"UPDATE budget_envelopes SET status=?,{field}=?,reason=?,updated_at=?,row_version=row_version+1 WHERE {where}id=? AND row_version=?",  # nosec B608
                (status, actor.id, reason, utc_now_text(), *parameters, budget_id, expected_version))
            audit_id, outbox_id = self._event(scope, budget_id, "budget." + action, actor, {"request_digest": request_digest, "row_version": expected_version + 1})
            result = self._public(self._row(scope, budget_id), pending_version=expected_version + 1)
            result["evidence"] = {"audit_event_id": audit_id, "outbox_event_id": outbox_id, "request_digest": request_digest}
            self._remember(scope, command_id, request_digest, actor.id, request, result)
            self._public(self._row(scope, budget_id))
            return result

    @staticmethod
    def _version(value: int) -> None:
        if type(value) is not int or not 1 <= value <= 9_000_000_000_000_000_000:
            raise BudgetControlError("Expected version requires a bounded positive integer.")

    def record(self, scope: BudgetScope, budget_id: str, action: CommitmentAction, *, expected_version: int, command_id: str, commitment_id: str = "") -> dict[str, Any]:
        self._version(expected_version)
        if action.operation != "Reserve":
            text(commitment_id, "Commitment ID")
        elif commitment_id:
            raise BudgetControlError("Reserve allocates its own immutable commitment ID.")
        with self._transaction(write=True):
            actor = self._actor(scope, "budget_control.manage", write=True)
            row = self._row(scope, budget_id, lock=True)
            policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(row)
            self._actor(scope, "budget_control.manage", write=True,
                amount=Decimal((0, tuple(map(int, str(action.amount_minor))), -policy.precision)))
            request = {"budget_id": budget_id, "expected_version": expected_version, "commitment_id": commitment_id, **asdict(action)}
            request_digest, replay = self._command(scope, command_id, actor.id, request)
            if replay is not None:
                return self._authoritative_replay(scope, replay)
            reference = self._canonical(scope, period_id=row["period_id"])
            if row["status"] != "Approved" or row["row_version"] != expected_version:
                raise BudgetControlError("Commitment requires an approved budget at the current exact version.")
            if expected_version >= 1003:
                raise BudgetControlError("Budget reached its reviewed limit of 1000 commitment events.")
            if not str(reference["start_date"]) <= action.operation_date <= str(reference["end_date"]):
                raise BudgetControlError("Commitment date is outside the retained fiscal period.")
            where, parameters = self._where()
            if action.operation == "Reserve":
                if action.amount_minor > conservation(row["limit_minor"], row["reserved_minor"], row["consumed_minor"]):
                    raise BudgetControlError("Budget capacity exceeded.")
                commitment_id = "BCM-" + uuid4().hex
                remaining = action.amount_minor
            else:
                # `where` is a repository-selected tenant predicate; values bind.
                prior = self._execute(f"SELECT * FROM budget_commitment_events WHERE {where}budget_id=? AND commitment_id=? ORDER BY budget_version DESC LIMIT 1",  # nosec B608
                    (*parameters, budget_id, commitment_id)).fetchone()
                if prior is None or prior["source_reference"] != action.source_reference or action.amount_minor > prior["remaining_minor"]:
                    raise BudgetControlError("Commitment reference or remaining capacity is invalid.")
                remaining = prior["remaining_minor"] - action.amount_minor
            event_id = "BCE-" + uuid4().hex
            audit_id, outbox_id = self._event(scope, budget_id, "budget." + action.operation.lower(), actor,
                {"commitment_id": commitment_id, "event_id": event_id, "request_digest": request_digest, "row_version": expected_version + 1})
            self._insert("budget_commitment_events", {"id": event_id, "budget_id": budget_id, "commitment_id": commitment_id,
                **asdict(action), "remaining_minor": remaining, "actor_id": actor.id, "created_at": utc_now_text(),
                "budget_version": expected_version + 1, "audit_event_id": audit_id, "outbox_event_id": outbox_id, "request_digest": request_digest})
            result = self._public(self._row(scope, budget_id), pending_version=expected_version + 1)
            result["commitment_id"] = commitment_id
            result["remaining_minor"] = str(remaining)
            result["evidence"] = {"event_id": event_id, "audit_event_id": audit_id, "outbox_event_id": outbox_id, "request_digest": request_digest}
            self._remember(scope, command_id, request_digest, actor.id, request, result)
            self._public(self._row(scope, budget_id))
            return result

    def get(self, scope: BudgetScope, budget_id: str) -> dict[str, Any]:
        with self._transaction(write=False):
            self._actor(scope, "budget_control.read", write=False)
            result = self._public(self._row(scope, budget_id))
            where, parameters = self._where()
            # `where` is closed and the budget identifier is parameterized.
            rows = self._execute(f"SELECT * FROM budget_commitment_events WHERE {where}budget_id=? ORDER BY budget_version DESC LIMIT 101", (*parameters, budget_id)).fetchall()  # nosec B608
            events = []
            for raw in rows[:100]:
                event = dict(raw)
                event.pop("tenant_id", None)
                for key in ("amount_minor", "remaining_minor"):
                    event[key] = str(event[key])
                events.append(event)
            result["events"] = events
            result["events_has_more"] = len(rows) > 100
            return result

    def list(self, scope: BudgetScope, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or not 0 <= offset <= 10_000_000:
            raise BudgetControlError("Budget pagination is outside the supported bounds.")
        with self._transaction(write=False):
            self._actor(scope, "budget_control.read", write=False)
            where, parameters = self._where()
            # `where` is closed and all scope/pagination values bind.
            rows = self._execute(f"SELECT * FROM budget_envelopes WHERE {where}workspace_id=? AND organization_id=? AND legal_entity_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",  # nosec B608
                (*parameters, scope.workspace_id, scope.organization_id, scope.legal_entity_id, limit + 1, offset)).fetchall()
            return {"envelopes": [self._public(dict(row)) for row in rows[:limit]], "pagination": {"limit": limit, "offset": offset, "has_more": len(rows) > limit}}
