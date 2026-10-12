# Verify AR invoice creation identity before acknowledging retry

Status: accepted for bounded SQLite/PostgreSQL invoice recovery; whole/hosted gates remain separate.
Date: 2026-10-03
Scope: PROD039, invoice creation on the existing SQLite/PostgreSQL adapters.

Authenticated HTTP reproduced two integrity gaps on both backends: a changed
request reused a successful key and received the old invoice, and a corrupted
stored response could redirect to another visible source or assert fabricated
amounts. Separate administrative synthetic corruption proves incomplete receipt
verification; it does not establish an ordinary HTTP cache-writing capability.
Current scope/RLS still refused hidden objects in the measured cases. The final
before-fix probe independently hashes actual business, AR audit and Outbox rows.

The command must validate exact request identity before returning success.
Persist an internal versioned envelope in the existing response column, with a
canonical request digest and the original acknowledgement. Resolve requested
customer and canonical hierarchy under current authorized scope; neither cached
source IDs nor cached amounts establish authority. Verify immutable backing
invoice identity, ordered line content and retained monetary policy separately.
Serialize the scoped command key before lookup/creation and retain atomic
invoice/line/audit/Outbox/success-receipt effects. Failed commands retain no
successful receipt.

Preserve the public historical Draft/version1 acknowledgement after submission,
approval or cash allocation. Authorized GET continues to expose current state.
Exact recovery uses retained interpretation and independently readable original
customer after registry changes or customer inactivation; canonical organization
and entity resolution still requires active masters. First creation keeps its
current active-parent and policy prerequisites. Current requesting authority is
checked each time. Workspace-authorized humans retain the existing recovery
semantics; the immutable creator is verified, not replaced with the recovering
actor. No creator-only restriction is introduced by this repair.

Compatibility reader: old raw acknowledgements remain recoverable only when
their complete identity and immutable backing content can be independently
proved. Their omitted due-date intent is ambiguous: the original date may have
been supplied or derived from then-current customer terms. Today's terms cannot
reconstruct that historical intent. An old raw receipt with omitted due_date
therefore fails closed and directs the authorized caller to GET the known
invoice. An explicit due date still requires complete independent source proof.
No guessed digest, current-policy substitution or duplicate creation is allowed.

This is an explicit bounded retry-compatibility restriction. New commands retain
both explicit-versus-omitted intent and the original resulting date. The raw
reader remains available for independently provable old commands; no stored
receipt is automatically rewritten. The public request/response shape is stable.
The existing column can hold the versioned envelope without a schema migration;
any actual storage-guard incompatibility requires a separately reviewed migration
before publication. Release notes must describe GET fallback and prohibit
retrying an uncertain legacy command under a different key.

Required acceptance: both adapters and actual authenticated HTTP reject changed
header/amount/customer/currency/date/line/order/scope and corrupt cached source,
content, policy or wrapper. Preserve exact historical acknowledgement and
current GET, revoked-authority denial and authorized workspace recovery. Use
two physical connections for exact/conflicting key races and inject late
audit/Outbox/key-persistence faults. Independently verify all business/evidence
rows and owned cleanup, then freeze source hashes for focused and broader gates.
No receipt/allocation protocol, generated GL or complete trade workflow is added.

Rollback: preserve verified backups and committed command history. Redeploying a
reader that cannot verify the envelope must refuse recovery and permit current
authorized GET; it must not treat the envelope as an invoice or create a duplicate.
Retain the raw compatibility reader without inferring missing historical intent.
Actual acceptance:331AR/API/cash/codec tests pass without skips on SQLite and
PostgreSQL16.14 under a nonowner runtime role. A separate native pg_dump/restore
test passes with1,188,108bytes and equal source/restored financial history;
SQLite backups include a true pre49 raw receipt after48-to49 migration. Frozen
nine owned files and1,208participating Python files remain unchanged. Independent
source review finds no blocker. Root independently confirms all four final-gate
owned databases are absent. Original red/93pass-3fixture-failure/numeric-text
failure artifacts remain retained in RECEIVABLES_INVOICE_RECOVERY_2026-10-03.json.

Two physical connections verify exact/conflicting key serialization at PostgreSQL
READ COMMITTED. An externally established REPEATABLE READ snapshot may refuse a
conflict safely; the command does not silently change caller isolation. The public
DB export still excludes AR command history; only tested local/native backup
profiles establish restore evidence. No receipt/allocation protocol is changed.
