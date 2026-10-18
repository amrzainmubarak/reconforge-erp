# Offline open-source reconciliation acceptance

The checked-in IBM AMLSim sample is pinned to commit
`7338a4bcb1af9bcfea2201ad7daccfe2a4d569ca`. Its original 45 synthetic rows and
Apache-2.0 license are preserved under `tests/fixtures/amlsim`, with attribution
and checksums. No generator code, Java stack or network dependency is required.

From a development installation with the repository's locked dependencies:

```powershell
python .github/scripts/verify_amlsim_reconciliation.py --output output/amlsim-evidence.json
python -m pytest tests/test_amlsim_reconciliation.py tests/test_matching_strict_constraints.py
```

The [versioned profile](amlsim-workload.v1.yaml) explicitly assigns USD, two minor
places and an epoch of 2000-01-01. These are synthetic scenario assignments:
upstream supplies numeric step values and amounts without currency or absolute
dates. The adapter rejects aggregate rows, malformed amounts, source-identity
duplicates, schema changes and input-digest mismatch before matching.

The right side is derived from the same source, with four declared faults:

| Source transaction | Derived scenario | Expected decision |
| --- | --- | --- |
| 2 | Remove its right-side record | Left remains unmatched |
| 4 | Add one minor unit to the right amount | Both records remain unmatched |
| 10 | Duplicate the right record with a separate stable ID | One pair matches; one right record remains unmatched |
| 11 | Delay the right date one day beyond the zero-day window | Both records remain unmatched |

The independent oracle requires 42 matched pairs, three unmatched left records
and three unmatched right records, with exact identity/amount/date checks for
every selected pair. It rejects the compatibility scored matcher, which can
select the changed-amount/late-date candidates. The new engine opt-in policy
`strict-one-to-one-v1` enforces constraints before assignment and preserves
bounded rejection explanations. Existing rule/API/worker defaults are unchanged.

The [retained execution](../execution/OPEN_SOURCE_AMLSIM_2026-10-03.json) records
upstream provenance, source/canonical/rule/decision digests,
permutation replay, elapsed/CPU time, environment and source hashes. The memory
measurement is explicitly Python allocations from tracemalloc, not process RSS.
This module proves a bounded in-process fault oracle. It does not prove
PostgreSQL processing volume, an official AMLSim/FinBench benchmark, AML/fraud
efficacy, customer hours saved or independent auditor acceptance. Larger inputs,
durable-worker restart and company outcomes remain separate acceptance gates.

The source repository and licensed artifact are linked in the
[fixture notice](../../tests/fixtures/amlsim/NOTICE.md). The
[module manifest](../modules/amlsim-reconciliation.yaml) records the boundaries,
test matrix and rollback. Removing this optional module requires no database
migration and does not alter existing financial records.
