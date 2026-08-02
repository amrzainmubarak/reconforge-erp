# Reference ERP read-only connector

`reference-erp-readonly` is a provider-neutral ERP ledger-line integration
example. It uses the governed HTTPS data-only runtime and accepts only a
secret reference; it does not contain a vendor credential, call a real ERP, or
write back.

The page schema is `reference-erp-ledger-page-v1`. Each page is bounded,
entity-scoped, cursor-addressable, idempotent, and rejects non-finite or
non-Decimal amount text, duplicate IDs, and mixed entity pages. Responses are
canonicalized and hashed for replay evidence.

The allowlisted synthetic endpoint is:

`https://erp.example.test/v1/ledger-lines`

Provider onboarding still requires an independently reviewed manifest,
credential provisioning, endpoint allowlisting, provider-version tests, and a
separate governed write-back contract.
