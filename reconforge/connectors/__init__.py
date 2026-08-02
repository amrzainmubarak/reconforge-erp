"""Safe, manifest-driven connector SDK contracts."""

from reconforge.connectors.manifest import (
    AuthenticationMethod,
    ConnectorCapability,
    ConnectorKind,
    ConnectorManifest,
    DataClassification,
    RetryPolicy,
    SupportLevel,
)
from reconforge.connectors.package import (
    ConnectorPackageError,
    PublisherKeyStatus,
    TrustedPublisherKey,
    TrustedPublisherRegistry,
    load_verified_package,
)
from reconforge.connectors.rest_reference import (
    REFERENCE_REST_MANIFEST,
    ReferenceRestConnector,
    ReferenceRestPage,
    ReferenceRestRead,
    ReferenceRestRecord,
    reference_rest_registration,
)

__all__ = [
    "AuthenticationMethod",
    "ConnectorCapability",
    "ConnectorKind",
    "ConnectorManifest",
    "ConnectorPackageError",
    "REFERENCE_REST_MANIFEST",
    "ReferenceRestConnector",
    "ReferenceRestPage",
    "ReferenceRestRead",
    "ReferenceRestRecord",
    "reference_rest_registration",
    "DataClassification",
    "PublisherKeyStatus",
    "RetryPolicy",
    "SupportLevel",
    "TrustedPublisherKey",
    "TrustedPublisherRegistry",
    "load_verified_package",
]
