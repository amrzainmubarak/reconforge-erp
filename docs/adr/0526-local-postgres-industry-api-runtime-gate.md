# ADR 0526: Local PostgreSQL industry/API runtime gate is bounded evidence

- **Date**: 2026-08-11
- **Status**: Accepted

## Context

The repository had current PostgreSQL migrations through `0088_pg_currency_snapshot`
and server-profile persistence for the manufacturing, retail, professional, and
bank-statement vertical slices. The historical CI report contained PostgreSQL
metrics, migration, and collection failures, so a current disposable runtime
check was needed before treating those surfaces as locally verified.

## Decision

Retain a disposable PostgreSQL 16 container and a disposable Redis 7.4
container as the local runtime gate. Apply all migrations as the administrator,
then run the industry persistence and authenticated server-API contracts with
the configured non-superuser PostgreSQL role. The gate covers:

- manufacturing cost-control PostgreSQL and server API contracts;
- retail settlement PostgreSQL and server API contracts;
- professional invoice-payment PostgreSQL and server API contracts;
- bank-statement PostgreSQL and server API contracts;
- the live PostgreSQL metrics parity contract; and
- the PostgreSQL Alembic command-availability contract.

The containers, synthetic records, and role are disposable and are removed
after the run. This is a local single-host runtime gate only. It does not
promote any vertical slice to a live ERP/bank provider, source authenticity,
payment initiation, statutory posting, write-back, HA/DR, hosted CI, or
production readiness claim.

## Verification

On the 2026-08-11 Windows/Docker Desktop environment, Alembic reached
`0088_pg_currency_snapshot`. The selected runtime contracts passed:

```text
tests/test_postgres_manufacturing_cost_control.py       3 passed
tests/test_api_server_manufacturing_cost_control.py    3 passed
tests/test_postgres_retail_settlement.py               3 passed
tests/test_api_server_retail_settlement.py              4 passed
tests/test_postgres_professional_invoice_payment.py    3 passed
tests/test_api_server_professional_invoice_payment.py 3 passed
tests/test_postgres_bank_statement.py                  3 passed
tests/test_api_server_bank_statement.py                 2 passed
tests/test_application_metrics.py                      1 passed
tests/test_alembic_postgres.py                         1 passed
```

The run produced only the existing Starlette/httpx deprecation warning on
FastAPI TestClient contracts. The containers were removed after verification.
The full local suite, hosted CI, native PostgreSQL backup binaries, and
publication remain separate gates under D-485.

## Rollback

Remove this ADR and the E-716 execution records. No schema, source data,
provider, or deployment state is changed by the disposable runtime gate.
