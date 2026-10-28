# Unknown reconciliation worker amount — 2026-10-28

On entry `c44a71110dd63f3ef2372c0bc8d451f91d3424d7`, a synthetic policy
context with a bounded amount and an unrelated supplier amount could authorize
an operation whose actual amount was unknown. ADR0882 adds an explicit unknown
token for reconciliation execution while preserving the previous meaning of
omitted and `None` amounts for other callers and discovery. A bounded policy
now rejects the unknown operation before claim; it is not treated as a skipped
or successful job.

The unit-level RED reproduced both the shared-policy and worker failures. The
final focused Python 3.14 group reported 84 passed, 3 skipped and one legacy
input warning. A Python 3.12 subset reported 39 passed, 1 skipped and the same
warning. An independent review checked compatibility of scheduler/outbox,
discovery and execution and exercised a second, bounded reauthorization before
claim with a repository double. A separate native test on PostgreSQL 16 with
ordinary NOSUPERUSER/NOBYPASSRLS role and FORCE RLS on the run table reported 5 passed / 0 skips
(`output/worker-amount-native-d314bd93f003/result.json`, 16.168 s including
setup), including `process_once` with a stored amount both below and above the
policy ceiling. The entry HEAD was `aeabb354` with uncommitted worker/test bytes;
the runner captured their individual hashes at start, not a whole-tree freeze.
Its test role had broad table
grants and does not establish least-privilege provisioning. Earlier fixture
failures, including an empty matcher that failed conservation, remain in the
task output. Input totals in the final fixture match chosen policy values, but
the worker did not calculate them; the test does not prove exposure derivation.
Snapshots cover the run, inputs, results, exceptions and checkpoints, not all
audit or outbox records.

The hosted security scan on successor `5c41ec91` rejected the original enum
member `TOKEN = "unknown"` as Bandit B105 (hardcoded password). The enum is a
non-secret marker; it was renamed rather than suppressing the scanner. Bandit
subsequently passed locally on Python 3.12, and the worker/backlog focused set
reported 44 passed, one prerequisite skip and one legacy input warning. The
renamed worker passed all five native cases on PostgreSQL 16 without skips
(`output/worker-amount-native-b317139a1baf/result.json`, 17.5 s including
setup); hosted checks remain required. The 5c41 local full pytest was
interrupted at 3% before the rename and is not a full-suite result.

The change does not bind a caller-provided known amount to the persisted run,
validate historic derived amounts or define cross-currency limits. A fake
repository reproduction showed a direct caller can supply a smaller amount
than the stored value; its live reachability is not established. The later
per-page isolation change counts denials and continues other runs on that page,
but durable audit and fairness across pages and restarts remain open. See
`RECONCILIATION_CLAIM_AUTHORITY_GAPS_2026-10-28.md` and
`RECONCILIATION_EXPOSURE_REPLAY_2026-10-28.md`; hosted final-source checks,
native restoration and restricted production grants are still required.
