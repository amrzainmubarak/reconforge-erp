"""Deterministic, read-only analysis of enterprise policy conflicts.

The analyzer is deliberately separate from policy enforcement.  It produces a
review artifact for a versioned set of grants; it never changes roles,
permissions, delegations, sessions, or route behavior.  Scope overlap is
fail-closed and every finding is digest-bound so a reviewer can replay the
same policy snapshot.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from reconforge.auth.policy import (
    PRIVILEGED_STEP_UP_PERMISSIONS,
    permission_requires_human,
)
from reconforge.auth.rbac import CONFLICTING_ACTIONS

POLICY_ANALYSIS_SCHEMA_VERSION = 1
POLICY_ANALYSIS_ALGORITHM_VERSION = "enterprise-policy-conflict-analysis-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_PERMISSION = re.compile(r"^[a-z][a-z0-9_.-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_SCOPE_AMOUNT_DIGITS = 128

PrincipalType = Literal["user", "service_account"]
GrantStatus = Literal["active", "revoked"]
ConflictSeverity = Literal["critical", "high", "medium"]
AnalysisStatus = Literal["clear", "conflicts"]


class PolicyAnalysisError(ValueError):
    """Raised when a policy-analysis request or result is invalid."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise PolicyAnalysisError(f"{field} is invalid.")
    return value.strip()


def _permission(value: object) -> str:
    if not isinstance(value, str) or not _PERMISSION.fullmatch(value.strip()):
        raise PolicyAnalysisError("Policy permission names are invalid.")
    return value.strip()


