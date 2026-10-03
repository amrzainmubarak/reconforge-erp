# Post a reviewed inventory receipt and unused inverse under one owner

Status: proposed; implementation and acceptance in progress.
Date: 2026-10-03
Scope: PROD038, single-line receipt and separately reviewed full unused inverse.

The current Inventory valuation bridge creates Generated Finance Drafts. Finance
operational effects accept only reviewed Manual entries and their reversals.
Linking existing documents alone cannot establish one committed operational event
or enforce a source-specific correction boundary.

Implement an immutable prepared source plan, independent human review, complete
source/output link and success-only command receipt. The plan includes canonical
scope, server-assigned source/output identities, exact quantity/value, retained
monetary policy, mapping and financial snapshot digests. It is immutable in this
first lane; there is no replacement Draft or caller-supplied posting capability.
Persisted stable identities govern maker/checker separation and current posting
authority; actor labels alone do not certify a human review.

PostgreSQL first, then the same contract under SQLite's explicit owner. One outer
owner commits the Posted physical receipt, Approved valuation, FIFO origin,
review-sealed Generated entry, one operational Dr Inventory/Cr GRNI effect and
their command/audit/outbox evidence. Children never finalize independently.
Materialize the exact Generated Draft and lines, approve valuation while preserving
its existing status guard, apply the independently retained review seal, then
write the operational effect. Current Manual posting remains restricted.

Recognize reserved output IDs from the persisted plan even before a complete link
exists. Deferred references and source guards reject a partial commit. Add closed
Inventory source kinds to the existing effect store and verified readers; do not
create a second GL or relax the public Manual command. Early application and raw
storage guards refuse generic GL reversal, legacy movement void and valuation
correction of owned sources.

All artifact IDs and document numbers use a dedicated IRP1 prefix. Case-variant
reserved-prefix admission is refused unless exact canonical reviewed ownership
exists, including parent/child IDs and both Finance lines. The migration refuses
any preexisting collision without modifying it. This unconditional namespace
guard closes the race where a new plan and a legacy insert both observe absence;
unique rows and deferred links alone do not close that race. Actual tests must
exercise same-ID and different-ID/same-number conflicts in both orderings.

Preserve literal legacy physical/FIFO/layer lock namespaces and one consistent
lock order. Lock fiscal periods and mutable canonical parents before effects.
Exact retry uses current authority and independently verified original linkage;
legitimate later consumption does not invalidate the original receipt success.
Do not silently change a caller's PostgreSQL isolation.

The0100 storage guard requires READ COMMITTED for ordinary movement posting and
voiding status transitions as well as reviewed source mutations. It takes the
existing physical/FIFO locks before observing receipt association, then checks
nonnegative Internal stock only for receipt-associated resources. A repeatable-read
absence snapshot cannot bypass this boundary. Ordinary Draft editing and read-only
repeatable-read stay available; this declared write-profile restriction neither
lowers caller isolation nor changes unrelated stock policy. New receipt admission
requires an Internal location that disallows negative stock.

Entity-scoped reference reads retain restrictive Finance metadata UPDATE RLS.
Use sorted paired tenant/table/ID advisory locks followed by ordinary authorized
SELECT for chart, journal and account admission; additive invoker mutation guards
acquire the same SQL-derived keys. No scope GUC widening or definer privilege is
introduced. Metadata Active races must wait and recheck. A DELETE can already hold
a tuple lock before its advisory guard, so test complete success or full rollback,
raw deletion refusal and safe identical retry; do not claim deadlock-free behavior.

Full inverse is a new separately reviewed source using the existing Delivery
movement kind and normal valuation-reversal Remove evidence. Prove its original
receipt is unused under source/layer/dependency locks; matching remaining balance
alone cannot rule out consumed-then-restored history. Where the legacy model cannot
prove lineage, explicitly refuse unsupported dependencies rather than infer
chronology from transaction-start timestamps. Final precise refusal limits must
be documented with tests before acceptance.

The selected v1 inverse predicate also refuses other historical Posted/Voided
outbound or Transfer movement for the same entity/item, excluding its own planned
inverse. It may conservatively refuse an untouched receipt on a resource with
older outbound history. This bounded limitation is explicit until source-allocation
lineage can prove narrower dependency claims. Queries remain scoped and indexed.

Preserve the existing FIFO chronology key of business date and movement number.
Reserved generated movement numbers contain deterministic hashes, so a later
prepared same-day receipt can sort before an already Approved receipt and be
refused. Verify the same accepted/refused order on both engines and zero partial
effects on refusal. This is a material v1 operational restriction, not an assertion
that arbitrary same-day receipt order is supported. PROD040 separately addresses
intraday ordering without silently changing retained valuation or consumption.

Reserved schema identifiers: SQLite50 and PostgreSQL0100, based on inspected
SQLite49/PostgreSQL0099. Keep historical SQL unchanged. SQLite needs an atomic
populated effect-table rebuild with data, guards, indexes, foreign-key verification
and migration markers committed together. PostgreSQL extends named checks/guards
transactionally; direct installation and migration must agree. Populated downgrade
refuses loss of source/review/link/command evidence.

Required proof: actual10units/value12000 on both engines, real human review,
complete raw bypass denials, exact/no-repeat recovery, late faults after each
stage, observed physical races, full unused inverse, existing Manual/Core/FIFO
compatibility, populated upgrade faults, SQLite coherent backup and native
PostgreSQL restore with nonowner RLS/guard/evidence readback. Root owns interface
registration and public claims after this backend proof; no placeholder API or
screen is added.

The read-only design is retained in PROD038-IMPLEMENTATION-PLAN.md. It is a design
snapshot, not runtime acceptance. This lane does not implement purchasing/AP,
sales/AR, taxes, FX, lot/serial, manufacturing, partial inverse or universal
Inventory=GL. The initial oracle is a synthetic receipt; no customer outcome or
production deployment claim follows.

Rollback: preserve a verified pre-upgrade backup, immutable prepared/reviewed
sources and committed effects. An incompatible reader must refuse new source
kinds. Restore only through a verified profile; never delete retained operational
evidence or rescale money to make a downgrade pass. Final rollback/native restore
evidence remains an acceptance requirement.
