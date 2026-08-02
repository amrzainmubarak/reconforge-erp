# Reference payment-statement read-only connector

`ReferencePaymentStatementConnector` is a synthetic, provider-neutral bank
statement source. It runs through the existing governed network executor and
accepts only the exact allowlisted HTTPS endpoint.

The closed page contract contains `id`, `account_id`, `bookingDate`,
`valueDate`, exact finite Decimal-text `amount`, `currency`, and an optional
`reference`. Duplicate IDs, unknown fields, non-finite amounts, malformed
dates, and a value date before the booking date fail closed. The result carries
request and canonical response digests plus retry-attempt evidence.

This connector is read-only and synthetic. It is not a live bank connector,
does not post payments, and does not provide write-back or settlement proof.
