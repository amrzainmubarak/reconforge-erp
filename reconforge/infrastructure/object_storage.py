"""Optional S3-compatible object storage for evidence and report artifacts.

Local workflows continue to write evidence to the operator-selected filesystem
by default.  This adapter is an explicit server boundary for S3-compatible
providers, including AWS S3 and self-hosted implementations such as MinIO.

Object keys are tenant-separated, every upload carries a SHA-256 metadata
checksum, downloads verify that checksum, and presigned URLs are bounded.  Raw
local paths and bearer credentials are never placed in object metadata by this
module.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

from reconforge.infrastructure.postgres import normalize_scope_id

_BUCKET_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,61})[a-z0-9]$")
_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_OBJECT_METADATA_KEY_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
_OBJECT_LOCK_MODES = {"GOVERNANCE", "COMPLIANCE"}


class ObjectStorageConfigurationError(ValueError):
    """Raised when object-storage configuration or object keys are unsafe."""


class ObjectStorageUnavailableError(RuntimeError):
    """Raised when the optional boto3 driver is not installed."""


class ObjectStorageOperationError(RuntimeError):
    """Raised when the storage provider cannot complete an operation."""


class ObjectStorageNotFoundError(ObjectStorageOperationError):
    """Raised when an object does not exist."""


class ObjectStorageIntegrityError(ObjectStorageOperationError):
    """Raised when stored content does not match its recorded checksum."""


@dataclass(frozen=True)
class ObjectStorageSettings:
    """Secure defaults for an S3-compatible object-storage endpoint."""

    bucket: str
    endpoint_url: str | None = field(default=None, repr=False)
    region: str = "us-east-1"
    key_prefix: str = "reconforge"
    presign_expiry_seconds: int = 600
    require_tls: bool = True
    server_side_encryption: str | None = "AES256"
    object_lock_mode: str | None = None
    allow_delete: bool = False

    def __post_init__(self) -> None:
        bucket = self.bucket.strip().lower()
        if bucket != self.bucket or not _BUCKET_PATTERN.fullmatch(bucket):
            raise ObjectStorageConfigurationError("Object-storage bucket name is invalid.")
        if self.endpoint_url is not None:
            parsed = urlsplit(self.endpoint_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ObjectStorageConfigurationError("Object-storage endpoint must be an HTTP(S) URL.")
            if self.require_tls and parsed.scheme != "https":
                raise ObjectStorageConfigurationError("Object-storage TLS is required; use an https:// endpoint.")
        if self.key_prefix and not _PREFIX_PATTERN.fullmatch(self.key_prefix):
            raise ObjectStorageConfigurationError("Object-storage key prefix contains unsafe characters.")
        if not self.region.strip() or self.presign_expiry_seconds <= 0:
            raise ObjectStorageConfigurationError("Object-storage region and presign expiry must be valid.")
        if self.server_side_encryption not in {None, "AES256", "aws:kms"}:
            raise ObjectStorageConfigurationError("Object-storage encryption must be AES256 or aws:kms.")
        if self.object_lock_mode is not None and self.object_lock_mode.upper() not in _OBJECT_LOCK_MODES:
            raise ObjectStorageConfigurationError("Object-lock mode must be GOVERNANCE or COMPLIANCE.")


def _load_boto3() -> ModuleType:
    try:
        return importlib.import_module("boto3")
    except ImportError as exc:
        raise ObjectStorageUnavailableError(
            "S3-compatible storage support is optional. Install the server extra with "
            "`pip install 'reconforge-erp[server]'`."
        ) from exc


class ObjectStorageConnectionFactory:
    """Create one lazy boto3 S3 client without storing credentials in settings."""

    def __init__(self, settings: ObjectStorageSettings) -> None:
        self.settings = settings
        self._client: Any | None = None

    def client(self) -> Any:
        """Return a cached S3 client, loading boto3 only on first use."""

        if self._client is None:
            boto3 = _load_boto3()
            self._client = boto3.client(
                "s3",
                region_name=self.settings.region,
                endpoint_url=self.settings.endpoint_url,
            )
        return self._client

    def close(self) -> None:
        """Close the client when the provider exposes a close method."""

        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None


@dataclass(frozen=True)
class StoredObject:
    """Downloaded object plus verified integrity and provenance metadata."""

    key: str
    content: bytes
    sha256: str
    content_type: str
    metadata: dict[str, str]
    version_id: str | None = None


class S3ObjectStore:
    """Tenant-scoped S3-compatible artifact store."""

    def __init__(self, connection_factory: ObjectStorageConnectionFactory) -> None:
        self.connection_factory = connection_factory
        self.settings = connection_factory.settings

    @staticmethod
    def _object_name(object_name: str) -> str:
        raw = str(object_name or "").replace("\\", "/")
        parts = raw.split("/")
        if not raw or raw.startswith("/") or any(not part or part in {".", ".."} for part in parts):
            raise ObjectStorageConfigurationError("Object name must be a relative non-traversing path.")
        if any(any(ord(character) < 32 for character in part) for part in parts):
            raise ObjectStorageConfigurationError("Object name contains control characters.")
        return "/".join(parts)

    def key_for(self, tenant_id: str, object_name: str) -> str:
        """Return a deterministic tenant-separated key."""

        tenant = normalize_scope_id(tenant_id)
        relative_name = self._object_name(object_name)
        prefix = f"{self.settings.key_prefix}/" if self.settings.key_prefix else ""
        return f"{prefix}tenant/{tenant}/{relative_name}"

    @staticmethod
    def _metadata(metadata: Mapping[str, object] | None, *, tenant_id: str, digest: str) -> dict[str, str]:
        result = {"reconforge-sha256": digest, "reconforge-tenant": tenant_id}
        for raw_key, raw_value in (metadata or {}).items():
            key = str(raw_key).strip().lower()
            if not _OBJECT_METADATA_KEY_PATTERN.fullmatch(key) or key.startswith("reconforge-"):
                raise ObjectStorageConfigurationError("Object metadata key is invalid or reserved.")
            value = str(raw_value)
            if any(ord(character) < 32 for character in value):
                raise ObjectStorageConfigurationError("Object metadata contains control characters.")
            result[key] = value
        return result

    def _call(self, operation: Any) -> Any:
        try:
            return operation(self.connection_factory.client())
        except (ObjectStorageConfigurationError, ObjectStorageIntegrityError, ObjectStorageNotFoundError):
            raise
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
            if str(error_code) in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStorageNotFoundError("Object was not found.") from exc
            raise ObjectStorageOperationError("Object-storage operation failed.") from exc

    def put_bytes(
        self,
        tenant_id: str,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredObject:
        """Upload immutable evidence bytes with a recorded SHA-256 checksum."""

        if not isinstance(content, bytes):
            raise ObjectStorageConfigurationError("Object content must be bytes.")
        if not content_type.strip() or any(ord(character) < 32 for character in content_type):
            raise ObjectStorageConfigurationError("Object content type is invalid.")
        tenant = normalize_scope_id(tenant_id)
        key = self.key_for(tenant, object_name)
        digest = hashlib.sha256(content).hexdigest()
        object_metadata = self._metadata(metadata, tenant_id=tenant, digest=digest)
        put_kwargs: dict[str, object] = {
            "Bucket": self.settings.bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "Metadata": object_metadata,
        }
        if self.settings.server_side_encryption is not None:
            put_kwargs["ServerSideEncryption"] = self.settings.server_side_encryption
        if retention_until is not None:
            if retention_until.tzinfo is None:
                raise ObjectStorageConfigurationError("Retention timestamp must be timezone-aware.")
            if retention_until <= datetime.now(UTC):
                raise ObjectStorageConfigurationError("Retention timestamp must be in the future.")
            if self.settings.object_lock_mode is None:
                raise ObjectStorageConfigurationError("Retention requires an object-lock mode in configuration.")
            put_kwargs["ObjectLockMode"] = self.settings.object_lock_mode.upper()
            put_kwargs["ObjectLockRetainUntilDate"] = retention_until.astimezone(UTC)
            object_metadata["reconforge-retain-until"] = retention_until.astimezone(UTC).isoformat()
        response = self._call(lambda client: client.put_object(**put_kwargs))
        return StoredObject(
            key=key,
            content=content,
            sha256=digest,
            content_type=content_type,
            metadata=object_metadata,
            version_id=str(response.get("VersionId")) if response.get("VersionId") is not None else None,
        )

    def get_bytes(self, tenant_id: str, object_name: str) -> StoredObject:
        """Download and verify one tenant-scoped object."""

        key = self.key_for(tenant_id, object_name)
        response = self._call(lambda client: client.get_object(Bucket=self.settings.bucket, Key=key))
        body = response.get("Body")
        if body is None or not callable(getattr(body, "read", None)):
            raise ObjectStorageOperationError("Object-storage response did not contain a readable body.")
        content = body.read()
        close = getattr(body, "close", None)
        if callable(close):
            close()
        if not isinstance(content, bytes):
            raise ObjectStorageOperationError("Object-storage response body was not bytes.")
        digest = hashlib.sha256(content).hexdigest()
        metadata = {str(key).lower(): str(value) for key, value in (response.get("Metadata") or {}).items()}
        expected = metadata.get("reconforge-sha256")
        if expected is not None and expected != digest:
            raise ObjectStorageIntegrityError("Object checksum does not match its recorded SHA-256.")
        return StoredObject(
            key=key,
            content=content,
            sha256=digest,
            content_type=str(response.get("ContentType") or "application/octet-stream"),
            metadata=metadata,
            version_id=str(response.get("VersionId")) if response.get("VersionId") is not None else None,
        )

    def presigned_get_url(self, tenant_id: str, object_name: str, *, expires_in_seconds: int | None = None) -> str:
        """Create a bounded GET URL for a tenant-scoped object."""

        expiry = expires_in_seconds if expires_in_seconds is not None else self.settings.presign_expiry_seconds
        if expiry <= 0 or expiry > 7 * 24 * 60 * 60:
            raise ObjectStorageConfigurationError("Presigned URL expiry must be between 1 second and 7 days.")
        key = self.key_for(tenant_id, object_name)
        url = self._call(
            lambda client: client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.settings.bucket, "Key": key},
                ExpiresIn=expiry,
                HttpMethod="GET",
            )
        )
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ObjectStorageOperationError("Object-storage provider returned an invalid signed URL.")
        return url

    def delete(self, tenant_id: str, object_name: str) -> None:
        """Delete an object only when destructive deletion is explicitly enabled."""

        if not self.settings.allow_delete:
            raise ObjectStorageConfigurationError("Object deletion is disabled by default for evidence storage.")
        key = self.key_for(tenant_id, object_name)
        self._call(lambda client: client.delete_object(Bucket=self.settings.bucket, Key=key))
