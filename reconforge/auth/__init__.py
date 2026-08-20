"""Local users, password hashing, RBAC, and SoD primitives."""

from __future__ import annotations

from reconforge.auth.delegations import DelegationGrant, DelegationValidationError
from reconforge.auth.federation import (
    FederatedPrincipal,
    FederationError,
    FederationProvider,
    FederationRequest,
    FederationService,
    VerifiedFederationAssertion,
)
from reconforge.auth.models import LocalPermission, LocalRole, LocalUser, RolePermission, SoDAction
from reconforge.auth.passwords import PasswordHash, hash_password, verify_password
from reconforge.auth.policy import (
    CentralPolicyEngine,
    PolicyDecision,
    PolicyEvaluationContext,
    evaluate_principal_access,
)
from reconforge.auth.policy_analysis import (
    POLICY_ANALYSIS_ALGORITHM_VERSION,
    POLICY_ANALYSIS_SCHEMA_VERSION,
    PolicyAnalysisError,
    PolicyAnalysisRequest,
    PolicyAnalysisResult,
    PolicyConflictFinding,
    PolicyGrant,
    PolicyScope,
    analyze_policy_conflicts,
    verify_policy_analysis_payload,
)
from reconforge.auth.rbac import (
    SoDCheckResult,
    check_object_action_permission,
    check_sod_conflict,
    has_permission,
    required_permission_for_action,
    same_actor,
)
from reconforge.auth.repositories import AuthRepositoryError, RoleRepository, UserRepository
from reconforge.auth.service import AuthServiceError, LocalAuthService

__all__ = [
    "AuthRepositoryError",
    "AuthServiceError",
    "CentralPolicyEngine",
    "POLICY_ANALYSIS_ALGORITHM_VERSION",
    "POLICY_ANALYSIS_SCHEMA_VERSION",
    "DelegationGrant",
    "DelegationValidationError",
    "FederatedPrincipal",
    "FederationError",
    "FederationProvider",
    "FederationRequest",
    "FederationService",
    "LocalAuthService",
    "LocalPermission",
    "LocalRole",
    "LocalUser",
    "PasswordHash",
    "PolicyDecision",
    "PolicyAnalysisError",
    "PolicyAnalysisRequest",
    "PolicyAnalysisResult",
    "PolicyConflictFinding",
    "PolicyEvaluationContext",
    "PolicyGrant",
    "PolicyScope",
    "RolePermission",
    "RoleRepository",
    "SoDAction",
    "SoDCheckResult",
    "UserRepository",
    "VerifiedFederationAssertion",
    "check_object_action_permission",
    "check_sod_conflict",
    "analyze_policy_conflicts",
    "evaluate_principal_access",
    "has_permission",
    "hash_password",
    "required_permission_for_action",
    "same_actor",
    "verify_password",
    "verify_policy_analysis_payload",
]
