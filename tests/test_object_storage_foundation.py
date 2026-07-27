from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from reconforge.infrastructure.object_storage import (
    LocalObjectStorageSettings,
    LocalObjectStore,
    ObjectStorageConfigurationError,
    ObjectStorageConflictError,
    ObjectStorageConnectionFactory,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageOperationError,
    ObjectStorageSettings,
    ObjectStorageUnavailableError,
    S3ObjectStore,
    _load_boto3,
)


class _Body:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.content if size < 0 else self.content[:size]

    def close(self) -> None:
        self.closed = True


class _ProviderError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def put_object(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("put_object", kwargs))
        if kwargs.get("IfNoneMatch") == "*" and (str(kwargs["Bucket"]), str(kwargs["Key"])) in self.objects:
            raise _ProviderError("PreconditionFailed")
        self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))] = kwargs
        return {"VersionId": "v1"}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("get_object", kwargs))
        stored = self.objects.get((str(kwargs["Bucket"]), str(kwargs["Key"])))
        if stored is None:
            raise _ProviderError("NoSuchKey")
        return {
            "Body": _Body(stored["Body"]),
            "ContentType": stored["ContentType"],
            "Metadata": stored["Metadata"],
            "ContentLength": len(stored["Body"]),
            "VersionId": "v1",
        }

    def generate_presigned_url(self, operation: str, **kwargs: object) -> str:
        self.calls.append((operation, kwargs))
        return "https://storage.example/signed"

    def delete_object(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("delete_object", kwargs))
        self.objects.pop((str(kwargs["Bucket"]), str(kwargs["Key"])), None)
        return {}

    def close(self) -> None:
        self.calls.append(("close", {}))


class _Factory:
    def __init__(self, client: _FakeS3, *, allow_delete: bool = False, object_lock_mode: str | None = None) -> None:
        self.settings = ObjectStorageSettings(
            bucket="reconforge-test",
            endpoint_url="https://storage.example",
            allow_delete=allow_delete,
            object_lock_mode=object_lock_mode,
        )
        self._client = client

    def client(self) -> _FakeS3:
        return self._client


def test_storage_settings_require_tls_and_redact_endpoint() -> None:
    with pytest.raises(ObjectStorageConfigurationError):
        ObjectStorageSettings(bucket="reconforge-test", endpoint_url="http://storage.example")
    settings = ObjectStorageSettings(bucket="reconforge-test", endpoint_url="https://user:secret@storage.example")
    assert "secret" not in repr(settings)
    assert "https://" not in repr(settings)


def test_storage_factory_is_lazy_and_loads_boto3_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeS3()
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_client_factory(service: str, **kwargs: object) -> _FakeS3:
        calls.append((service, kwargs))
        return fake_client

    monkeypatch.setattr("reconforge.infrastructure.object_storage._load_boto3", lambda: SimpleNamespace(client=fake_client_factory))
    factory = ObjectStorageConnectionFactory(ObjectStorageSettings(bucket="reconforge-test"))
    assert calls == []
    assert factory.client() is fake_client
    assert factory.client() is fake_client
    assert calls == [("s3", {"region_name": "us-east-1", "endpoint_url": None})]


def test_missing_boto3_driver_has_install_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_driver(name: str) -> SimpleNamespace:
        raise ImportError(name)

    monkeypatch.setattr("reconforge.infrastructure.object_storage.importlib.import_module", missing_driver)
    with pytest.raises(ObjectStorageUnavailableError, match="server"):
        _load_boto3()


def test_upload_download_checksum_and_tenant_key_isolation() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    uploaded = store.put_bytes(
        "Tenant_A",
        "evidence/report.json",
        b"{\"ok\":true}",
        content_type="application/json",
        metadata={"source": "synthetic"},
    )

    assert uploaded.key == "reconforge/tenant/tenant_a/evidence/report.json"
    assert uploaded.version_id == "v1"
    with pytest.raises(ObjectStorageConflictError):
        store.put_bytes("tenant_a", "evidence/report.json", b"replacement")
    downloaded = store.get_bytes("tenant_a", "evidence/report.json")
    assert downloaded.content == b"{\"ok\":true}"
    assert downloaded.sha256 == uploaded.sha256
    assert downloaded.metadata["reconforge-tenant"] == "tenant_a"
    assert store.key_for("tenant_b", "evidence/report.json") != uploaded.key


