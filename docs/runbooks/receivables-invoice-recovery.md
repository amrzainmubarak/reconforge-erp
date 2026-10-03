# Recover an uncertain AR invoice creation

Scope: the existing authenticated invoice creation API on SQLite and PostgreSQL.
This runbook covers acknowledgement recovery, not receipt allocation or GL posting.

Before sending a creation command, retain its exact normalized request and stable
idempotency key in the authorized caller's operation context. The React workspace
keeps an uncertain request in memory and requires an explicit retry. Do not put
session proofs, passwords or financial payloads in browser storage or logs.

After a timeout or lost response, authenticate again when necessary and recover
under the same authorized tenant/workspace/entity scope. Send the original
request with its original key. Do not edit its customer, number, dates, amounts,
currency, lines or line order, and do not choose a new key to bypass a refusal.

A successful retry returns the original creation acknowledgement: Draft/version1
and the original creator, dates, policy, line identities and amounts. The invoice
may already be submitted, approved, cancelled or paid. Read
`GET /api/v1/receivables/invoices/{invoice_id}` under current authorization before
choosing a subsequent action; use that response's current status and version.
An acknowledgement is evidence of creation, not a current balance query.

The server verifies the key's request digest against an independently resolved
invoice and ordered backing lines. It also verifies retained monetary policy,
original attribution and the complete historical acknowledgement. PostgreSQL
recovery checks its numeric quantity against the retained quantity text. A
changed request, redirected source, fabricated amount or corrupt acknowledgement
fails without another business/audit/outbox effect. An authorized human in the
same workspace may recover the original command; attribution remains original.
Current permission and scope checks apply to every attempt.

Recovery tolerates a later suspended customer, changed payment terms and a new
workspace registry binding. Canonical organization/entity resolution still
requires currently active masters. A new creation still requires an active
customer and current policy affinity. Standard concurrent recovery is verified
under PostgreSQL READ COMMITTED; an externally established REPEATABLE READ
snapshot may refuse a conflict safely instead of transparently observing a newly
committed key. Do not change a caller's transaction isolation silently.

Historical raw command receipts have no retained explicit-versus-omitted due-date
intent. A raw receipt with an explicit matching date remains readable only after
complete source verification. A retry that omits the historical due date fails
closed: today's customer terms cannot prove what happened originally. Use the
known invoice ID and authorized GET; investigate the existing operation rather
than retrying under a different key. No raw receipt is automatically rewritten
or assigned a guessed request digest, and no policy is inferred for pre-policy
records.

For a corrupt response or unresolved operation, preserve the operation identifier,
safe error code and request correlation reference. Use approved backup and
incident procedures to compare backing records and evidence; do not manually edit
the success receipt to make the retry pass. Financial content belongs in the
authorized evidence store, not a public issue or diagnostic log.

Verified recovery tests include actual SQLite backups and native PostgreSQL
`pg_dump`/`pg_restore` after payment, customer suspension and registry rebinding.
They preserve the original acknowledgement and current Paid read without another
effect. The public DB export contract does not include AR command history and
must not be used as an AR recovery backup.

Rollback must preserve captured policy and committed command history. An older
reader that cannot interpret the internal versioned envelope must refuse
acknowledgement recovery and permit current authorized GET. It must not return
the envelope as a public invoice or create a replacement invoice. Validate an
operator's actual backup/restore profile before relying on it.
