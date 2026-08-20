# CAMT.053 HTTPS bank-statement source

ReconForge provides a governed, read-only HTTPS adapter that composes the
bounded local CAMT.053 parser with `NetworkConnectorExecutor`:

```python
from reconforge.connectors.bank_statement_camt053 import (
    BankStatementCamt053Connector,
    bank_statement_camt053_registration,
)

registration = bank_statement_camt053_registration(
    credential_reference="vault://tenant-a/bank",
)
read = BankStatementCamt053Connector(executor, registration).read_statement(
    idempotency_key="statement-run-2026-01-31",
    expected_account_id="DE89370400440532013000",
)
```

The registration allows one exact HTTPS path, resolves a credential reference
only at request time, caps the response at 8 MiB, retries only through the
shared bounded policy, rejects malformed or entity-expansion XML through
`defusedxml`, and optionally enforces an expected account identifier. The
result carries the request digest, raw response digest, normalized CAMT source
digest, and attempt count.

This is a synthetic provider-neutral boundary. It does not prove a bank's
CAMT dialect, source authenticity, certificate or credential lifecycle,
statement completeness, payment initiation, settlement, accounting posting,
ERP mapping, write-back, or production availability. A bank-specific profile
must add provider conformance fixtures and an approved runtime gate before it
is described as a live bank integration.