def test_object_keys_metadata_retention_and_delete_are_guarded() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    with pytest.raises(ObjectStorageConfigurationError):
        store.key_for("tenant-a", "../escape.txt")
    with pytest.raises(ObjectStorageConfigurationError):
        store.put_bytes("tenant-a", "evidence.txt", b"x", metadata={"reconforge-sha256": "override"})
    with pytest.raises(ObjectStorageConfigurationError):
        store.put_bytes("tenant-a", "evidence.txt", b"x", retention_until=datetime.now(UTC) + timedelta(days=1))
    with pytest.raises(ObjectStorageConfigurationError):
        store.delete("tenant-a", "evidence.txt")

    locked = S3ObjectStore(
        _Factory(client, allow_delete=True)
    )
    locked.put_bytes("tenant-a", "evidence.txt", b"x")
    locked.delete("tenant-a", "evidence.txt")
    assert "https://" in locked.presigned_get_url("tenant-a", "evidence.txt", expires_in_seconds=60)

    lock_client = _FakeS3()
    lock_store = S3ObjectStore(_Factory(lock_client, object_lock_mode="COMPLIANCE"))
    lock_store.put_bytes(
        "tenant-a",
        "retained.txt",
        b"retained",
        retention_until=datetime.now(UTC) + timedelta(days=1),
    )
    put_call = next(kwargs for name, kwargs in lock_client.calls if name == "put_object")
    assert put_call["ServerSideEncryption"] == "AES256"
    assert put_call["ObjectLockMode"] == "COMPLIANCE"


def test_tampered_download_fails_integrity_check() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    uploaded = store.put_bytes("tenant-a", "evidence.txt", b"original")
    stored = client.objects[("reconforge-test", uploaded.key)]
    stored["Body"] = b"tampered"
    with pytest.raises(ObjectStorageIntegrityError):
        store.get_bytes("tenant-a", "evidence.txt")


@pytest.mark.parametrize("metadata", [{}, {"reconforge-sha256": "0" * 64}])
def test_s3_download_requires_complete_matching_integrity_metadata(metadata: dict[str, str]) -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    uploaded = store.put_bytes("tenant-a", "evidence.txt", b"original")
    stored = client.objects[("reconforge-test", uploaded.key)]
    stored["Metadata"] = metadata
    with pytest.raises(ObjectStorageIntegrityError):
        store.get_bytes("tenant-a", "evidence.txt")


def test_s3_download_rejects_declared_oversize_before_reading_body() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    uploaded = store.put_bytes("tenant-a", "evidence.txt", b"original")
    original_get = client.get_object
    body = _Body(b"original")

    def oversized(**kwargs: object) -> dict[str, object]:
        response = original_get(**kwargs)
        response["Body"] = body
        response["ContentLength"] = store.settings.max_object_bytes + 1
        return response

    client.get_object = oversized  # type: ignore[method-assign]
    with pytest.raises(ObjectStorageOperationError, match="size limit"):
        store.get_bytes("tenant-a", "evidence.txt")
    assert body.closed is True
    assert uploaded.key


def test_provider_not_found_is_safe() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    with pytest.raises(ObjectStorageNotFoundError):
        store.get_bytes("tenant-a", "missing.txt")


def test_local_store_parity_retention_integrity_and_tenant_isolation(tmp_path: Path) -> None:
    store = LocalObjectStore(
        LocalObjectStorageSettings(root=tmp_path.resolve(), allow_delete=True, max_object_bytes=32)
    )
    retained_until = datetime.now(UTC) + timedelta(days=1)
    uploaded = store.put_bytes(
        "tenant-a", "evidence/report.json", b'{"ok":true}',
        content_type="application/json", metadata={"source": "synthetic"},
        retention_until=retained_until,
    )
    downloaded = store.get_bytes("tenant-a", "evidence/report.json")
    assert downloaded.content == uploaded.content
    assert downloaded.sha256 == uploaded.sha256
    assert downloaded.metadata["reconforge-tenant"] == "tenant-a"
    with pytest.raises(ObjectStorageNotFoundError):
        store.get_bytes("tenant-b", "evidence/report.json")
    with pytest.raises(ObjectStorageConflictError):
        store.put_bytes("tenant-a", "evidence/report.json", b"replacement")
    with pytest.raises(ObjectStorageConflictError, match="retention"):
        store.delete("tenant-a", "evidence/report.json")
    with pytest.raises(ObjectStorageConfigurationError, match="size limit"):
        store.put_bytes("tenant-a", "too-large.bin", b"x" * 33)

    object_path = tmp_path / Path(*uploaded.key.split("/"))
    object_path.write_bytes(b"tampered")
    with pytest.raises(ObjectStorageIntegrityError):
        store.get_bytes("tenant-a", "evidence/report.json")


def test_local_store_rejects_traversal_links_and_reserved_sidecars(tmp_path: Path) -> None:
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    for unsafe in ("../escape", "/absolute", "nested//empty", "file.reconforge-object.json"):
        with pytest.raises(ObjectStorageConfigurationError):
            store.key_for("tenant-a", unsafe)
    link = tmp_path / "reconforge" / "tenant" / "tenant-a"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic-link creation is unavailable")
    with pytest.raises(ObjectStorageConfigurationError, match="link"):
        store.put_bytes("tenant-a", "blocked.bin", b"x")


