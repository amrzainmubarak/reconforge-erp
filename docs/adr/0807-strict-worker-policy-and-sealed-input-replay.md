# ADR0807: Preserve strict policy and canonical inputs through durable execution

Date:2026-10-03

Status:Accepted for the repository and worker paths

The pure matcher supported explicit strict constraints, but the PostgreSQL worker
adapter omitted that persisted option. The actual pinned AMLSim scenario exposed
the resulting difference: legacy matching selected44 pairs, whereas the strict
fault oracle requires42. Preserve historical omission as `legacy-scored-v1` and
forward explicitly selected `strict-one-to-one-v1`. Unknown policies, malformed
strict date windows and grouped flags fail before matching, with durable failure
evidence and no decision effects.

Real registration also rejected unchanged amounts because PostgreSQL NUMERIC
returns its declared scale. Compare validated finite Decimal values exactly,
without ambient precision arithmetic. Bind every canonical field, including
currency, parsed date, original text, reference, attributes, valid flag and use
count; an unchanged caller-supplied fingerprint cannot authenticate altered data.
Existing text normalization remains unchanged; this is not raw-byte preservation.

New inputs are accepted only while the run is Running/Queued, attempt0, with no
cancellation request. Registration and claim lock the same parent row. Once the
run is sealed, exact replay reads the existing row without INSERT; a new source
ID or changed payload fails. Submit the complete canonical batch and its run in
one transaction before exposing it to workers, as current API/synchronous
submission already does.

An actual REPEATABLE READ race showed a claimer waiting for the registrar but
then missing its committed child input in an older snapshot. Require explicit
READ COMMITTED for claims and new registration. Do not silently change caller
isolation. Stable exact replay can remain read-only under the older snapshot.
READ COMMITTED races are exercised in both orders with observed backend lock
waits: registration-first is visible to claim; claim-first denies registration.

The real45-row IBM/AMLSim sample executes on PostgreSQL16.14 through production
migrations0094 and0096. Both runs persist42 pairs and3unmatched rows per side,
equal semantic decisions under reversed input order, verified input/result
hashes, policy lineage and audit/outbox lifecycle. Identical registration keeps90
inputs. Expired-claim recovery at attempt2 persists48 decisions once; this models
lease interruption, not OS-process termination. Three malformed rule jobs fail
with no decisions. Sibling worker execution and RLS reads are denied.

The focused gate passes257 tests with two explicit live-DB skips; the separate
actual runner supplies live evidence. It remains an opt-in CI operation that
creates and removes a fresh synthetic database. The retained
[report projection](../execution/POSTGRES_AMLSIM_WORKER_2026-10-03.json) binds the
full original runtime artifacts, source hashes, independent oracle and previous
failures. The original upstream fixture/license/projection are unchanged.

This acceptance is bounded to repository/worker behavior. A separate raw SQL
INSERT-after-Complete reproduction invalidated the stored input manifest, while
existing completed-row UPDATE and lifecycle relabeling were denied. PROD030
adds a database gate; this ADR does not declare it implemented. No scale,
customer ROI, financial posting, AML efficacy or auditor acceptance follows
from this small synthetic workload. Reverting the forwarding changes restores
the demonstrated strict-policy mismatch; preserve retained rule semantics when
rolling back or stop affected jobs until a compatible worker is restored.
