from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from reconforge.connectors.network import ConnectorNetworkError
from reconforge.connectors.object_reference import (
    ObjectRemoteEntry,
    ObjectStorageTransport,
    ReferenceObjectStorageConnector,
    object_reference_registration,
)


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "secret/object"
        return b"synthetic-object-secret"


@dataclass
class _Transport(ObjectStorageTransport):
    entries: tuple[ObjectRemoteEntry, ...]
    seen_tenant: str | None = None

    def list_objects(
        self,
        endpoint: str,
        *,
        tenant_id: str,
        key_prefix: str,
        credential: bytes,
        maximum_objects: int,
        maximum_object_bytes: int,
    ) -> tuple[ObjectRemoteEntry, ...]:
        assert endpoint == "https://objects.example.test/reconforge"
        assert key_prefix == "incoming"
        assert credential == b"synthetic-object-secret"
        assert maximum_objects == 100
        assert maximum_object_bytes == 16_777_216
        self.seen_tenant = tenant_id
        return self.entries


def _entry(key: str, content: bytes, tenant: str = "tenant-a") -> ObjectRemoteEntry:
    return ObjectRemoteEntry(key, content, hashlib.sha256(content).hexdigest(), {"reconforge-tenant": tenant})


def _connector(entries: tuple[ObjectRemoteEntry, ...]) -> tuple[ReferenceObjectStorageConnector, _Transport]:
    transport = _Transport(entries)
    registration = object_reference_registration(credential_reference="secret/object", tenant_id="tenant-a")
    return ReferenceObjectStorageConnector(transport, _Secrets(), registration), transport


def test_object_read_is_tenant_scoped_sorted_and_replayable() -> None:
    connector, transport = _connector((_entry("incoming/z.json", b"z"), _entry("incoming/a.csv", b"a")))
    first = connector.read_objects(idempotency_key="object-1")
    replay = connector.read_objects(idempotency_key="object-1")
    assert [item.key for item in first.objects] == ["incoming/a.csv", "incoming/z.json"]
    assert first.request_digest == replay.request_digest
    assert first.response_digest == replay.response_digest
    assert first.next_cursor is None
    assert transport.seen_tenant == "tenant-a"


def test_object_cursor_and_checksum_are_bound() -> None:
    connector, _ = _connector((_entry("incoming/a.csv", b"a"), _entry("incoming/b.json", b"{}")))
    result = connector.read_objects(idempotency_key="object-2", cursor="incoming/a.csv")
    assert [item.key for item in result.objects] == ["incoming/b.json"]
    assert result.objects[0].sha256 == hashlib.sha256(b"{}").hexdigest()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ((_entry("outside/a.csv", b"x"),), "outside_prefix"),
        ((_entry("incoming/a.csv", b"x", tenant="tenant-b"),), "scope_mismatch"),
        ((ObjectRemoteEntry("incoming/a.csv", b"x", "0" * 64, {"reconforge-tenant": "tenant-a"}),), "checksum"),
        ((ObjectRemoteEntry("incoming/../a.csv", b"x", hashlib.sha256(b"x").hexdigest(), {"reconforge-tenant": "tenant-a"}),), "traversal"),
    ],
)
def test_object_rejects_cross_scope_traversal_and_bad_checksum(
    entries: tuple[ObjectRemoteEntry, ...], message: str
) -> None:
    connector, _ = _connector(entries)
    with pytest.raises(ConnectorNetworkError, match=message):
        connector.read_objects(idempotency_key="object-3")


def test_object_registration_rejects_bad_prefix_and_endpoint() -> None:
    registration = object_reference_registration(credential_reference="secret/object", tenant_id="tenant-a")
    with pytest.raises(ValidationError, match="prefix"):
        registration.__class__.model_validate({**registration.model_dump(), "key_prefix": "../secret"})
    with pytest.raises(ValidationError, match="exactly match"):
        registration.__class__.model_validate(
            {**registration.model_dump(), "endpoint": "https://objects.example.test/other"}
        )


def test_object_rejects_invalid_cursor_and_idempotency() -> None:
    connector, _ = _connector(())
    with pytest.raises(ConnectorNetworkError, match="idempotency"):
        connector.read_objects(idempotency_key=" ")
    with pytest.raises(ConnectorNetworkError, match="cursor"):
        connector.read_objects(idempotency_key="object-4", cursor="x" * 4097)
