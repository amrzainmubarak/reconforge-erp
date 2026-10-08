"""Central Policy Engine for RBAC, ABAC, and Segregation of Duties (SoD) evaluation."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from reconforge.audit import append_audit_event
from reconforge.auth.rbac import canonical_policy_value, check_sod_conflict
from reconforge.domain.protocols import AuditEventRepositoryProtocol

if TYPE_CHECKING:
    from reconforge.platform.common import ServerPrincipal

_POLICY_LOGGER = logging.getLogger("reconforge.authorization")
POLICY_VERSION = "central-policy-v3"
_READABLE_POLICY_VERSIONS = frozenset({"central-policy-v1", "central-policy-v2", POLICY_VERSION})
POLICY_DECISION_EVIDENCE_SCHEMA_VERSION = 1
PrincipalType = Literal["user", "service_account"]
HUMAN_ONLY_PERMISSIONS = frozenset(
    {
        "jobs.manage",
        "sales.manage",
        "sales.approve",
        "accounts.review",
        "accounts.complete",
        "audit.read",
        "audit.verify",
        "close.manage",
        "finance_core.manage",
        "finance_core.post",
        "finance_core.reverse",
        "finance_core.validate",
        "inventory.post",
        "payables.reverse",
        "receivables.credit_override",
        "roles.manage",
        "service_accounts.manage",
        "security.emergency.approve",
        "security.emergency.review",
        "security.emergency.request",
        "security.center.read",
        "security.policy.manage",
        "connectors.writeback.propose",
        "connectors.writeback.approve",
        "connectors.writeback.reconcile",
        "connectors.writeback.dispatch",
        "connectors.writeback.compensate",
        "users.manage",
    }
)
PRIVILEGED_STEP_UP_PERMISSIONS = frozenset(
    {
        "jobs.manage",
        "sales.manage",
        "sales.approve",
        "audit.read",
        "audit.verify",
        "close.manage",
        "finance_core.manage",
        "finance_core.post",
        "finance_core.reverse",
        "finance_core.validate",
        "inventory.post",
        "payables.reverse",
        "receivables.credit_override",
        "roles.manage",
        "service_accounts.manage",
        "security.emergency.approve",
        "security.emergency.review",
        "security.emergency.request",
        "security.center.read",
        "security.policy.manage",
        "connectors.writeback.dispatch",
        "connectors.writeback.compensate",
        "users.manage",
    }
)


def permission_requires_human(permission: str) -> bool:
    """Return whether a permission can make or administer a human-governed decision."""

    return permission in HUMAN_ONLY_PERMISSIONS or permission.endswith((".approve", ".review", ".complete"))


@dataclass(frozen=True)
class PolicyEvaluationContext:
    """Contextual attributes for policy evaluation."""

    user_id: str
    username: str
    user_permissions: set[str] | frozenset[str]
    principal_type: PrincipalType = "user"
    step_up_active: bool = False
    step_up_enforced: bool = False
    required_step_up_method: str | None = None
    step_up_method: str | None = None
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    entity_id: str | None = None
    period_id: str | None = None
    region_id: str | None = None
    data_classification: str | None = None
    amount: Decimal | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    authorized_tenant_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_organization_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_workspace_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_entity_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_period_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_region_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_data_classifications: frozenset[str] = field(default_factory=frozenset)
    requested_field_names: frozenset[str] = field(default_factory=frozenset)
    authorized_field_names: frozenset[str] = field(default_factory=frozenset)
    delegation_id: str | None = None
    delegation_expires_at: datetime | None = None
    evaluation_time: datetime | None = None
    object_type: str | None = None
    object_id: str | None = None
    object_owner_id: str | None = None
    action: str | None = None
    prior_actions: list[tuple[str, str, str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for field_name in ("amount", "minimum_amount", "maximum_amount"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValueError(f"{field_name} must be a finite Decimal when supplied.")
        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.minimum_amount > self.maximum_amount
        ):
            raise ValueError("minimum_amount cannot exceed maximum_amount.")
        for field_name in ("delegation_expires_at", "evaluation_time"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware when supplied.")
        if self.delegation_expires_at is not None and not self.delegation_id:
            raise ValueError("delegation_id is required when delegation_expires_at is supplied.")
        for field_name, values in (
            ("requested_field_names", self.requested_field_names),
            ("authorized_field_names", self.authorized_field_names),
        ):
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain non-empty field names.")


def _digest_payload(payload: object) -> str:
    """Hash a canonical JSON payload without exposing its values in evidence."""

    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _digest_text(*, namespace: str, value: object) -> str:
    """Hash one value with an explicit namespace to prevent scope collisions."""

    return _digest_payload({"namespace": namespace, "value": str(value)})


def _digest_values(*, namespace: str, values: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> str:
    """Hash a sorted set of values while retaining its semantic namespace."""

    return _digest_payload({"namespace": namespace, "values": sorted(str(value) for value in values)})


def policy_scope_digest(context: PolicyEvaluationContext) -> str:
    """Return a digest over resource and grant scopes with typed namespaces.

    Raw tenant, workspace, entity, period, region, and classification identifiers
    are never emitted.  The namespace labels are part of the hashed payload so
    identical text in different scope dimensions cannot become the same evidence
    input by accident.
    """

    scope_payload = {
        "data_classification": {
            "resource": _digest_text(namespace="scope.data_classification.resource", value=context.data_classification)
            if context.data_classification is not None
            else None,
            "grants": _digest_values(
                namespace="scope.data_classification.grant", values=context.authorized_data_classifications
            ),
        },
        "entity": {
            "resource": _digest_text(namespace="scope.entity.resource", value=context.entity_id)
            if context.entity_id is not None
            else None,
            "grants": _digest_values(namespace="scope.entity.grant", values=context.authorized_entity_ids),
        },
        "organization": {
            "resource": _digest_text(namespace="scope.organization.resource", value=context.organization_id)
            if context.organization_id is not None
            else None,
            "grants": _digest_values(namespace="scope.organization.grant", values=context.authorized_organization_ids),
        },
        "period": {
            "resource": _digest_text(namespace="scope.period.resource", value=context.period_id)
            if context.period_id is not None
            else None,
            "grants": _digest_values(namespace="scope.period.grant", values=context.authorized_period_ids),
        },
        "region": {
            "resource": _digest_text(namespace="scope.region.resource", value=context.region_id)
            if context.region_id is not None
            else None,
            "grants": _digest_values(namespace="scope.region.grant", values=context.authorized_region_ids),
        },
        "tenant": {
            "resource": _digest_text(namespace="scope.tenant.resource", value=context.tenant_id)
            if context.tenant_id is not None
            else None,
            "grants": _digest_values(namespace="scope.tenant.grant", values=context.authorized_tenant_ids),
        },
        "workspace": {
            "resource": _digest_text(namespace="scope.workspace.resource", value=context.workspace_id)
            if context.workspace_id is not None
            else None,
            "grants": _digest_values(namespace="scope.workspace.grant", values=context.authorized_workspace_ids),
        },
    }
    return _digest_payload({"schema_version": POLICY_DECISION_EVIDENCE_SCHEMA_VERSION, "scopes": scope_payload})


def policy_context_digest(context: PolicyEvaluationContext) -> str:
    """Return a replay-oriented digest over every policy input.

    The digest intentionally contains only canonicalized or hashed values.  It
    binds the actor, permission snapshot, typed scope snapshot, exact Decimal
    bounds, SoD history, ownership, delegation, and requested fields without
    placing financial or identity data in logs.
    """

    def decimal_digest(namespace: str, value: Decimal | None) -> str | None:
        return _digest_text(namespace=namespace, value=str(value)) if value is not None else None

    def timestamp(value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value is not None else None

    prior_actions = [
        [
            str(actor).strip().casefold(),
            str(object_type).strip().casefold(),
            str(object_id).strip().casefold(),
            str(action).strip().casefold(),
        ]
        for actor, object_type, object_id, action in context.prior_actions
    ]
    payload = {
        "action": str(context.action or "").strip().casefold(),
        "amount": decimal_digest("financial.amount", context.amount),
        "authorized_fields": _digest_values(namespace="field.authorized", values=context.authorized_field_names),
        "context_schema_version": POLICY_DECISION_EVIDENCE_SCHEMA_VERSION,
        "data_classification": _digest_text(namespace="classification.value", value=context.data_classification)
        if context.data_classification is not None
        else None,
        "delegation": {
            "expires_at": timestamp(context.delegation_expires_at),
            "id": _digest_text(namespace="delegation.id", value=context.delegation_id)
            if context.delegation_id is not None
            else None,
        },
        "evaluation_time": timestamp(context.evaluation_time),
        "maximum_amount": decimal_digest("financial.maximum_amount", context.maximum_amount),
        "minimum_amount": decimal_digest("financial.minimum_amount", context.minimum_amount),
        "object": {
            "id": _digest_text(namespace="object.id", value=str(context.object_id).strip().casefold())
            if context.object_id is not None
            else None,
            "owner": _digest_text(namespace="principal.owner", value=str(context.object_owner_id).strip().casefold())
            if context.object_owner_id is not None
            else None,
            "type": str(context.object_type or "").strip().casefold(),
        },
        "permissions": _digest_values(namespace="permission.snapshot", values=context.user_permissions),
        "principal_type": context.principal_type,
        "prior_actions": prior_actions,
        "requested_fields": _digest_values(namespace="field.requested", values=context.requested_field_names),
        "scope_digest": policy_scope_digest(context),
        "step_up": {
            "active": context.step_up_active,
            "enforced": context.step_up_enforced,
            "method": context.step_up_method,
            "required_method": context.required_step_up_method,
        },
        "user": {
            "id": _digest_text(namespace="principal.user", value=str(context.user_id).strip().casefold()),
            "username": _digest_text(namespace="principal.username", value=str(context.username).strip().casefold()),
        },
    }
    return _digest_payload(payload)


@dataclass(frozen=True)
class PolicyDecision:
    """Decision produced by the central policy engine."""

    allowed: bool
    reason: str
    reason_code: str = "policy_allowed"
    evaluator: str = "CentralPolicyEngine"
    granted_permission: str | None = None
    context_digest: str | None = None
    scope_digest: str | None = None


@dataclass(frozen=True)
class PolicyDecisionEvidence:
    """Closed, redacted evidence for one central policy evaluation."""

    schema_version: int
    policy_version: str
    allowed: bool
    reason_code: str
    evaluator: str
    principal_type: PrincipalType
    actor_digest: str
    required_permission_digest: str
    granted_permission_digest: str | None
    context_binding: Literal["bound", "unbound"]
    context_digest: str
    scope_digest: str
    surface_digest: str
    request_id_digest: str
    decision_digest: str

    def _unsigned(self) -> dict[str, object]:
        return {
            "actor_digest": self.actor_digest,
            "allowed": self.allowed,
            "context_binding": self.context_binding,
            "context_digest": self.context_digest,
            "evaluator": self.evaluator,
            "granted_permission_digest": self.granted_permission_digest,
            "policy_version": self.policy_version,
            "principal_type": self.principal_type,
            "reason_code": self.reason_code,
            "request_id_digest": self.request_id_digest,
            "required_permission_digest": self.required_permission_digest,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
            "surface_digest": self.surface_digest,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "decision_digest": self.decision_digest}


PolicyAuditSink = Callable[[PolicyDecisionEvidence], None]


def build_policy_decision_evidence(
    decision: PolicyDecision,
    *,
    actor_id: str,
    required_permissions: frozenset[str],
    surface: str,
    request_id: str = "",
    principal_type: PrincipalType = "user",
    context: PolicyEvaluationContext | None = None,
) -> PolicyDecisionEvidence:
    """Build deterministic, redacted evidence for a policy decision."""

    if not isinstance(decision, PolicyDecision):
        raise TypeError("decision must be a PolicyDecision")
    if principal_type not in {"user", "service_account"}:
        raise ValueError("principal_type is invalid")
    if (
        not isinstance(required_permissions, frozenset)
        or not required_permissions
        or any(not isinstance(value, str) or not value.strip() for value in required_permissions)
    ):
        raise ValueError("required_permissions must be a non-empty frozenset of strings")
    if context is not None:
        expected_context_digest = policy_context_digest(context)
        expected_scope_digest = policy_scope_digest(context)
        if decision.context_digest is not None and decision.context_digest != expected_context_digest:
            raise ValueError("policy decision context digest does not match supplied context")
        if decision.scope_digest is not None and decision.scope_digest != expected_scope_digest:
            raise ValueError("policy decision scope digest does not match supplied context")
        context_digest = expected_context_digest
        scope_digest = expected_scope_digest
    else:
        context_digest = decision.context_digest or _digest_payload({"context": "unbound"})
        scope_digest = decision.scope_digest or _digest_payload({"scope": "unbound"})
    evidence = PolicyDecisionEvidence(
        schema_version=POLICY_DECISION_EVIDENCE_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        allowed=decision.allowed,
        reason_code=decision.reason_code,
        evaluator=decision.evaluator,
        principal_type=principal_type,
        actor_digest=_digest_text(namespace="principal.actor", value=str(actor_id).strip().casefold()),
        required_permission_digest=_digest_values(namespace="permission.contract", values=required_permissions),
        granted_permission_digest=(
            _digest_text(namespace="permission.granted", value=decision.granted_permission)
            if decision.granted_permission is not None
            else None
        ),
        context_binding="bound" if decision.context_digest is not None or context is not None else "unbound",
        context_digest=context_digest,
        scope_digest=scope_digest,
        surface_digest=_digest_text(namespace="audit.surface", value=surface),
        request_id_digest=_digest_text(namespace="audit.request", value=request_id),
        decision_digest="",
    )
    unsigned = evidence._unsigned()
    return replace(evidence, decision_digest=_digest_payload(unsigned))


def verify_policy_decision_evidence(payload: object) -> dict[str, object]:
    """Verify the closed shape and digest of one policy-decision artifact."""

    if not isinstance(payload, dict):
        raise ValueError("Policy decision evidence must be an object.")
    expected_fields = {
        "actor_digest",
        "allowed",
        "context_binding",
        "context_digest",
        "decision_digest",
        "evaluator",
        "granted_permission_digest",
        "policy_version",
        "principal_type",
        "reason_code",
        "request_id_digest",
        "required_permission_digest",
        "schema_version",
        "scope_digest",
        "surface_digest",
    }
    if set(payload) != expected_fields:
        raise ValueError("Policy decision evidence fields are not exactly declared.")
    if (
        not isinstance(payload.get("schema_version"), int)
        or isinstance(payload.get("schema_version"), bool)
        or payload.get("schema_version") != POLICY_DECISION_EVIDENCE_SCHEMA_VERSION
    ):
        raise ValueError("Policy decision evidence schema version is unsupported.")
    if not isinstance(payload.get("policy_version"), str) or payload["policy_version"] not in _READABLE_POLICY_VERSIONS:
        raise ValueError("Policy decision evidence policy version is unsupported.")
    if not isinstance(payload.get("allowed"), bool):
        raise ValueError("Policy decision evidence allowed value is invalid.")
    if payload.get("principal_type") not in {"user", "service_account"}:
        raise ValueError("Policy decision evidence principal type is invalid.")
    if payload.get("context_binding") not in {"bound", "unbound"}:
        raise ValueError("Policy decision evidence context binding is invalid.")
    for field_name in ("reason_code", "evaluator"):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"Policy decision evidence {field_name} is invalid.")
    for field_name in (
        "actor_digest",
        "context_digest",
        "decision_digest",
        "required_permission_digest",
        "scope_digest",
        "surface_digest",
        "request_id_digest",
    ):
        value = payload.get(field_name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"Policy decision evidence {field_name} is invalid.")
    granted_digest = payload.get("granted_permission_digest")
    if granted_digest is not None and (
        not isinstance(granted_digest, str)
        or len(granted_digest) != 64
        or any(character not in "0123456789abcdef" for character in granted_digest)
    ):
        raise ValueError("Policy decision evidence granted permission digest is invalid.")
    unsigned = dict(payload)
    unsigned.pop("decision_digest")
    if _digest_payload(unsigned) != payload["decision_digest"]:
        raise ValueError("Policy decision evidence digest mismatch.")
    return dict(payload)


def _bind_policy_decision(context: PolicyEvaluationContext, decision: PolicyDecision) -> PolicyDecision:
    """Bind central-engine output to the exact context that produced it."""

    return replace(
        decision,
        context_digest=policy_context_digest(context),
        scope_digest=policy_scope_digest(context),
    )


def audit_policy_decision(
    decision: PolicyDecision,
    *,
    actor_id: str,
    required_permissions: frozenset[str],
    surface: str,
    request_id: str = "",
    principal_type: PrincipalType = "user",
    context: PolicyEvaluationContext | None = None,
    audit_connection: sqlite3.Connection | None = None,
    audit_repository: AuditEventRepositoryProtocol | None = None,
    audit_sink: PolicyAuditSink | None = None,
) -> PolicyDecisionEvidence:
    """Emit sanitized authorization evidence without raw scope data.

    The historical ``permission_contract_digest`` remains for log-reader
    compatibility.  The additive decision evidence carries the stronger closed
    contract and a digest over the policy context when the evaluator supplied
    one. When a local SQLite connection or backend-neutral append-only
    repository is supplied, the same redacted evidence is appended to that
    ledger. A sink is available for request-scoped server adapters that must
    acquire their own tenant-bound transaction. Callers must select exactly one
    persistence boundary; absent one, the structured-log boundary is retained.
    """

    if audit_connection is not None and audit_repository is not None:
        raise ValueError("audit_connection and audit_repository are mutually exclusive")
    if (audit_connection is not None or audit_repository is not None) and audit_sink is not None:
        raise ValueError("audit_sink cannot be combined with a direct audit persistence boundary")

    permission_digest = hashlib.sha256(
        json.dumps(sorted(required_permissions), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    actor_digest = hashlib.sha256(actor_id.strip().casefold().encode("utf-8")).hexdigest() if actor_id.strip() else ""
    evidence = build_policy_decision_evidence(
        decision,
        actor_id=actor_id,
        required_permissions=required_permissions,
        surface=surface,
        request_id=request_id,
        principal_type=principal_type,
        context=context,
    )
    _POLICY_LOGGER.info(
        "authorization_decision",
        extra={
            "authorization": {
                "actor_digest": actor_digest,
                "allowed": decision.allowed,
                "evaluator": decision.evaluator,
                "permission_contract_digest": permission_digest,
                "principal_type": principal_type,
                "policy_version": POLICY_VERSION,
                "reason_code": decision.reason_code,
                "request_id": request_id,
                "surface": surface,
                "decision_evidence": evidence.to_dict(),
                "decision_digest": evidence.decision_digest,
                "policy_decision_schema_version": evidence.schema_version,
                "policy_context_digest": evidence.context_digest,
                "policy_scope_digest": evidence.scope_digest,
            }
        },
    )
    event_metadata = {
        "policy_decision_evidence": evidence.to_dict(),
        "request_id_digest": _digest_text(namespace="request.id", value=request_id),
    }
    if audit_connection is not None:
        append_audit_event(
            audit_connection,
            actor_user_id=actor_id.strip() or None,
            actor_label="policy-engine",
            object_type="authorization.policy_decision",
            object_id=evidence.decision_digest,
            action="evaluated",
            after_hash=evidence.decision_digest,
            metadata=event_metadata,
        )
    elif audit_repository is not None:
        audit_repository.append(
            actor_user_id=actor_id.strip() or None,
            actor_label="policy-engine",
            object_type="authorization.policy_decision",
            object_id=evidence.decision_digest,
            action="evaluated",
            after_hash=evidence.decision_digest,
            metadata=event_metadata,
        )
    elif audit_sink is not None:
        audit_sink(evidence)
    return evidence


class CentralPolicyEngine:
    """Centralized policy engine evaluating RBAC, ABAC, and SoD rules.

    Enforces 'Deny by default' principle.
    """

    def evaluate(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permission: str | None = None,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
    ) -> PolicyDecision:
        """Evaluate access and bind the result to a redacted input digest."""

        return _bind_policy_decision(
            ctx,
            self._evaluate_unbound(
                ctx,
                required_permission=required_permission,
                enforce_sod=enforce_sod,
                enforce_ownership=enforce_ownership,
            ),
        )

    def _evaluate_unbound(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permission: str | None = None,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
    ) -> PolicyDecision:
        """Evaluate access for a given context and policy options."""

        # 1. Deny if context is missing basic user identity
        if not ctx.user_id:
            return PolicyDecision(False, "Deny: missing authenticated user identity.", "identity_missing")

        # Temporary delegated authority is explicit, replayable, and fail-closed.
        # The caller must provide the evaluation instant; wall-clock reads are not
        # hidden inside the policy engine.
        if ctx.delegation_expires_at is not None:
            if ctx.evaluation_time is None:
                return PolicyDecision(
                    False,
                    "Deny: delegated authority requires an explicit evaluation time.",
                    "delegation_evaluation_time_missing",
                )
            if ctx.evaluation_time >= ctx.delegation_expires_at:
                return PolicyDecision(
                    False,
                    "Deny: delegated authority has expired.",
                    "delegation_expired",
                )

        # 2. A caller must name the permission contract. Identity alone never grants access.
        if not required_permission:
            return PolicyDecision(False, "Deny: no required permission was specified.", "permission_contract_missing")
        if required_permission not in ctx.user_permissions:
            return PolicyDecision(
                allowed=False,
                reason=f"Deny: missing required permission '{required_permission}'.",
                reason_code="permission_missing",
            )
        cash_action = (
            required_permission == "receivables.manage"
            and ctx.object_type == "receivables.receipt"
            and ctx.action in {"post", "allocate"}
        )
        privileged_action = required_permission in PRIVILEGED_STEP_UP_PERMISSIONS or cash_action
        if ctx.principal_type == "service_account" and (permission_requires_human(required_permission) or cash_action):
            return PolicyDecision(
                allowed=False,
                reason="Deny: service accounts cannot perform a human-governed action.",
                reason_code="human_principal_required",
            )
        if (ctx.step_up_enforced or cash_action) and privileged_action and not ctx.step_up_active:
            return PolicyDecision(
                allowed=False,
                reason="Deny: this privileged action requires recent human reauthentication.",
                reason_code="step_up_required",
            )
        if (
            privileged_action
            and ctx.required_step_up_method is not None
            and ctx.step_up_method != ctx.required_step_up_method
        ):
            return PolicyDecision(
                allowed=False,
                reason="Deny: this privileged action requires the configured MFA assurance method.",
                reason_code="mfa_required",
            )

        # 3. Enforce every supplied resource scope. Empty grants deny scoped access.
        scope_checks = (
            ("tenant", ctx.tenant_id, ctx.authorized_tenant_ids),
            ("organization", ctx.organization_id, ctx.authorized_organization_ids),
            ("workspace", ctx.workspace_id, ctx.authorized_workspace_ids),
            ("entity", ctx.entity_id, ctx.authorized_entity_ids),
            ("period", ctx.period_id, ctx.authorized_period_ids),
            ("region", ctx.region_id, ctx.authorized_region_ids),
            ("data_classification", ctx.data_classification, ctx.authorized_data_classifications),
        )
        for scope_name, resource_id, authorized_ids in scope_checks:
            if resource_id is not None and resource_id not in authorized_ids:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Deny: {scope_name} scope is not authorized.",
                    reason_code=f"{scope_name}_scope_denied",
                )

        # A broader grant does not widen the authority selected for this mutation.
        # Workspace-only currency administration retains the existing tenant-wide
        # master_data.manage contract; permission-to-resource binding is separate.
        if required_permission == "master_data.manage" and canonical_policy_value(ctx.action) == "mutate":
            resource = canonical_policy_value(ctx.object_type)
            entity_is_too_narrow = ctx.entity_id is not None and resource in {
                "master_data.organization", "master_data.currency", "master_data.fiscal_period",
            }
            organization_is_too_narrow = ctx.organization_id is not None and resource in {
                "master_data.currency", "master_data.fiscal_period",
            }
            if entity_is_too_narrow or organization_is_too_narrow:
                return PolicyDecision(
                    False,
                    "Deny: the selected authority cannot mutate shared master data.",
                    "master_data_authority_denied",
                )

        if ctx.minimum_amount is not None or ctx.maximum_amount is not None:
            if ctx.amount is None:
                return PolicyDecision(
                    False,
                    "Deny: a bounded financial policy requires an exact amount.",
                    "amount_missing_for_bounded_policy",
                )
            if ctx.minimum_amount is not None and ctx.amount < ctx.minimum_amount:
                return PolicyDecision(False, "Deny: amount is below the authorized policy floor.", "amount_below_floor")
            if ctx.maximum_amount is not None and ctx.amount > ctx.maximum_amount:
                return PolicyDecision(
                    False, "Deny: amount exceeds the authorized policy ceiling.", "amount_above_ceiling"
                )

        if ctx.requested_field_names and not ctx.requested_field_names.issubset(ctx.authorized_field_names):
            return PolicyDecision(
                False,
                "Deny: one or more requested fields are not authorized.",
                "field_scope_denied",
            )

        # 4. Check Segregation of Duties (SoD) if object & action are specified
        if enforce_sod and ctx.object_type and ctx.object_id and ctx.action:
            sod_result = check_sod_conflict(
                user_id=ctx.user_id,
                object_type=ctx.object_type,
                object_id=ctx.object_id,
                action=ctx.action,
                prior_actions=ctx.prior_actions,
            )
            if not sod_result.allowed:
                return PolicyDecision(False, sod_result.reason, "sod_conflict")

        # 5. Self-approval/review is never an ordinary override path.
        if (
            enforce_ownership
            and canonical_policy_value(ctx.object_owner_id)
            and canonical_policy_value(ctx.user_id) == canonical_policy_value(ctx.object_owner_id)
            and canonical_policy_value(ctx.action) in {"approve", "review", "certify"}
        ):
            return PolicyDecision(
                allowed=False,
                reason="Deny: user cannot approve or review objects they created (certification is also prohibited).",
                reason_code="self_approval_denied",
            )

        return PolicyDecision(allowed=True, reason="Access granted.", granted_permission=required_permission)

    def evaluate_any(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
    ) -> PolicyDecision:
        """Evaluate an any-of contract and bind the result to its context."""

        return _bind_policy_decision(ctx, self._evaluate_any_unbound(ctx, required_permissions=required_permissions))

    def _evaluate_any_unbound(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
    ) -> PolicyDecision:
        """Require one permission from a non-empty, immutable any-of contract."""

        if not required_permissions or any(not value.strip() for value in required_permissions):
            return PolicyDecision(False, "Deny: no required permission was specified.", "permission_contract_missing")
        if not ctx.user_id:
            return PolicyDecision(False, "Deny: missing authenticated user identity.", "identity_missing")
        if ctx.user_permissions.isdisjoint(required_permissions):
            return PolicyDecision(False, "Deny: no required permission is granted.", "permission_missing")
        # Scope and future contextual checks remain centralized in evaluate.
        candidates = ctx.user_permissions.intersection(required_permissions)
        if ctx.principal_type == "service_account":
            candidates = frozenset(permission for permission in candidates if not permission_requires_human(permission))
            if not candidates:
                return PolicyDecision(
                    False,
                    "Deny: service accounts cannot perform a human-governed action.",
                    "human_principal_required",
                )
        selected = min(candidates)
        return self.evaluate(ctx, required_permission=selected)


def evaluate_principal_access(
    principal: ServerPrincipal,
    *,
    required_permission: str,
    object_type: str | None = None,
    object_id: str | None = None,
    action: str | None = None,
    prior_actions: list[tuple[str, str, str, str]] | None = None,
    tenant_id: str | None = None,
    organization_id: str | None = None,
    workspace_id: str | None = None,
    entity_id: str | None = None,
    period_id: str | None = None,
    region_id: str | None = None,
    data_classification: str | None = None,
    amount: Decimal | None = None,
    minimum_amount: Decimal | None = None,
    maximum_amount: Decimal | None = None,
    authorized_tenant_ids: frozenset[str] = frozenset(),
    authorized_organization_ids: frozenset[str] = frozenset(),
    authorized_workspace_ids: frozenset[str] = frozenset(),
    authorized_entity_ids: frozenset[str] = frozenset(),
    authorized_period_ids: frozenset[str] = frozenset(),
    authorized_region_ids: frozenset[str] = frozenset(),
    authorized_data_classifications: frozenset[str] = frozenset(),
    requested_field_names: frozenset[str] = frozenset(),
    authorized_field_names: frozenset[str] = frozenset(),
    object_owner_id: str | None = None,
    delegation_id: str | None = None,
    delegation_expires_at: datetime | None = None,
    evaluation_time: datetime | None = None,
) -> PolicyDecision:
    """Helper for evaluating ServerPrincipal authorization."""

    ctx = PolicyEvaluationContext(
        user_id=principal.user.id,
        username=principal.user.username,
        user_permissions=principal.permissions,
        principal_type=principal.principal_type,
        step_up_active=principal.step_up_active,
        step_up_enforced=True,
        tenant_id=tenant_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        period_id=period_id,
        region_id=region_id,
        data_classification=data_classification,
        amount=amount,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
        authorized_tenant_ids=authorized_tenant_ids,
        authorized_organization_ids=authorized_organization_ids,
        authorized_workspace_ids=authorized_workspace_ids,
        authorized_entity_ids=authorized_entity_ids,
        authorized_period_ids=authorized_period_ids,
        authorized_region_ids=authorized_region_ids,
        authorized_data_classifications=authorized_data_classifications,
        requested_field_names=requested_field_names,
        authorized_field_names=authorized_field_names,
        delegation_id=delegation_id,
        delegation_expires_at=delegation_expires_at,
        evaluation_time=evaluation_time,
        object_type=object_type,
        object_id=object_id,
        object_owner_id=object_owner_id,
        action=action,
        prior_actions=prior_actions or [],
    )
    engine = CentralPolicyEngine()
    return engine.evaluate(ctx, required_permission=required_permission)
