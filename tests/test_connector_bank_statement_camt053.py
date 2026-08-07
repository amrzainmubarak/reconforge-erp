from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reconforge.connectors.bank_statement_camt053 import (
    BANK_STATEMENT_CAMT053_ENDPOINT,
    BankStatementCamt053Connector,
    bank_statement_camt053_registration,
)
from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/bank"
        return b"synthetic-bank-token-123"


@dataclass
class _Transport:
    body: bytes
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    status: int = 200

    def get(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> NetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers)))
        return NetworkResponse(self.status, self.body)


def _fixture() -> bytes:
    return (Path(__file__).parent / "golden" / "camt053" / "statement.xml").read_bytes()


def _connector(body: bytes) -> tuple[BankStatementCamt053Connector, _Transport]:
    transport = _Transport(body)
    registration = bank_statement_camt053_registration(credential_reference="vault://tenant-a/bank")
    return BankStatementCamt053Connector(NetworkConnectorExecutor(transport, secret_resolver=_Secrets()), registration), transport


def test_bank_statement_camt053_reads_through_governed_executor_and_scopes_account() -> None:
    connector, transport = _connector(_fixture())

    result = connector.read_statement(idempotency_key="bank-run-1", expected_account_id="DE89370400440532013000")

    assert result.statement.statement_id == "STMT-CAMT-001"
    assert result.statement.lines[0].signed_amount == "100"
    assert result.response_digest
    assert result.request_digest
    assert result.attempts == 1
    assert transport.calls[0][0] == BANK_STATEMENT_CAMT053_ENDPOINT
    assert transport.calls[0][1]["Authorization"] == "Bearer synthetic-bank-token-123"
    assert b"synthetic-bank-token-123" not in repr(result).encode("utf-8")


def test_bank_statement_camt053_rejects_malformed_response_and_account_mismatch() -> None:
    malformed, malformed_transport = _connector(b"<Document/>")
    with pytest.raises(ConnectorNetworkError, match="response_invalid"):
        malformed.read_statement(idempotency_key="bank-invalid")
    assert len(malformed_transport.calls) == 1

    mismatch, mismatch_transport = _connector(_fixture())
    with pytest.raises(ConnectorNetworkError, match="account_scope_mismatch"):
        mismatch.read_statement(idempotency_key="bank-mismatch", expected_account_id="OTHER")
    assert len(mismatch_transport.calls) == 1


@pytest.mark.parametrize("endpoint", [
    "http://bank.example.test/api/v1/statements/camt053",
    "https://bank.example.test/api/v1/statements/other",
    "https://bank.example.test/api/v1/statements/camt053?cursor=1",
    "https://user:pass@bank.example.test/api/v1/statements/camt053",
])
def test_bank_statement_camt053_registration_rejects_endpoint_widening(endpoint: str) -> None:
    with pytest.raises(ConnectorNetworkError, match="endpoint_invalid"):
        bank_statement_camt053_registration(credential_reference="vault://tenant-a/bank", endpoint=endpoint)


def test_bank_statement_camt053_connector_contract_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/bank_statement_camt053.py" in manifest
    assert "include tests/test_connector_bank_statement_camt053.py" in manifest
    assert "include docs/connectors/bank-statement-camt053-readonly.md" in manifest
    assert "include docs/adr/0435-bank-statement-camt053-http-boundary.md" in manifest
    assert (root / "docs/connectors/bank-statement-camt053-readonly.md").is_file()
    assert (root / "docs/adr/0435-bank-statement-camt053-http-boundary.md").is_file()
