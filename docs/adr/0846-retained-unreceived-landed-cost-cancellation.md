# 0846: Retained unreceived landed-cost cancellation

Date: 2026-10-10
Status: Accepted for experimental native PostgreSQL operations

The paid landed-cost bundle prepares its native merchandise receipts and cash
entry before review. An incorrect bundle therefore reserved purchase quantities
permanently even when no inventory, cash or GL had been published. Deleting these
drafts would discard immutable source evidence and previous acknowledgements.

Add an immutable, forced-RLS cancellation owner record for bundles in their
original Prepared or Reviewed phase. Its human must hold current reviewer
authority, be independent of the preparer and, after review, of the reviewer too.
The retained record seals the exact request, reason, acknowledgement, audit and
outbox references. Review and posting of a cancelled bundle fail closed. Posted
bundles remain subject to a future complete financial reversal contract.

Keep the original bundle phase, native draft/review, allocation records and
historical command responses unchanged. The current projection reports
`status=Cancelled` and its independent cancellation evidence. Purchase capacity
excludes only receipts belonging to a valid retained cancellation. Original
receipt identities, numbers, sequence limits and document budgets remain retained.
Repreparation creates fresh evidence and fresh receipt identities. Quantities
from different units are never added; partial reservations and release use exact
integer/decimal arithmetic.

Cancellation and publication lock the same bundle and purchase parent. Under
READ COMMITTED, concurrent publication, cancellation and new reservations observe
a serial business effect. Lost acknowledgements return the original exact
response and repeat current authority checks. Deferred SQL closure also denies
raw cancellation forgery, detached receipt publication, evidence mutation and
cash publication after cancellation.

Native receipt plans identify paid charges before any new owner-index read:
at least one selected receipt must exceed its original merchandise cost because
the bundle has a positive conserved charge. This includes bundles whose other
allocations round to zero. Ordinary native procurement and receipt roles therefore
need no privileges on landed-cost tables. A narrow current receiving participant
admits the charged allocation lookup when the bundle first prepares its receipts;
database closure independently verifies the exact allocation.

The additive migration refreshes installed owner dispatch and capacity closure.
Empty cancellation storage can downgrade; retained cancellations refuse downgrade.
Restore must include cancellation records together with their original native
sources, audit, outbox, quantities and financial evidence. API, Studio in English
and Arabic, native SQL attacks, concurrency, replacement receipt cycles and
populated browser restore are the acceptance surfaces. This does not establish a
supplier return, debit note, landed-cost reversal or production scale claim.