def test_local_store_fails_closed_for_missing_or_invalid_manifest(tmp_path: Path) -> None:
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    uploaded = store.put_bytes("tenant-a", "evidence.txt", b"evidence")
    object_path = tmp_path / Path(*uploaded.key.split("/"))
    manifest_path = object_path.with_name(object_path.name + ".reconforge-object.json")
    manifest_path.unlink()
    with pytest.raises(ObjectStorageNotFoundError):
        store.get_bytes("tenant-a", "evidence.txt")

    object_path.unlink()
    store.put_bytes("tenant-a", "invalid.txt", b"evidence")
    invalid_path = tmp_path / Path(*store.key_for("tenant-a", "invalid.txt").split("/"))
    invalid_manifest = invalid_path.with_name(invalid_path.name + ".reconforge-object.json")
    invalid_manifest.write_text("not-json", encoding="utf-8")
    with pytest.raises(ObjectStorageIntegrityError, match="manifest"):
        store.get_bytes("tenant-a", "invalid.txt")


def test_local_store_concurrent_create_has_one_immutable_winner(tmp_path: Path) -> None:
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))

    def create(payload: bytes) -> bytes | None:
        try:
            return store.put_bytes("tenant-a", "race.bin", payload).content
        except ObjectStorageConflictError:
            return None

    payloads = [f"candidate-{index}".encode() for index in range(12)]
    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        results = list(executor.map(create, payloads))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.get_bytes("tenant-a", "race.bin").content == winners[0]


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_S3_ENDPOINT") or not os.environ.get("RECONFORGE_TEST_S3_BUCKET"),
    reason="requires a live S3-compatible service",
)
def test_live_s3_tenant_key_isolation() -> None:
    pytest.importorskip("boto3")
    settings = ObjectStorageSettings(
        bucket=os.environ["RECONFORGE_TEST_S3_BUCKET"],
        endpoint_url=os.environ["RECONFORGE_TEST_S3_ENDPOINT"],
        require_tls=False,
        allow_delete=True,
        server_side_encryption=None,
    )
    factory = ObjectStorageConnectionFactory(settings)
    store = S3ObjectStore(factory)
    object_name = "integration/live.txt"
    try:
        uploaded = store.put_bytes("test_s3_a", object_name, b"tenant-a")
        assert store.get_bytes("test_s3_a", object_name).content == b"tenant-a"
        assert store.key_for("test_s3_a", object_name) != store.key_for("test_s3_b", object_name)
        with pytest.raises(ObjectStorageNotFoundError):
            store.get_bytes("test_s3_b", object_name)
        with pytest.raises(ObjectStorageConflictError):
            store.put_bytes("test_s3_a", object_name, b"replacement")
        factory.client().put_object(
            Bucket=settings.bucket, Key=uploaded.key, Body=b"tampered",
            ContentType="application/octet-stream", Metadata=uploaded.metadata,
        )
        with pytest.raises(ObjectStorageIntegrityError):
            store.get_bytes("test_s3_a", object_name)
    finally:
        factory.client().delete_object(
            Bucket=settings.bucket, Key=store.key_for("test_s3_a", object_name)
        )
        factory.close()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_S3_ENDPOINT")
    or not os.environ.get("RECONFORGE_TEST_S3_LOCK_BUCKET"),
    reason="requires a live object-lock-enabled S3-compatible bucket",
)
def test_live_s3_retention_blocks_normal_delete() -> None:
    pytest.importorskip("boto3")
    settings = ObjectStorageSettings(
        bucket=os.environ["RECONFORGE_TEST_S3_LOCK_BUCKET"],
        endpoint_url=os.environ["RECONFORGE_TEST_S3_ENDPOINT"], require_tls=False,
        allow_delete=True, server_side_encryption=None, object_lock_mode="GOVERNANCE",
    )
    factory = ObjectStorageConnectionFactory(settings)
    store = S3ObjectStore(factory)
    object_name = f"integration/retained-{os.getpid()}.txt"
    uploaded = store.put_bytes(
        "test_s3_retention", object_name, b"retained",
        retention_until=datetime.now(UTC) + timedelta(hours=1),
    )
    try:
        assert store.get_bytes("test_s3_retention", object_name).content == b"retained"
        with pytest.raises(ObjectStorageOperationError):
            store.delete("test_s3_retention", object_name)
    finally:
        factory.client().delete_object(
            Bucket=settings.bucket, Key=uploaded.key, BypassGovernanceRetention=True
        )
        factory.close()
