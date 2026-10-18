# 0811: Explicit reviewed operational posting over the Finance Core

Status: accepted for the bounded Manual/full-reversal contract, 2026-10-03.

## Reproduced boundary

The dimensioned Finance Core maintained Draft/Validated/Voided control entries.
Validation was not an immutable operational posting: restricted PostgreSQL SQL
could change validated monetary content or delete its lines/dimensions, and
voiding removed the entry from the control balance. SQLite validated dimension
links remained mutable and voiding committed an outer caller transaction.
A real period-close race allowed validation after a period became Closed.
The synthetic before report remains unchanged; these are separate from the
earlier tenant-scope and currency-provenance repairs.

## Decision

Reuse the dimensioned Finance Core. Add SQLite48/PostgreSQL0098 and a typed,
backend-neutral posting application contract. New authenticated Manual drafts
capture a stable preparer identity; independent validation captures the reviewer,
versioned canonical content digest and currency-policy provenance. Actor labels
never establish identity. Historical entries remain unsealed: neither a username
lookup nor migration invents a reviewer or operational effect for them.

Only that captured preparer may replace the authenticated Draft. An actual
checker replacement followed by successful validation/posting was reproduced
and closed; keeping only the original preparer label would not enforce SoD.

An explicit authenticated human command with finance_core.post and recent
reauthentication creates one immutable operational effect. The preparer cannot
validate or post their entry. The posting command binds actor, operation, scope,
reason and expected review digest. Exact acknowledgement retry returns the same
effect; changed content or actor under the same key conflicts. Entry headers,
lines, dimension links, effects and command receipts cannot be altered after
posting. Audit/outbox and the command receipt belong to the same transaction.
Command receipts must correspond to a retained effect or linked reversal Draft;
replay also verifies the requested source. Exact effect verification binds its
audit/outbox actor, action, object, entry, digest, JSON content and scope. It
rejects borrowed real evidence as well as absent evidence. Full audit-chain
verification remains a separate explicit operation.

PostgreSQL mutations require READ COMMITTED and acquire a fiscal-period shared
lock before testing Open, then an entry update lock. Child mutations lock their
exact old/new parent. Posting changes the parent row version before sealing so a
waiting repeatable-read child writer cannot exploit a stale snapshot. Existing
scope GUCs and outer transaction ownership are preserved. SQLite owns one
explicit transaction for these new commands and rejects unsupported nesting
rather than committing an existing caller's unrelated writes.
An explicit SQLite posting unit of work supports bound operations; a caught
child failure marks the whole owner for rollback. Backup restores through a
temporary unpublished database, verifies retained provenance/effect/evidence
links and reinstalls guards. Public export owns a consistent read snapshot only
when the caller has no transaction; caller pending work is preserved.

A correction prepares a new linked full-reversal Draft using the original
scope, currency policy, exact inverse line amounts and dimension IDs. It requires
independent review and explicit posting. A reversal cannot itself be reversed
under this first contract. Imported/generated control records are not silently
adopted; generated trade posting requires its own later source-effect contract.

Balances include only actual operational effects in the selected fiscal period.
Gross debit/credit turnover and net debit/credit account activity are distinct.
These are not cumulative closing balances: earlier periods and opening balances
are not included. The API declares selected-period-net-activity explicitly.
A full reversal within that period has positive gross turnover and zero net
activity; it preserves the original history. Drill-down identifies each
contributing effect, entry and line, and the API verifies aggregate equality
against those lines. Stored
account/dimension identities are stable evidence; historical master display
labels are not claimed to be captured by this contract.

## Interface and compatibility

New PostgreSQL server endpoints expose preview, explicit post, effect read,
reversal preparation and posted-only trial balance. Permission inventories
declare finance_core.post and the combined manage/reverse contract. Payloads
cannot supply actor or session assurance. Actual cookie CSRF, scope selection
and stronger required session method remain enforced by the existing boundary.

The new finance-posting-api-v1 transmits money as decimal minor-unit strings and
retains the exact canonical snapshot_json string plus its digest. Clients must
verify that original text, without parsing amounts into JavaScript Number and
reserializing. Separate display lines carry exact strings. Existing control
entry response contracts remain closed and unchanged.

The SQLite adapter remains offline. Its authenticated CLI boundary must use real
password verification and stable stored identity; an arbitrary --actor label is
insufficient. The new HTTP posting routes currently require the PostgreSQL
server profile because Community HTTP has no recent-session assurance adapter.
Community control CLI/API compatibility remains available. Full Community HTTP
posting needs a separately verified assurance implementation.

## Acceptance and rollback

Acceptance requires both-backend exact effects/reversal/retry, independent
review, raw DML sealing, period/review concurrency, atomic failure injection,
populated migration/restore, guarded downgrade and real authenticated HTTP/CLI.
SQLite's final101-test gate passes without skips. PostgreSQL's final affected
seven-test gate passes after retained evidence-affinity and preparer repairs;
the earlier81pass/one-native-client-skip broader run remains a separate source-
drifting checkpoint. Actual PostgreSQL HTTP and local password-authenticated CLI
pass. A populated native PostgreSQL16.14 restore preserves two effects, three
command receipts, four legacy-null entries and every history digest, then repeats
scope, receipt-substitution and evidence-substitution denials. Separate native
16.14/17.10 chain reports reach0098 with unchanged migration sources and cleanup.
FINANCE_POSTING_2026-10-03.json retains exact source/artifact boundaries. The
whole-repository immutable snapshot is recorded separately when executed.
Full operational GL, multi-currency books, automatic
stock/subledger posting and complete trade cycles are not inferred from this
Manual/full-reversal slice.

No lossy downgrade may discard operational effects, command receipts or sealed
review provenance. Restore a compatible pre-upgrade backup under operator
control and reconcile subsequent writes. Reverting guards restores demonstrated
weaker controls. No production action or release is included in this decision.
