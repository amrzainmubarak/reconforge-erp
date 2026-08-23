"""Deployment-profile contracts for truthful mode selection."""

from reconforge.deployment.admission import (
    RegulatedAdmissionError,
    RegulatedAdmissionEvidence,
    verify_regulated_admission,
)
from reconforge.deployment.key_custody import (
    ManagedKeyManifest,
    ManagedKeyManifestError,
    verify_managed_key_manifest,
)
from reconforge.deployment.profiles import (
    DeploymentEdition,
    DeploymentProfile,
    DeploymentProfileError,
    DeploymentRuntimeFacts,
    deployment_profile,
    list_deployment_profiles,
    validate_deployment_profile,
)
from reconforge.deployment.readiness import (
    DeploymentReadinessError,
    DeploymentReadinessMatrix,
    load_deployment_readiness_matrix,
)
from reconforge.deployment.runtime_evidence import (
    DeploymentRuntimeEvidence,
    DeploymentRuntimeEvidenceError,
    verify_deployment_runtime_evidence,
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
    "DeploymentRuntimeEvidence",
    "DeploymentRuntimeEvidenceError",
    "verify_deployment_runtime_evidence",
    "DeploymentReadinessError",
    "DeploymentReadinessMatrix",
    "load_deployment_readiness_matrix",
    "ManagedKeyManifest",
    "ManagedKeyManifestError",
    "verify_managed_key_manifest",
    "RegulatedAdmissionError",
    "RegulatedAdmissionEvidence",
    "verify_regulated_admission",
]
