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

__all__ = [
    "AuthenticationMethod",
    "ConnectorCapability",
    "ConnectorKind",
    "ConnectorManifest",
    "ConnectorPackageError",
    "DataClassification",
    "PublisherKeyStatus",
    "RetryPolicy",
    "SupportLevel",
    "TrustedPublisherKey",
    "TrustedPublisherRegistry",
    "load_verified_package",
]
