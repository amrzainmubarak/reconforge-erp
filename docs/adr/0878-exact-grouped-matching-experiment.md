# ADR 0878: Experimental exact grouped-matching contract

Status: experimental; 2026-10-27. Production release remains blocked.

The existing experimental grouped algorithm `bounded-grouped-subset-sum@1.0.0`
uses ambient Decimal arithmetic. With precision 3, the distinct amounts
123456789 and 123456780 incorrectly compare equal; with precision 28 they do
not match. Even default precision 28 falsely matches the distinct 29-digit
integers 12345678901234567890123456781 and 12345678901234567890123456780.
The original negative reproductions are retained at
`output/enterprise-program-20261026/grouped-decimal-context-negative-20261027.log`
and `output/enterprise-program-20261026/grouped-decimal-default-negative-20261027.log`.
Independent QA also reproduced a signed-zero replay difference: the same
one-to-many match can receive a different v1 decision digest under ROUND_FLOOR
and ROUND_HALF_EVEN without setting Inexact. Evidence is retained in
`output/enterprise-program-20261026/qa-v1-signed-zero-20261027.json`. This is
a financial correctness and deterministic replay blocker, not an assertion
that any posted ledger was affected.

`match_exact_groups_v2` is an opt-in, non-posting domain entry point. It evaluates
already-normalized records under an explicitly bounded Decimal
context; groups must share a currency. It traps inexact arithmetic, retains unresolved-ambiguity
behavior, and binds a separate algorithm version, full input/policy fingerprint,
and result digest into an artifact digest. The caller supplies a validated,
immutable currency registry context. Unknown
currencies and amount, fee or tolerance values not exactly representable at
the relevant currency precision are refused; extra trailing zeros are allowed.
Registry version and digest are bound to the input fingerprint and returned.
Precision, exponent, identity length, record count and cardinality are bounded.
The declared total bounds candidate-pair evaluations plus portfolio-search nodes;
left-group enumeration has a separate phase-sized ceiling and is not included in
that counter. There is no wall-clock or general CPU performance guarantee. FX
conversion, persistence and review workflow are not supplied by this entry point.
The fingerprint is content evidence: tenant/workspace, rule-set, run and actor
identity must be bound by an authorized application layer. Fingerprints are
sensitive metadata and must follow deployment classification policies.

The v1 algorithm, manifest and stored results remain untouched. The PostgreSQL
adapter adds an operational fail-closed gate: it checks the enclosing Decimal
context for `Inexact` before returning partition results. A formerly accepted
inexact job can now fail; its old stored output is not rewritten, and replay of
an affected historical execution requires its original software environment.
The guard does not observe inexact operations in nested contexts such as FX,
change checkpoints already committed by previous attempts, or resolve the
signed-zero digest drift. It is a partial safety mitigation, not v1 acceptance.
The new v2 entry point is not wired to current users or jobs and must not be described
as a completed production fix. Before migration: define a versioned worker and
rules schema; distinguish old jobs and replay by algorithm version; persist the approved
currency registry context; prove persistence, permissions,
audit, outbox, cross-engine parity, performance budgets and failure recovery;
provide migration/rollback and preserve historical records without reinterpretation.
Reverting the isolated module removes the experimental entry point; never apply
it to historical v1 decisions under the old version label. Reverting the adapter
guard restores prior behavior and can re-enable erroneous matches; it is not a
safe operational rollback without isolating the grouped worker first.