def _semver(value: object) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise PolicyAnalysisError("Policy version must use semantic versioning.")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyAnalysisError(f"{field} must be a timezone-aware ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PolicyAnalysisError(f"{field} must be a timezone-aware ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        raise PolicyAnalysisError(f"{field} must use whole-second timezone-aware precision.")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _canonical_scope_amount(value: object, field_name: str) -> str:
    """Validate and serialize one bounded, exact policy amount."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise PolicyAnalysisError(f"Policy {field_name} must be a finite Decimal.")
    digits = value.as_tuple().digits
    if len(digits) > _MAX_SCOPE_AMOUNT_DIGITS or abs(value.adjusted()) > _MAX_SCOPE_AMOUNT_DIGITS:
        raise PolicyAnalysisError(f"Policy {field_name} exceeds the bounded Decimal contract.")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0"}:
        rendered = "0"
    if len(rendered.lstrip("-")) > _MAX_SCOPE_AMOUNT_DIGITS + 1:
        raise PolicyAnalysisError(f"Policy {field_name} exceeds the bounded Decimal contract.")
    return rendered


@dataclass(frozen=True)
class PolicyScope:
    """Tenant-bound scope; empty dimensions mean wildcard within the tenant."""

    tenant_id: str
    workspace_id: str | None = None
    entity_ids: frozenset[str] = frozenset()
    period_ids: frozenset[str] = frozenset()
    region_ids: frozenset[str] = frozenset()
    data_classifications: frozenset[str] = frozenset()
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "Policy tenant"))
        if self.workspace_id is not None:
            object.__setattr__(self, "workspace_id", _identifier(self.workspace_id, "Policy workspace"))
        for field_name in ("entity_ids", "period_ids", "region_ids", "data_classifications"):
            values = getattr(self, field_name)
            if not isinstance(values, frozenset) or any(
                not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()) for value in values
            ):
                raise PolicyAnalysisError(f"Policy {field_name} must contain bounded identifiers.")
            object.__setattr__(self, field_name, frozenset(value.strip() for value in values))
        for field_name in ("minimum_amount", "maximum_amount"):
            value = getattr(self, field_name)
            if value is not None:
                _canonical_scope_amount(value, field_name)
        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.minimum_amount > self.maximum_amount
        ):
            raise PolicyAnalysisError("Policy minimum_amount cannot exceed maximum_amount.")

    @property
    def is_unscoped_privileged(self) -> bool:
        return self.workspace_id is None and not any(
            (
                self.entity_ids,
                self.period_ids,
                self.region_ids,
                self.data_classifications,
                self.minimum_amount is not None,
                self.maximum_amount is not None,
            )
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "data_classifications": sorted(self.data_classifications),
            "entity_ids": sorted(self.entity_ids),
            "period_ids": sorted(self.period_ids),
            "region_ids": sorted(self.region_ids),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
        }
        # Omit new optional bounds when absent so legacy v1 request digests and
        # CLI payloads remain byte-for-byte compatible.
        if self.minimum_amount is not None:
            payload["minimum_amount"] = _canonical_scope_amount(self.minimum_amount, "minimum_amount")
        if self.maximum_amount is not None:
            payload["maximum_amount"] = _canonical_scope_amount(self.maximum_amount, "maximum_amount")
        return payload


def _dimension_overlaps(left: frozenset[str], right: frozenset[str]) -> bool:
    return not left or not right or bool(left.intersection(right))


def _scopes_overlap(left: PolicyScope, right: PolicyScope) -> bool:
    if left.tenant_id != right.tenant_id:
        return False
    if left.workspace_id is not None and right.workspace_id is not None and left.workspace_id != right.workspace_id:
        return False
    if (
        left.maximum_amount is not None
        and right.minimum_amount is not None
        and left.maximum_amount < right.minimum_amount
    ):
        return False
    if (
        right.maximum_amount is not None
        and left.minimum_amount is not None
        and right.maximum_amount < left.minimum_amount
    ):
        return False
    return all(
        _dimension_overlaps(getattr(left, field_name), getattr(right, field_name))
        for field_name in ("entity_ids", "period_ids", "region_ids", "data_classifications")
    )


@dataclass(frozen=True)
class PolicyGrant:
    """One versioned role/permission grant in a policy snapshot."""

    grant_id: str
    principal_id: str
    principal_type: PrincipalType
    role_id: str
    scope: PolicyScope
    permissions: frozenset[str]
    status: GrantStatus = "active"

    def __post_init__(self) -> None:
        for field_name in ("grant_id", "principal_id", "role_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), f"Policy {field_name}"))
        if self.principal_type not in {"user", "service_account"}:
            raise PolicyAnalysisError("Policy principal type is invalid.")
        if not isinstance(self.permissions, frozenset) or not self.permissions:
            raise PolicyAnalysisError("Policy grants require at least one permission.")
        object.__setattr__(self, "permissions", frozenset(_permission(value) for value in self.permissions))
        if self.status not in {"active", "revoked"}:
            raise PolicyAnalysisError("Policy grant status is invalid.")

    def to_dict(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "permissions": sorted(self.permissions),
            "principal_id": self.principal_id,
            "principal_type": self.principal_type,
            "role_id": self.role_id,
            "scope": self.scope.to_dict(),
            "status": self.status,
        }


@dataclass(frozen=True)
class PolicyAnalysisRequest:
    """Approved, replayable input snapshot for conflict analysis."""

    policy_id: str
    policy_version: str
    grants: tuple[PolicyGrant, ...]
    require_scoped_privileged: bool
    prepared_by: str
    prepared_at: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Policy ID"))
        object.__setattr__(self, "policy_version", _semver(self.policy_version))
        if not isinstance(self.grants, tuple) or len(self.grants) > 10000:
            raise PolicyAnalysisError("Policy analysis accepts at most 10000 grants.")
        grant_ids: set[str] = set()
        for grant in self.grants:
            if not isinstance(grant, PolicyGrant):
                raise PolicyAnalysisError("Policy grants must use the typed grant contract.")
            if grant.grant_id in grant_ids:
                raise PolicyAnalysisError("Policy grant IDs must be unique.")
            grant_ids.add(grant.grant_id)
        object.__setattr__(self, "grants", tuple(sorted(self.grants, key=lambda grant: grant.grant_id)))
        if not isinstance(self.require_scoped_privileged, bool):
            raise PolicyAnalysisError("Policy scoped-privileged requirement must be boolean.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Policy preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Policy approver"))
        if self.prepared_by.casefold() == self.approved_by.casefold():
            raise PolicyAnalysisError("Policy analysis preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Policy preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Policy approval timestamp")
        if approved_at > prepared_at:
            raise PolicyAnalysisError("Policy approval must precede analysis preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "grants": [grant.to_dict() for grant in self.grants],
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "require_scoped_privileged": self.require_scoped_privileged,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PolicyConflictFinding:
    """One deterministic policy conflict finding."""

    code: str
    severity: ConflictSeverity
    principal_id: str
    grant_ids: tuple[str, ...]
    permissions: tuple[str, ...]
    scope_digests: tuple[str, ...]
    reason: str

    @property
    def conflict_id(self) -> str:
        return _digest(self._unsigned())

    def _unsigned(self) -> dict[str, object]:
        return {
            "code": self.code,
            "grant_ids": list(self.grant_ids),
            "permissions": list(self.permissions),
            "principal_id": self.principal_id,
            "reason": self.reason,
            "scope_digests": list(self.scope_digests),
            "severity": self.severity,
        }

    def to_dict(self) -> dict[str, object]:
        return {"conflict_id": self.conflict_id, **self._unsigned()}


@dataclass(frozen=True)
class PolicyAnalysisResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    policy_id: str
    policy_version: str
    status: AnalysisStatus
    findings: tuple[PolicyConflictFinding, ...]
    active_grant_count: int
    revoked_grant_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "active_grant_count": self.active_grant_count,
            "algorithm_version": self.algorithm_version,
            "findings": [finding.to_dict() for finding in self.findings],
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "revoked_grant_count": self.revoked_grant_count,
            "schema_version": self.schema_version,
            "status": self.status,
        }


def _conflicting_permission_pair(left: str, right: str) -> tuple[str, str] | None:
    left_object, _, left_action = left.rpartition(".")
    right_object, _, right_action = right.rpartition(".")
    if not left_object or left_object != right_object or left_action == right_action:
        return None
    if right_action in CONFLICTING_ACTIONS.get(left_action, set()) or left_action in CONFLICTING_ACTIONS.get(right_action, set()):
        return (min(left, right), max(left, right))
    return None


def _finding(
    *,
    code: str,
    severity: ConflictSeverity,
    principal_id: str,
    grants: tuple[PolicyGrant, ...],
    permissions: tuple[str, ...],
    reason: str,
) -> PolicyConflictFinding:
    return PolicyConflictFinding(
        code=code,
        severity=severity,
        principal_id=principal_id,
        grant_ids=tuple(sorted(grant.grant_id for grant in grants)),
        permissions=tuple(sorted(set(permissions))),
        scope_digests=tuple(sorted({grant.scope.digest for grant in grants})),
        reason=reason,
    )


def analyze_policy_conflicts(request: PolicyAnalysisRequest) -> PolicyAnalysisResult:
    """Analyze a policy snapshot without mutating or enforcing it."""

    if not isinstance(request, PolicyAnalysisRequest):
        raise PolicyAnalysisError("A typed policy analysis request is required.")
    active = tuple(grant for grant in request.grants if grant.status == "active")
    revoked = tuple(grant for grant in request.grants if grant.status == "revoked")
    findings: dict[str, PolicyConflictFinding] = {}
    by_principal: dict[str, list[PolicyGrant]] = {}
    for grant in active:
        by_principal.setdefault(grant.principal_id, []).append(grant)
        human_permissions = tuple(sorted(permission for permission in grant.permissions if permission_requires_human(permission)))
        if grant.principal_type == "service_account" and human_permissions:
            result = _finding(
                code="service_account_human_permission",
                severity="critical",
                principal_id=grant.principal_id,
                grants=(grant,),
                permissions=human_permissions,
                reason="A service account holds a permission reserved for a human-governed action.",
            )
            findings[result.conflict_id] = result
        privileged = tuple(sorted(permission for permission in grant.permissions if permission in PRIVILEGED_STEP_UP_PERMISSIONS))
        if request.require_scoped_privileged and privileged and grant.scope.is_unscoped_privileged:
            result = _finding(
                code="unscoped_privileged_grant",
                severity="high",
                principal_id=grant.principal_id,
                grants=(grant,),
                permissions=privileged,
                reason="A privileged permission is granted without a workspace or bounded resource scope.",
            )
            findings[result.conflict_id] = result

    for principal_id, grants in sorted(by_principal.items()):
        for left, right in itertools.combinations(grants, 2):
            if not _scopes_overlap(left.scope, right.scope):
                continue
            duplicate_permissions = tuple(sorted(left.permissions.intersection(right.permissions)))
            if duplicate_permissions:
                result = _finding(
                    code="duplicate_active_grant",
                    severity="medium",
                    principal_id=principal_id,
                    grants=(left, right),
                    permissions=duplicate_permissions,
                    reason="The same principal has duplicate active permission grants over overlapping scopes.",
                )
                findings[result.conflict_id] = result
            for left_permission, right_permission in itertools.combinations(
                sorted(left.permissions.union(right.permissions)), 2
            ):
                pair = _conflicting_permission_pair(left_permission, right_permission)
                if pair is None:
                    continue
                result = _finding(
                    code="sod_permission_overlap",
                    severity="high",
                    principal_id=principal_id,
                    grants=(left, right),
                    permissions=pair,
                    reason="One principal can reach conflicting prepare/review/submit/approve duties over overlapping scopes.",
                )
                findings[result.conflict_id] = result
        for grant in grants:
            for left_permission, right_permission in itertools.combinations(sorted(grant.permissions), 2):
                pair = _conflicting_permission_pair(left_permission, right_permission)
                if pair is None:
                    continue
                result = _finding(
                    code="sod_permission_overlap",
                    severity="high",
                    principal_id=principal_id,
                    grants=(grant,),
                    permissions=pair,
                    reason="One grant contains conflicting prepare/review/submit/approve duties.",
                )
                findings[result.conflict_id] = result

    severity_order = {"critical": 0, "high": 1, "medium": 2}
    ordered_findings = tuple(
        sorted(
            findings.values(),
            key=lambda finding: (
                severity_order[finding.severity],
                finding.code,
                finding.principal_id,
                finding.conflict_id,
            ),
        )
    )
    unsigned: dict[str, object] = {
        "active_grant_count": len(active),
        "algorithm_version": POLICY_ANALYSIS_ALGORITHM_VERSION,
        "findings": [finding.to_dict() for finding in ordered_findings],
        "policy_id": request.policy_id,
        "policy_version": request.policy_version,
        "request_digest": request.digest,
        "revoked_grant_count": len(revoked),
        "schema_version": POLICY_ANALYSIS_SCHEMA_VERSION,
        "status": "conflicts" if ordered_findings else "clear",
    }
    return PolicyAnalysisResult(
        schema_version=POLICY_ANALYSIS_SCHEMA_VERSION,
        algorithm_version=POLICY_ANALYSIS_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(unsigned),
        policy_id=request.policy_id,
        policy_version=request.policy_version,
        status="conflicts" if ordered_findings else "clear",
        findings=ordered_findings,
        active_grant_count=len(active),
        revoked_grant_count=len(revoked),
    )


def verify_policy_analysis_payload(payload: object) -> dict[str, object]:
    """Verify result digest and internal finding identity without policy mutation."""

    if not isinstance(payload, dict):
        raise PolicyAnalysisError("Policy analysis result must be an object.")
    expected_digest = payload.get("result_digest")
    if not isinstance(expected_digest, str) or not _SHA256.fullmatch(expected_digest):
        raise PolicyAnalysisError("Policy analysis result digest is missing or invalid.")
    unsigned = dict(payload)
    unsigned.pop("result_digest", None)
    if _digest(unsigned) != expected_digest:
        raise PolicyAnalysisError("Policy analysis result digest mismatch.")
    if payload.get("schema_version") != POLICY_ANALYSIS_SCHEMA_VERSION:
        raise PolicyAnalysisError("Policy analysis schema version is unsupported.")
    if payload.get("algorithm_version") != POLICY_ANALYSIS_ALGORITHM_VERSION:
        raise PolicyAnalysisError("Policy analysis algorithm version is unsupported.")
    if payload.get("status") not in {"clear", "conflicts"}:
        raise PolicyAnalysisError("Policy analysis status is invalid.")
    if not isinstance(payload.get("request_digest"), str) or not _SHA256.fullmatch(payload["request_digest"]):
        raise PolicyAnalysisError("Policy analysis request digest is invalid.")
    findings = payload.get("findings")
    if not isinstance(findings, list) or len(findings) > 10000:
        raise PolicyAnalysisError("Policy analysis findings are invalid.")
    seen: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise PolicyAnalysisError("Policy analysis finding is invalid.")
        required = {"code", "conflict_id", "grant_ids", "permissions", "principal_id", "reason", "scope_digests", "severity"}
        if set(finding) != required:
            raise PolicyAnalysisError("Policy analysis finding fields are not exactly declared.")
        conflict_id = finding["conflict_id"]
        if not isinstance(conflict_id, str) or not _SHA256.fullmatch(conflict_id) or conflict_id in seen:
            raise PolicyAnalysisError("Policy analysis conflict IDs are invalid or duplicated.")
        seen.add(conflict_id)
        if finding["severity"] not in {"critical", "high", "medium"} or not isinstance(finding["code"], str):
            raise PolicyAnalysisError("Policy analysis finding classification is invalid.")
        if not isinstance(finding["grant_ids"], list) or not all(isinstance(item, str) for item in finding["grant_ids"]):
            raise PolicyAnalysisError("Policy analysis finding grant IDs are invalid.")
        if not isinstance(finding["permissions"], list) or not all(isinstance(item, str) for item in finding["permissions"]):
            raise PolicyAnalysisError("Policy analysis finding permissions are invalid.")
        if not isinstance(finding["scope_digests"], list) or not all(
            isinstance(item, str) and _SHA256.fullmatch(item) for item in finding["scope_digests"]
        ):
            raise PolicyAnalysisError("Policy analysis finding scope digests are invalid.")
        unsigned_finding = dict(finding)
        unsigned_finding.pop("conflict_id")
        if _digest(unsigned_finding) != conflict_id:
            raise PolicyAnalysisError("Policy analysis conflict ID mismatch.")
    active_count = payload.get("active_grant_count")
    revoked_count = payload.get("revoked_grant_count")
    if not isinstance(active_count, int) or isinstance(active_count, bool) or active_count < 0:
        raise PolicyAnalysisError("Policy analysis active count is invalid.")
    if not isinstance(revoked_count, int) or isinstance(revoked_count, bool) or revoked_count < 0:
        raise PolicyAnalysisError("Policy analysis revoked count is invalid.")
    if (payload["status"] == "clear") != (len(findings) == 0):
        raise PolicyAnalysisError("Policy analysis status does not match findings.")
    return dict(payload)


__all__ = [
    "POLICY_ANALYSIS_ALGORITHM_VERSION",
    "POLICY_ANALYSIS_SCHEMA_VERSION",
    "PolicyAnalysisError",
    "PolicyAnalysisRequest",
    "PolicyAnalysisResult",
    "PolicyConflictFinding",
    "PolicyGrant",
    "PolicyScope",
    "analyze_policy_conflicts",
    "verify_policy_analysis_payload",
]
