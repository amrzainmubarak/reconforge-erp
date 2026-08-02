from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from reconforge.connectors.network import ConnectorNetworkError
from reconforge.connectors.sftp_reference import (
    ReferenceSftpConnector,
    SftpRemoteFile,
    SftpTransport,
    sftp_reference_registration,
)


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "secret/sftp"
        return b"synthetic-secret-material"


@dataclass
class _Transport(SftpTransport):
    files: tuple[SftpRemoteFile, ...]
    seen_credential: bytes | None = None

    def list_files(self, endpoint: str, *, root_path: str, credential: bytes, maximum_files: int, maximum_file_bytes: int) -> tuple[SftpRemoteFile, ...]:
        assert endpoint == "sftp://sftp.example.test:22/inbound"
        assert root_path == "/inbound"
        assert maximum_files == 100
        assert maximum_file_bytes == 16_777_216
        self.seen_credential = credential
        return self.files


def _connector(files: tuple[SftpRemoteFile, ...]) -> tuple[ReferenceSftpConnector, _Transport]:
    transport = _Transport(files)
    return ReferenceSftpConnector(transport, _Secrets(), sftp_reference_registration(credential_reference="secret/sftp")), transport


def test_sftp_read_is_sorted_bounded_and_digest_replayable() -> None:
    connector, transport = _connector(
        (
            SftpRemoteFile("/inbound/z.csv", b"z", "2026-08-02T10:00:00Z"),
            SftpRemoteFile("/inbound/a.csv", b"a", "2026-08-02T09:00:00Z"),
        )
    )
    first = connector.read_files(idempotency_key="sftp-1")
    replay = connector.read_files(idempotency_key="sftp-1")
    assert [item.path for item in first.files] == ["/inbound/a.csv", "/inbound/z.csv"]
    assert first.request_digest == replay.request_digest
    assert first.response_digest == replay.response_digest
    assert first.next_cursor is None
    assert transport.seen_credential == b"synthetic-secret-material"


def test_sftp_cursor_and_file_hashes_are_deterministic() -> None:
    connector, _ = _connector(
        (
            SftpRemoteFile("/inbound/a.csv", b"a", "2026-08-02T09:00:00Z"),
            SftpRemoteFile("/inbound/b.json", b"{}", "2026-08-02T10:00:00Z"),
        )
    )
    result = connector.read_files(idempotency_key="sftp-2", cursor="/inbound/a.csv")
    assert [item.path for item in result.files] == ["/inbound/b.json"]
    assert result.files[0].sha256 == hashlib.sha256(b"{}").hexdigest()


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ((SftpRemoteFile("/outside/a.csv", b"x", "now"),), "outside_root"),
        ((SftpRemoteFile("/inbound/a.exe", b"x", "now"),), "file_type"),
    ],
)
def test_sftp_rejects_unsafe_remote_files(files: tuple[SftpRemoteFile, ...], message: str) -> None:
    connector, _ = _connector(files)
    with pytest.raises(ConnectorNetworkError, match=message):
        connector.read_files(idempotency_key="sftp-3")


def test_sftp_registration_rejects_traversal_and_non_allowlisted_endpoint() -> None:
    registration = sftp_reference_registration(credential_reference="secret/sftp")
    with pytest.raises(ValidationError, match="traversal"):
        registration.__class__.model_validate({**registration.model_dump(), "root_path": "/inbound/../secret"})
    with pytest.raises(ValidationError, match="exactly match"):
        registration.__class__.model_validate({**registration.model_dump(), "endpoint": "sftp://sftp.example.test:22/other"})


def test_sftp_rejects_invalid_cursor_and_idempotency_without_transport() -> None:
    connector, _ = _connector(())
    with pytest.raises(ConnectorNetworkError, match="idempotency"):
        connector.read_files(idempotency_key=" ")
    with pytest.raises(ConnectorNetworkError, match="cursor"):
        connector.read_files(idempotency_key="sftp-4", cursor="x" * 4097)
