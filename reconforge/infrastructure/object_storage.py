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
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol
from urllib.parse import urlsplit

from reconforge.application.evidence import EvidenceStorageScope

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


class ObjectStorageConflictError(ObjectStorageOperationError):
    """Raised when immutable object identity already exists."""


ObjectStorageScope = EvidenceStorageScope


def _storage_scope(value: str | ObjectStorageScope) -> ObjectStorageScope:
    return value if isinstance(value, ObjectStorageScope) else ObjectStorageScope(tenant_id=value)


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
    max_object_bytes: int = 64 * 1024 * 1024

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
        if not 1 <= self.max_object_bytes <= 1024 * 1024 * 1024:
            raise ObjectStorageConfigurationError("Object-storage size limit must be between 1 byte and 1 GiB.")


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


class ObjectStoreProtocol(Protocol):
    """Backend-neutral immutable byte-object contract."""

    def key_for(self, tenant_id: str | ObjectStorageScope, object_name: str) -> str: ...

    def put_bytes(
        self,
        tenant_id: str | ObjectStorageScope,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredObject: ...

    def get_bytes(self, tenant_id: str | ObjectStorageScope, object_name: str) -> StoredObject: ...

    def delete(self, tenant_id: str | ObjectStorageScope, object_name: str) -> None: ...


class S3ObjectStore:
    """Tenant-scoped S3-compatible artifact store."""

    supports_hierarchical_scope = True

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

    def key_for(self, tenant_id: str | ObjectStorageScope, object_name: str) -> str:
        """Return a deterministic tenant-separated key."""

        scope = _storage_scope(tenant_id)
        relative_name = self._object_name(object_name)
        prefix = f"{self.settings.key_prefix}/" if self.settings.key_prefix else ""
        scope_path = f"tenant/{scope.tenant_id}"
        if scope.workspace_id:
            scope_path += f"/workspace/{scope.workspace_id}"
        if scope.entity_id:
            scope_path += f"/entity/{scope.entity_id}"
        return f"{prefix}{scope_path}/{relative_name}"

    @staticmethod
    def _metadata(
        metadata: Mapping[str, object] | None,
        *,
        scope: ObjectStorageScope,
        digest: str,
    ) -> dict[str, str]:
        result = {
            "reconforge-sha256": digest,
            "reconforge-tenant": scope.tenant_id,
            "reconforge-workspace": scope.workspace_id,
            "reconforge-entity": scope.entity_id,
        }
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
        except (
            ObjectStorageConfigurationError,
            ObjectStorageConflictError,
            ObjectStorageIntegrityError,
            ObjectStorageNotFoundError,
        ):
            raise
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
            if str(error_code) in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStorageNotFoundError("Object was not found.") from exc
            if str(error_code) in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                raise ObjectStorageConflictError("Immutable object identity already exists.") from exc
            raise ObjectStorageOperationError("Object-storage operation failed.") from exc

    def put_bytes(
        self,
        tenant_id: str | ObjectStorageScope,
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
        if len(content) > self.settings.max_object_bytes:
            raise ObjectStorageConfigurationError("Object content exceeds the configured size limit.")
        if not content_type.strip() or any(ord(character) < 32 for character in content_type):
            raise ObjectStorageConfigurationError("Object content type is invalid.")
        scope = _storage_scope(tenant_id)
        key = self.key_for(scope, object_name)
        digest = hashlib.sha256(content).hexdigest()
        object_metadata = self._metadata(metadata, scope=scope, digest=digest)
        put_kwargs: dict[str, object] = {
            "Bucket": self.settings.bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "Metadata": object_metadata,
            "IfNoneMatch": "*",
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

    def get_bytes(self, tenant_id: str | ObjectStorageScope, object_name: str) -> StoredObject:
        """Download and verify one tenant-scoped object."""

        scope = _storage_scope(tenant_id)
        key = self.key_for(scope, object_name)
        response = self._call(lambda client: client.get_object(Bucket=self.settings.bucket, Key=key))
        body = response.get("Body")
        if body is None or not callable(getattr(body, "read", None)):
            raise ObjectStorageOperationError("Object-storage response did not contain a readable body.")
        declared_size = response.get("ContentLength")
        if declared_size is not None and int(declared_size) > self.settings.max_object_bytes:
            close = getattr(body, "close", None)
            if callable(close):
                close()
            raise ObjectStorageOperationError("Stored object exceeds the configured size limit.")
        try:
            try:
                content = body.read(self.settings.max_object_bytes + 1)
            except TypeError:
                content = body.read()
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if not isinstance(content, bytes):
            raise ObjectStorageOperationError("Object-storage response body was not bytes.")
        if len(content) > self.settings.max_object_bytes:
            raise ObjectStorageOperationError("Stored object exceeds the configured size limit.")
        digest = hashlib.sha256(content).hexdigest()
        metadata = {str(key).lower(): str(value) for key, value in (response.get("Metadata") or {}).items()}
        expected = metadata.get("reconforge-sha256")
        if expected is None:
            raise ObjectStorageIntegrityError("Object is missing its required SHA-256 metadata.")
        if expected != digest:
            raise ObjectStorageIntegrityError("Object checksum does not match its recorded SHA-256.")
        expected_scope = {
            "reconforge-tenant": scope.tenant_id,
            "reconforge-workspace": scope.workspace_id,
            "reconforge-entity": scope.entity_id,
        }
        if any(metadata.get(name, "") != value for name, value in expected_scope.items()):
            raise ObjectStorageIntegrityError("Object hierarchy metadata does not match the requested scope.")
        return StoredObject(
            key=key,
            content=content,
            sha256=digest,
            content_type=str(response.get("ContentType") or "application/octet-stream"),
            metadata=metadata,
            version_id=str(response.get("VersionId")) if response.get("VersionId") is not None else None,
        )

    def presigned_get_url(
        self,
        tenant_id: str | ObjectStorageScope,
        object_name: str,
        *,
        expires_in_seconds: int | None = None,
    ) -> str:
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

    def delete(self, tenant_id: str | ObjectStorageScope, object_name: str) -> None:
        """Delete an object only when destructive deletion is explicitly enabled."""

        if not self.settings.allow_delete:
            raise ObjectStorageConfigurationError("Object deletion is disabled by default for evidence storage.")
        key = self.key_for(tenant_id, object_name)
        stored = self.get_bytes(tenant_id, object_name)
        delete_kwargs = {"Bucket": self.settings.bucket, "Key": key}
        if stored.version_id is not None:
            delete_kwargs["VersionId"] = stored.version_id
        self._call(lambda client: client.delete_object(**delete_kwargs))


_LOCAL_METADATA_SUFFIX = ".reconforge-object.json"


@dataclass(frozen=True)
class LocalObjectStorageSettings:
    """Filesystem-backed object-store settings for offline Community mode."""

    root: Path
    key_prefix: str = "reconforge"
    allow_delete: bool = False
    max_object_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        root = Path(self.root)
        if not root.is_absolute():
            raise ObjectStorageConfigurationError("Local object-storage root must be absolute.")
        if self.key_prefix and not _PREFIX_PATTERN.fullmatch(self.key_prefix):
            raise ObjectStorageConfigurationError("Local object-storage key prefix contains unsafe characters.")
        if not 1 <= self.max_object_bytes <= 1024 * 1024 * 1024:
            raise ObjectStorageConfigurationError("Local object size limit must be between 1 byte and 1 GiB.")
        object.__setattr__(self, "root", root)


class LocalObjectStore:
    """Offline immutable object store with sidecar integrity manifests."""

    supports_hierarchical_scope = True

    def __init__(self, settings: LocalObjectStorageSettings) -> None:
        self.settings = settings
        configured_root = settings.root
        if configured_root.exists() and configured_root.is_symlink():
            raise ObjectStorageConfigurationError("Local object-storage root must be a regular directory.")
        configured_root.mkdir(parents=True, exist_ok=True)
        self.root = configured_root.resolve()
        if not self.root.is_dir():
            raise ObjectStorageConfigurationError("Local object-storage root must be a regular directory.")

    def key_for(self, tenant_id: str | ObjectStorageScope, object_name: str) -> str:
        scope = _storage_scope(tenant_id)
        relative = S3ObjectStore._object_name(object_name)
        if relative.endswith(_LOCAL_METADATA_SUFFIX):
            raise ObjectStorageConfigurationError("Object name uses a reserved local metadata suffix.")
        prefix = f"{self.settings.key_prefix}/" if self.settings.key_prefix else ""
        scope_path = f"tenant/{scope.tenant_id}"
        if scope.workspace_id:
            scope_path += f"/workspace/{scope.workspace_id}"
        if scope.entity_id:
            scope_path += f"/entity/{scope.entity_id}"
        return f"{prefix}{scope_path}/{relative}"

    def _paths(self, tenant_id: str | ObjectStorageScope, object_name: str) -> tuple[str, Path, Path]:
        key = self.key_for(tenant_id, object_name)
        target = self.root.joinpath(*key.split("/"))
        manifest = target.with_name(target.name + _LOCAL_METADATA_SUFFIX)
        for candidate in (target, manifest):
            try:
                candidate.relative_to(self.root)
            except ValueError as exc:
                raise ObjectStorageConfigurationError("Local object path escapes its configured root.") from exc
        return key, target, manifest

    def _prepare_parent(self, target: Path) -> None:
        relative_parent = target.parent.relative_to(self.root)
        current = self.root
        for part in relative_parent.parts:
            current = current / part
            if current.exists() and (current.is_symlink() or not current.is_dir()):
                raise ObjectStorageConfigurationError("Local object path crosses a non-directory or link.")
            current.mkdir(exist_ok=True)
            if current.is_symlink():
                raise ObjectStorageConfigurationError("Local object path crosses a symbolic link.")

    @staticmethod
    def _write_temp(parent: Path, payload: bytes) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=".reconforge-object-", dir=parent)
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def put_bytes(
        self,
        tenant_id: str | ObjectStorageScope,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredObject:
        if not isinstance(content, bytes):
            raise ObjectStorageConfigurationError("Object content must be bytes.")
        if len(content) > self.settings.max_object_bytes:
            raise ObjectStorageConfigurationError("Object content exceeds the configured size limit.")
        if not content_type.strip() or any(ord(character) < 32 for character in content_type):
            raise ObjectStorageConfigurationError("Object content type is invalid.")
        scope = _storage_scope(tenant_id)
        key, target, manifest_path = self._paths(scope, object_name)
        self._prepare_parent(target)
        if target.exists() or manifest_path.exists():
            raise ObjectStorageConflictError("Immutable object identity already exists.")
        digest = hashlib.sha256(content).hexdigest()
        object_metadata = S3ObjectStore._metadata(metadata, scope=scope, digest=digest)
        retain_text = ""
        if retention_until is not None:
            if retention_until.tzinfo is None or retention_until <= datetime.now(UTC):
                raise ObjectStorageConfigurationError("Retention timestamp must be timezone-aware and in the future.")
            retain_text = retention_until.astimezone(UTC).isoformat()
            object_metadata["reconforge-retain-until"] = retain_text
        manifest = json.dumps(
            {
                "schema_version": 1,
                "key": key,
                "sha256": digest,
                "size": len(content),
                "content_type": content_type,
                "metadata": object_metadata,
                "retention_until": retain_text,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        content_temp = self._write_temp(target.parent, content)
        manifest_temp = self._write_temp(target.parent, manifest)
        content_linked = False
        manifest_linked = False
        try:
            os.link(content_temp, target)
            content_linked = True
            os.link(manifest_temp, manifest_path)
            manifest_linked = True
        except FileExistsError as exc:
            if content_linked:
                target.unlink(missing_ok=True)
            if manifest_linked:
                manifest_path.unlink(missing_ok=True)
            raise ObjectStorageConflictError("Immutable object identity already exists.") from exc
        except Exception as exc:
            if content_linked:
                target.unlink(missing_ok=True)
            if manifest_linked:
                manifest_path.unlink(missing_ok=True)
            raise ObjectStorageOperationError("Unable to publish local object.") from exc
        finally:
            content_temp.unlink(missing_ok=True)
            manifest_temp.unlink(missing_ok=True)
        return StoredObject(key, content, digest, content_type, object_metadata)

    def get_bytes(self, tenant_id: str | ObjectStorageScope, object_name: str) -> StoredObject:
        scope = _storage_scope(tenant_id)
        key, target, manifest_path = self._paths(scope, object_name)
        if not target.is_file() or not manifest_path.is_file() or target.is_symlink() or manifest_path.is_symlink():
            raise ObjectStorageNotFoundError("Object was not found.")
        try:
            if manifest_path.stat().st_size > 64 * 1024:
                raise ObjectStorageIntegrityError("Local object manifest exceeds its size limit.")
            with manifest_path.open("rb") as stream:
                manifest_bytes = stream.read(64 * 1024 + 1)
            if len(manifest_bytes) > 64 * 1024:
                raise ObjectStorageIntegrityError("Local object manifest exceeds its size limit.")
            manifest = json.loads(manifest_bytes)
        except ObjectStorageIntegrityError:
            raise
        except Exception as exc:
            raise ObjectStorageIntegrityError("Local object manifest is invalid.") from exc
        if target.stat().st_size > self.settings.max_object_bytes:
            raise ObjectStorageOperationError("Stored object exceeds the configured size limit.")
        with target.open("rb") as stream:
            content = stream.read(self.settings.max_object_bytes + 1)
        if len(content) > self.settings.max_object_bytes:
            raise ObjectStorageOperationError("Stored object exceeds the configured size limit.")
        digest = hashlib.sha256(content).hexdigest()
        metadata = manifest.get("metadata") if isinstance(manifest, dict) else None
        if (
            not isinstance(metadata, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("key") != key
            or manifest.get("size") != len(content)
            or manifest.get("sha256") != digest
            or metadata.get("reconforge-sha256") != digest
            or metadata.get("reconforge-tenant") != scope.tenant_id
            or metadata.get("reconforge-workspace", "") != scope.workspace_id
            or metadata.get("reconforge-entity", "") != scope.entity_id
        ):
            raise ObjectStorageIntegrityError("Local object content or manifest failed verification.")
        return StoredObject(
            key,
            content,
            digest,
            str(manifest.get("content_type") or "application/octet-stream"),
            {str(name): str(value) for name, value in metadata.items()},
        )

    def delete(self, tenant_id: str | ObjectStorageScope, object_name: str) -> None:
        if not self.settings.allow_delete:
            raise ObjectStorageConfigurationError("Object deletion is disabled by default for evidence storage.")
        _, target, manifest_path = self._paths(tenant_id, object_name)
        if not target.exists() and not manifest_path.exists():
            raise ObjectStorageNotFoundError("Object was not found.")
        stored = self.get_bytes(tenant_id, object_name)
        retain_text = stored.metadata.get("reconforge-retain-until", "")
        if retain_text:
            try:
                retained_until = datetime.fromisoformat(retain_text)
            except ValueError as exc:
                raise ObjectStorageIntegrityError("Local retention metadata is invalid.") from exc
            if retained_until > datetime.now(UTC):
                raise ObjectStorageConflictError("Object retention period has not expired.")
        target.unlink()
        manifest_path.unlink()
