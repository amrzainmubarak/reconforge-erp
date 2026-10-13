# Explicit-source group reporting diagnostic

This read-only diagnostic reconciles one to sixteen explicitly selected complete
IC2 paired-trade sources. Select each original source and source digest, known-zero
origin plan and digest, final native elimination plan and digest, and original
management report digest. All source IDs must be unique and sorted. No missing
opening is inferred, and the request never silently discards a selected member.

The first contract uses the same qualified tenant, workspace, organization and
three native book entities. It also retains one exact captured registry/reporting
policy, native group adjustment journal and account ID/chart/role map. Different
source periods are supported when every original native entry is covered by its
exact referenced native period. This is selected membership, not a complete group
or a complete fiscal-period population.

For each source, all party account translations are rebuilt through existing IC2
`translate_book` and captured policy/rates. `group_report` retains translated
membership separately from original native adjustment lines. The diagnostic shows
translated, native adjustment and combined balances by role, with source/report
drilldown. Each column balances independently. It also checks the selected income,
balance-sheet, CTA and source Cash equations. It writes no GL, financial claim,
approval, period transition or schema, and introduces no currency calculator.

The actual synthetic two-source development capture contains fourteen native
effects. Its translated reporting Cash is 202 minor units, native adjustment Cash
is 0, and combined Cash is 202. Its income result is 784 and CTA equity is -582. This
bridge is deliberate: the translated party view is not the native adjustment
entity's Cash ledger. The complete original capture is 788853 bytes, raw SHA256
`843a87f664c5128bff62204073d5fb6330913701da627d8ed0d6fb34be204360`.

Source SHARE retention follows canonical sorted source order. Current identity,
permissions and hierarchy grants are admitted before source waits and checked by
the existing source owner for every captured source/plan. The diagnostic adds no
period row lock. Exact referenced period metadata is captured by one read-only
statement after retaining source histories; it is an observation at that statement,
not a promise that the status cannot change after capture. A native regression
proves another connection can obtain the period row `FOR UPDATE NOWAIT` while the
diagnostic retains its source locks. Formal Close task approval and readiness
remain unassessed.

Both `intercompany_fx.read` and `finance_core.read` cover original functional and
transaction contexts, per-source reporting values, and every displayed aggregate
reporting maximum using captured reporting precision. The actual aggregate guard
fixture permits each original source under USD 200 and refuses a USD 200.02 aggregate value.
The earlier USD 150 fixture was invalid because the source's own native elimination
amount is USD 170.02; that failed receipt is retained. This is a current central policy
evaluation test, not a claim that a ceiling is persisted in the source.

The GET query contains strict bounded JSON `selection` with a `pins` array. Each
pin contains the explicit `opening` object, `elimination_plan_id`,
`elimination_plan_digest` and `report_digest`. Duplicate JSON fields, unknown fields,
floating/boolean opening money, repeated sources and oversized selections are
refused. The summary exposes exact minor amounts as decimal integer strings.
The evidence route streams the complete original source captures and observed
period rows with the existing 64MiB/one-million-node artifact bounds. The canonical
transport coalesces unchanged codec bytes into at most 64KiB chunks; no database
connection or authorization work is retained by the response generator.

The independent verifier checks an externally retained raw SHA before parsing,
requires fresh exclusive output, and executes only stdlib code. It verifies the
existing source Cash oracle's exact source SHA before loading it, then independently
derives every translated account and CTA through exact Fraction arithmetic using
original native lines and captured historical/closing rates. It checks the original
native adjustment population, full reporting bridge, source pins and observed
period membership. It does not re-evaluate current authority or recompute the
complete audit chain. Normal and optimized isolated execution accept the original
two-source capture with byte-identical proof outputs.

```text
python -I .github/scripts/verify_intercompany_group_diagnostic.py original.json --sha256 <retained-original-sha> --output fresh-proof.json
python -I -O .github/scripts/verify_intercompany_group_diagnostic.py original.json --sha256 <retained-original-sha> --output another-fresh-proof.json
```

The first helper adversarial run exposed boolean zero comparing equal to integer
zero in Python dictionaries. The red mutation receipt is retained; the current
helper explicitly checks every displayed minor amount as a bounded exact integer.
The runtime derives native integer amounts. Forty-nine pure, strict-selection and
file-only oracle cases pass on the corrected helper. Targeted native proof covers
the two-source fourteen-effect cycle and both current aggregate amount permissions;
the ordinary authenticated report/export target also passes with exact original
length/SHA, complete source equality and unchanged financial populations. Its first
failure was a tuple/list representation mismatch in exported selection containers;
the current containers are explicit JSON lists, with unchanged serialized digests.
These original failures are retained separately. UI and HTTPS execution are not
claimed for this diagnostic.
PostgreSQL is required and SQLite is explicitly unavailable. Country statutory
packs remain zero, and comparative performance measurement remains deferred.
