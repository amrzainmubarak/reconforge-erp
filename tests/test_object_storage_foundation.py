from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from reconforge.infrastructure.object_storage import (
    ObjectStorageConfigurationError,
    ObjectStorageConnectionFactory,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageSettings,
    ObjectStorageUnavailableError,
    S3ObjectStore,
    _load_boto3,
)


class _Body:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def read(self) -> bytes:
        return self.content

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


def test_provider_not_found_is_safe() -> None:
    client = _FakeS3()
    store = S3ObjectStore(_Factory(client))
    with pytest.raises(ObjectStorageNotFoundError):
        store.get_bytes("tenant-a", "missing.txt")


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
    )
    factory = ObjectStorageConnectionFactory(settings)
    store = S3ObjectStore(factory)
    object_name = "integration/live.txt"
    try:
        store.put_bytes("test_s3_a", object_name, b"tenant-a")
        assert store.get_bytes("test_s3_a", object_name).content == b"tenant-a"
        assert store.key_for("test_s3_a", object_name) != store.key_for("test_s3_b", object_name)
    finally:
        store.delete("test_s3_a", object_name)
        factory.close()
