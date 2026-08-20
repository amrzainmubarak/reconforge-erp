# ERPNext Journal Entry draft write-back

`erpnext-journal-entry-writeback` is a provider-specific payload and transport
contract for ERPNext's Journal Entry REST resource. It validates exact
non-negative Decimal debit/credit text, requires each line to have one positive
side, requires the full document to balance, and serializes a deterministic
`docstatus=0` draft document. The registration uses ERPNext `token`
authorization and the governed write-back executor.

The registration is feature-disabled by default. Enabling it requires the
existing policy, authenticated maker-checker approval, idempotency binding,
bounded retries, response acknowledgement, and compensation controls. The
payload builder performs no network I/O and stores no credentials.

This is synthetic transport and provider-schema evidence. It is not evidence
of a live ERPNext tenant, account mapping, posting approval, provider
idempotency behavior, production write-back, statutory accounting, or an SLA.
