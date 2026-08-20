# ERPNext Payment Entry draft write-back

`erpnext-payment-entry-writeback` is a provider-specific contract for an
ERPNext `Payment Entry` draft. It accepts exact Decimal text, requires one
positive paid or received side, rejects same-account transfers, preserves
currency and source references, and emits deterministic `docstatus=0` JSON.

The registration is disabled by default. Any enablement still requires the
existing policy, authenticated maker-checker approval, idempotency binding,
bounded retries, acknowledgement validation, and operator-controlled
compensation rules. The payload builder performs no network I/O and stores no
credentials.

The repository tests use synthetic data and a provider-compatible transport.
They do not establish a live ERPNext tenant, account mapping, posting approval,
vendor idempotency/status behavior, production write-back, statutory
accounting, or an SLA.
