"""Governed, read-only HTTPS CAMT.053 bank-statement connector.

The adapter composes the existing bounded CAMT.053 parser with the governed
network executor. It intentionally stops at one account-scoped statement read:
provider dialect conformance, statement authenticity, payment initiation,
settlement, posting, and write-back remain separate gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from reconforge.connectors.camt053 import MAX_CAMT053_BYTES, Camt053Error, Camt053Statement, parse_camt053_bytes
from reconforge.connectors.manifest import (
    AuthenticationMethod,
    ConnectorCapability,
    ConnectorKind,
    ConnectorManifest,
    DataClassification,
    RetryPolicy,
    SupportLevel,
)
from reconforge.connectors.network import (
    ConnectorNetworkError,
    ConnectorReadResult,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
)

BANK_STATEMENT_CAMT053_PATH = "/api/v1/statements/camt053"
BANK_STATEMENT_CAMT053_ENDPOINT = "https://bank.example.test" + BANK_STATEMENT_CAMT053_PATH
BANK_STATEMENT_CAMT053_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="bank-statement-camt053-readonly",
    display_name="CAMT.053 bank statement read-only source",
    version="1.0.0",
    kind=ConnectorKind.NETWORK_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.SECRET_REFERENCE,
    network_required=True,
    data_classification=DataClassification.RESTRICTED,
    rate_limit_per_minute=30,
    incremental_cursor=False,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=8),
    schema_versions=("camt053-statement-http-v1",),
    synthetic_sandbox=True,
    threat_model=("credential-disclosure", "schema-confusion", "source-mismatch", "ssrf"),
    secret_handling="Resolve the provider credential reference at runtime; never persist, log, or return the secret.",  # nosec B106
    egress_destinations=(BANK_STATEMENT_CAMT053_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


def bank_statement_camt053_registration(
    *, credential_reference: str, endpoint: str = BANK_STATEMENT_CAMT053_ENDPOINT
) -> NetworkConnectorRegistration:
    """Create an exact HTTPS registration without widening the provider path."""

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != BANK_STATEMENT_CAMT053_PATH
    ):
        raise ConnectorNetworkError("bank_statement_camt053_endpoint_invalid")
    manifest = BANK_STATEMENT_CAMT053_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest,
        endpoint=endpoint,
        credential_reference=credential_reference,
        maximum_response_bytes=MAX_CAMT053_BYTES,
    )


@dataclass(frozen=True)
class BankStatementCamt053Read:
    statement: Camt053Statement
    request_digest: str
    response_digest: str
    attempts: int


@dataclass(frozen=True)
class BankStatementCamt053Connector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_statement(
        self,
        *,
        idempotency_key: str,
        expected_account_id: str | None = None,
    ) -> BankStatementCamt053Read:
        if expected_account_id is not None:
            expected_account_id = expected_account_id.strip()
            if not expected_account_id or len(expected_account_id) > 256:
                raise ConnectorNetworkError("bank_statement_camt053_account_scope_invalid")
        result: ConnectorReadResult = self.executor.read(self.registration, idempotency_key=idempotency_key)
        try:
            statement = parse_camt053_bytes(result.response_body)
        except Camt053Error as exc:
            raise ConnectorNetworkError("bank_statement_camt053_response_invalid") from exc
        if expected_account_id is not None and statement.account_id != expected_account_id:
            raise ConnectorNetworkError("bank_statement_camt053_account_scope_mismatch")
        return BankStatementCamt053Read(
            statement=statement,
            request_digest=result.request_digest,
            response_digest=result.response_digest,
            attempts=result.attempts,
        )


__all__ = [
    "BANK_STATEMENT_CAMT053_ENDPOINT",
    "BANK_STATEMENT_CAMT053_MANIFEST",
    "BANK_STATEMENT_CAMT053_PATH",
    "BankStatementCamt053Connector",
    "BankStatementCamt053Read",
    "bank_statement_camt053_registration",
]
