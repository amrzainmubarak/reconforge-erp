"""Bounded operator-owned federation configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from reconforge.auth.federation import FederationProvider, FederationVerifier
from reconforge.infrastructure.oidc import OIDCStaticJWKSVerifier
from reconforge.infrastructure.saml import SAMLProviderMaterial, SAMLResponseVerifier
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, read_json_document

FEDERATION_CONFIG_SCHEMA_VERSION = "1.0"
FEDERATION_CONFIG_POLICY = StructuredDocumentPolicy(
    max_file_bytes=1_048_576,
    max_nodes=20_000,
    max_depth=16,
    max_collection_items=2_000,
    max_scalar_characters=100_000,
    max_yaml_aliases=1,
)


class FederationConfigurationError(ValueError):
    """Safe operator configuration rejection without material disclosure."""


class _ConfigurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CommonProviderConfiguration(_ConfigurationModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    issuer: str = Field(min_length=1, max_length=2048)
    audiences: tuple[str, ...] = Field(min_length=1, max_length=16)
    allowed_algorithms: tuple[str, ...] = Field(min_length=1, max_length=8)
    group_role_mapping: dict[str, str] = Field(default_factory=dict)
    allowed_roles: frozenset[str] = Field(min_length=1, max_length=32)
    enabled: bool = True
    network_required: bool = True

    def provider(self, protocol: Literal["oidc", "saml"]) -> FederationProvider:
        return FederationProvider(
            id=self.id,
            protocol=protocol,
            issuer=self.issuer,
            audiences=self.audiences,
            allowed_algorithms=self.allowed_algorithms,
            group_role_mapping=self.group_role_mapping,
            allowed_roles=self.allowed_roles,
            enabled=self.enabled,
            network_required=self.network_required,
        )


class OIDCProviderConfiguration(_CommonProviderConfiguration):
    protocol: Literal["oidc"]
    jwks: dict[str, object]


class SAMLProviderConfiguration(_CommonProviderConfiguration):
    protocol: Literal["saml"]
    material: SAMLProviderMaterial


ProviderConfiguration = Annotated[
    OIDCProviderConfiguration | SAMLProviderConfiguration,
    Field(discriminator="protocol"),
]


class FederationConfiguration(_ConfigurationModel):
    schema_version: Literal["1.0"] = "1.0"
    air_gap_mode: bool = False
    providers: tuple[ProviderConfiguration, ...] = Field(min_length=1, max_length=16)

    @field_validator("providers")
    @classmethod
    def validate_unique_provider_ids(
        cls, providers: tuple[ProviderConfiguration, ...]
    ) -> tuple[ProviderConfiguration, ...]:
        identifiers = [provider.id for provider in providers]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Federation provider identifiers must be unique.")
        return providers

    @model_validator(mode="after")
    def validate_enabled_provider(self) -> FederationConfiguration:
        if not any(provider.enabled for provider in self.providers):
            raise ValueError("Federation configuration requires an enabled provider.")
        return self


@dataclass(frozen=True)
class FederationRuntimeConfiguration:
    providers: dict[str, FederationProvider]
    verifiers: dict[str, FederationVerifier]
    air_gap_mode: bool


def load_federation_runtime(path: Path | str) -> FederationRuntimeConfiguration:
    """Load one bounded JSON file and instantiate reviewed protocol adapters."""

    try:
        document = read_json_document(path, policy=FEDERATION_CONFIG_POLICY)
        configuration = FederationConfiguration.model_validate(document)
        providers: dict[str, FederationProvider] = {}
        oidc_jwks: dict[str, dict[str, object]] = {}
        saml_materials: dict[str, SAMLProviderMaterial] = {}
        for configured in configuration.providers:
            providers[configured.id] = configured.provider(configured.protocol)
            if isinstance(configured, OIDCProviderConfiguration):
                oidc_jwks[configured.id] = configured.jwks
            else:
                saml_materials[configured.id] = configured.material
        verifiers: dict[str, FederationVerifier] = {}
        if oidc_jwks:
            verifiers["oidc"] = OIDCStaticJWKSVerifier(oidc_jwks)
        if saml_materials:
            verifiers["saml"] = SAMLResponseVerifier(saml_materials)
        return FederationRuntimeConfiguration(providers, verifiers, configuration.air_gap_mode)
    except (StructuredDocumentError, ValidationError, ValueError, TypeError) as exc:
        raise FederationConfigurationError("Federation configuration is invalid.") from exc
