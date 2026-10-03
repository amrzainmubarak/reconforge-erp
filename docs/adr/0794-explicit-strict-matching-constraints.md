# ADR 0794: Add an explicit strict one-to-one matching policy

Date: 2026-10-03. Status: accepted for implementation.

The indexed matcher combines reference, amount, date and key scores. A candidate
with a matching reference/date/key can exceed the selection threshold even when
its amount is outside tolerance; a late date can similarly remain eligible.
That scored compatibility behavior is inadequate for an exact reconciliation
fault oracle. Changing it globally would alter retained decisions and replay.

Add an opt-in `constraint_policy="strict-one-to-one-v1"` to the pure deterministic
engine. Preserve the default `legacy-scored-v1` behavior and digests. In strict
mode, validate currency, amount tolerance, date window, declared exact fields and
source quality before assignment; reject grouped flags. Rejected candidates must
not occupy a match or prevent an eligible alternative from being selected.
Retain bounded rejection examples and complete in-budget reason counts, with the
policy identity in strict lineage. Existing candidate ceilings remain enforced.

Run strict arithmetic under a private context based on bounded input precision;
never rely on the caller's Decimal precision or use a float for money. Strict
financial text/coefficient length is capped at 512 and derived context precision
at 4096 before matching. Caller ingress still owns the source-record volume cap.
Test
boundaries, permutation, duplicate ambiguity, invalid inputs, eligible alternative
selection and unchanged legacy digests. Registering this option in public rules,
repository services and hosted worker contracts is a separate versioned slice;
the initial caller is the offline AMLSim benchmark. No production matching rule
is silently migrated. Rollback removes the opt-in path without changing stored
historical output.
