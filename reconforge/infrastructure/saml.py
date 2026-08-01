"""Strict SAML 2.0 Response verification through python3-saml/xmlsec."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconforge.auth.federation import FederationProvider, FederationRequest, VerifiedFederationAssertion

RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256_DIGEST = "http://www.w3.org/2001/04/xmlenc#sha256"


class SAMLVerificationError(ValueError):
    """Sanitized SAML verification failure."""


class SAMLProviderMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sp_entity_id: str = Field(min_length=1, max_length=2048)
    acs_url: str = Field(min_length=1, max_length=2048)
    idp_sso_url: str = Field(min_length=1, max_length=2048)
    idp_certificate_pem: str = Field(min_length=1, max_length=100_000)
    group_attribute: str = Field(default="groups", min_length=1, max_length=256)
    display_name_attribute: str | None = Field(default="displayName", max_length=256)
    email_attribute: str | None = Field(default="email", max_length=256)
    allowed_digest_algorithms: tuple[str, ...] = (SHA256_DIGEST,)

    @field_validator("acs_url", "idp_sso_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("SAML endpoints must be credential-free HTTPS URLs.")
        return value

    @field_validator("allowed_digest_algorithms")
    @classmethod
    def validate_digest_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) > 8 or len(set(values)) != len(values):
            raise ValueError("SAML digest allowlist is invalid.")
        return values

    @field_validator("idp_certificate_pem")
    @classmethod
    def validate_public_certificate(cls, value: str) -> str:
        if "PRIVATE KEY" in value:
            raise ValueError("SAML IdP material must contain a public certificate only.")
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives.asymmetric import rsa

            certificate = x509.load_pem_x509_certificate(value.encode("ascii"))
            public_key = certificate.public_key()
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("SAML IdP certificate is invalid.") from exc
        if isinstance(public_key, rsa.RSAPublicKey) and public_key.key_size < 2048:
            raise ValueError("SAML IdP RSA certificates require at least 2048 bits.")
        return value


class SAMLResponseVerifier:
    """Validate one signed SAML Response with fixed local IdP metadata."""

    def __init__(self, materials: dict[str, SAMLProviderMaterial]) -> None:
        self._materials = dict(materials)

    def verify(self, provider: FederationProvider, request: FederationRequest) -> VerifiedFederationAssertion:
        material = self._materials.get(provider.id)
        if provider.protocol != "saml" or material is None or request.request_id is None:
            raise SAMLVerificationError("SAML verification failed.")
        try:
            from onelogin.saml2.response import OneLogin_Saml2_Response
            from onelogin.saml2.settings import OneLogin_Saml2_Settings

            settings = OneLogin_Saml2_Settings(self._settings(provider, material))
            response = OneLogin_Saml2_Response(settings, request.encoded_assertion)
            if not response.is_valid(self._request_data(material.acs_url), request.request_id, raise_exceptions=True):
                raise SAMLVerificationError("SAML verification failed.")
            signatures = tuple(
                response.document.xpath("//*[local-name()='SignatureMethod']/@Algorithm")  # nosec B320
            )
            digests = tuple(response.document.xpath("//*[local-name()='DigestMethod']/@Algorithm"))  # nosec B320
            if len(signatures) != 1 or signatures[0] not in provider.allowed_algorithms:
                raise SAMLVerificationError("SAML verification failed.")
            if not digests or any(item not in material.allowed_digest_algorithms for item in digests):
                raise SAMLVerificationError("SAML verification failed.")
            issuers = tuple(response.get_issuers())
            if set(issuers) != {provider.issuer}:
                raise SAMLVerificationError("SAML verification failed.")
            audiences = tuple(response.get_audiences())
            if not set(audiences).intersection(provider.audiences):
                raise SAMLVerificationError("SAML verification failed.")
            issued_at = response.get_assertion_issue_instant()
            expires_at = response.get_assertion_not_on_or_after()
            assertion_id = response.get_assertion_id()
            subject = response.get_nameid()
            if not isinstance(issued_at, int) or not isinstance(expires_at, int):
                raise SAMLVerificationError("SAML verification failed.")
            if not isinstance(assertion_id, str) or not 1 <= len(assertion_id) <= 512:
                raise SAMLVerificationError("SAML verification failed.")
            if not isinstance(subject, str) or not 1 <= len(subject) <= 512:
                raise SAMLVerificationError("SAML verification failed.")
            attributes = response.get_attributes()
            groups = self._attribute_values(attributes, material.group_attribute, required=True, maximum_items=256)
            display_name = self._single_attribute(attributes, material.display_name_attribute, 256)
            email = self._single_attribute(attributes, material.email_attribute, 320)
            return VerifiedFederationAssertion(
                protocol="saml",
                issuer=provider.issuer,
                subject=subject,
                audiences=audiences,
                assertion_id=assertion_id,
                issued_at=datetime.fromtimestamp(issued_at, UTC),
                expires_at=datetime.fromtimestamp(expires_at, UTC),
                in_response_to=request.request_id,
                groups=groups,
                display_name=display_name,
                email=email,
                signature_verified=True,
                algorithm=signatures[0],
            )
        except SAMLVerificationError:
            raise
        except Exception as exc:
            raise SAMLVerificationError("SAML verification failed.") from exc

    @staticmethod
    def _settings(provider: FederationProvider, material: SAMLProviderMaterial) -> dict[str, Any]:
        return {
            "strict": True,
            "debug": False,
            "sp": {
                "entityId": material.sp_entity_id,
                "assertionConsumerService": {
                    "url": material.acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
            },
            "idp": {
                "entityId": provider.issuer,
                "singleSignOnService": {
                    "url": material.idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": material.idp_certificate_pem,
            },
            "security": {
                "wantMessagesSigned": True,
                "wantAssertionsSigned": False,
                "wantAssertionsEncrypted": False,
                "wantNameId": True,
                "wantNameIdEncrypted": False,
                "rejectDeprecatedAlgorithm": True,
                "signatureAlgorithm": provider.allowed_algorithms[0],
                "digestAlgorithm": material.allowed_digest_algorithms[0],
            },
        }

    @staticmethod
    def _request_data(acs_url: str) -> dict[str, object]:
        parsed = urlsplit(acs_url)
        return {
            "https": "on",
            "http_host": parsed.netloc,
            "script_name": parsed.path,
            "get_data": {},
            "post_data": {},
        }

    @staticmethod
    def _attribute_values(
        attributes: dict[str, list[str]], key: str, *, required: bool, maximum_items: int
    ) -> tuple[str, ...]:
        values = attributes.get(key, [])
        if (required and not values) or len(values) > maximum_items:
            raise SAMLVerificationError("SAML verification failed.")
        if any(not isinstance(item, str) or not 1 <= len(item) <= 256 for item in values):
            raise SAMLVerificationError("SAML verification failed.")
        return tuple(values)

    @classmethod
    def _single_attribute(cls, attributes: dict[str, list[str]], key: str | None, maximum: int) -> str | None:
        if key is None or key not in attributes:
            return None
        values = cls._attribute_values(attributes, key, required=False, maximum_items=1)
        if len(values) != 1 or len(values[0]) > maximum:
            raise SAMLVerificationError("SAML verification failed.")
        return values[0]
