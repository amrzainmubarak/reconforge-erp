# Reference payment-statement read-only connector

`ReferencePaymentStatementConnector` is a synthetic, provider-neutral bank
statement source. It runs through the existing governed network executor and
accepts only the exact allowlisted HTTPS endpoint.

The closed page contract contains `id`, `account_id`, `bookingDate`,
`valueDate`, exact finite Decimal-text `amount`, `currency`, and an optional
`reference`. Duplicate IDs, unknown fields, non-finite amounts, malformed
dates, and a value date before the booking date fail closed. The result carries
request and canonical response digests plus retry-attempt evidence.

Callers may pass `expected_account_id` to `read_page`; a returned page that
contains another account fails closed. The focused suite also runs the real
governed HTTPS transport against a disposable TLS sandbox with transient retry,
cursor propagation, address pinning, and secret-redaction assertions.

This connector is read-only and synthetic. It is not a live bank connector,
does not post payments, and does not provide write-back or settlement proof.
