"""Deployment-profile contracts for truthful mode selection."""

from reconforge.deployment.profiles import (
    DeploymentEdition,
    DeploymentProfile,
    DeploymentProfileError,
    DeploymentRuntimeFacts,
    deployment_profile,
    list_deployment_profiles,
    validate_deployment_profile,
)
from reconforge.deployment.worker_permissions import (
    WorkerPermissionManifest,
    WorkerPermissionManifestError,
    verify_worker_permission_manifest,
)

__all__ = [
    "DeploymentEdition",
    "DeploymentProfile",
    "DeploymentProfileError",
    "DeploymentRuntimeFacts",
    "deployment_profile",
    "list_deployment_profiles",
    "validate_deployment_profile",
    "WorkerPermissionManifest",
    "WorkerPermissionManifestError",
    "verify_worker_permission_manifest",
]
