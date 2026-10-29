# Reconciliation source authority and result collision — 2026-10-28

**Status: reproduced; repair and final-source qualification pending.** The
following observations concern synthetic data in a test environment. They do
not establish production exploitability, the number of affected historical
runs, or a financial posting. They are separate defects: source fields can be
overridden before matching; persisted result collisions can conceal differing
output behind a later checkpoint.

## Source authority can be overridden

The submission [API](../../reconforge/api/routes/reconciliation.py) forwards
the supplied `attributes` alongside the canonical source fields. In the local
matcher [adapter](../../reconforge/workers/postgres_reconciliation.py),
`_canonical_record` uses `setdefault` when adding source ID, amount, currency,
date and reference. Existing attribute keys can therefore take precedence over
the separately stored fields. The repository validates result IDs against
registered inputs, but an attribute ID equal to a *different* registered input
can satisfy that existence check while misattributing the result.

An in-process synthetic adapter probe used the real matcher and independently
changed each attribute. It observed `Matched` for amount `1` versus `999`,
EUR versus USD, January versus October, and reference `OTHER` versus `REF`
when the corresponding attribute instead matched the right side. An ID
attribute also caused source `left-a` to be reported as `left-b`. This isolated
probe establishes matcher behavior, not persistence or a live API exploit.
The script `output/result-collision-probe-20261028/adapter_probe.py` SHA-256
`8e654091a46e7e93a8f912b315fa63189760148b062ba2efb80b8968bb45ca37`
asserted that the imported adapter file was in the checkout; its log SHA-256
is `1025c80d4e4cc2ee78d6f58896ca2cd2a2d87174584e617e9bf805e14592a1f8`.

The separate restricted-role PostgreSQL test created two registered left
inputs: `left-a` amount 10 with `attributes.id=left-b`, and `left-b` amount 77
with `attributes.id=left-a`; the right input had amount 10. The real worker
completed and persisted a `Matched` result linking `left-b` to the right input
with amount difference zero. That ID exists, but its stored amount is 77; the
record whose amount and reference matched was `left-a`. The fixture used a
synthetic organization-scoped service-account policy, PostgreSQL 16.14, a
non-superuser/non-BYPASSRLS role and FORCE RLS on reconciliation runs. The
fixture used test-only grants on named tables, not a production privilege
profile. The command used the mandatory native gate and reported one test
passed, zero skips; it did not use the HTTP route or prove a deployed exploit.
Its retained log is `output/result-collision-probe-20261028/native-identity-confirm.log`,
SHA-256 `5fb3ec7b9537656e2405b9d217875e84825a4c627c887cb15b12fd822eaf689f`.
The original assertion-only failure, caused by rendering zero as `0E-18`, is
preserved as `native-identity-first-assertion.log`, SHA-256
`27c7970bd722dc5114875d94950ed31ba4b860312988bae0eeb5b53cc47556c9`.
The identity test file SHA at the successful run was
`a49e5354e110a5f5e38ce866d04b7a6aa5c9ee2f94a9b32addad002e762e6eb0`;
it was subsequently extended with the four cases below.

The extended PostgreSQL test independently persisted `Matched` and completed
four runs with the same conflicting amount, currency, date and reference
conditions as the adapter probe. The single test ran all four cases, with no
skip; log `output/result-collision-probe-20261028/native-fields.log` SHA-256
`ec956f9abca85251896455816e97a14e4571b1963d63f69a05e52219a892a2ad`.
The final extended `test_native_identity.py` SHA-256 is
`0c2bdfeeb1c1446a414bbf31e4238dd659c912e8fd3bcffa658ae8d66287981a`.

## Result collision can falsify a later checkpoint

The repository's `append_result` and `append_results_batch` in
[PostgreSQL reconciliation](../../reconforge/infrastructure/postgres_reconciliation.py)
derive result identity from tenant, run, left ID, right ID, match type and
status. Other values, including confidence, explanation, amount difference and
lineage, are excluded. At the tested source, an insert conflict caused the
existing row to be returned without comparing those omitted values. The
partition method hashes requested output and subsequently writes a checkpoint.

On the owned PostgreSQL service, the first synthetic partition persisted a
result with difference `0` and lineage `first`; a second partition submitted
the same result identity with difference `4`, different confidence and lineage
`second`. Both partition calls completed and two checkpoints existed. The
second checkpoint's `output_hash` matched its *requested* different payload,
while the single stored result remained the first payload. This proves the
repository/partition behavior for explicitly supplied synthetic outputs; it
does **not** establish that the production matcher emits this exact collision
or that historical checkpoints are affected. The test used the restricted
application role and mandatory gate: one passed, no skips. Its log
`output/result-collision-probe-20261028/native-result-collision.log` has
SHA-256 `879e24d2736c08de7675de2a0665d1952ad10177e5af04eee04fbae6b1b65966`;
the test file SHA-256 is
`e29cd5b4ee5a3ceb005195092b8a9b4c100b1a1211b933383a693b5c49ead756`.

## Source and verification boundary

The observed Git HEAD was `43d8d051ea14046e78f86c2723f4c5aaec0afa02` with
uncommitted changes elsewhere. Windows Python 3.12.13 used an owned ephemeral
PostgreSQL 16.14 container, image SHA-256
`57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`.
The worker source hash was
`4eeec1a59c044b373bf5fdb5a2ca6592139017b8a0ce43a4b214cea284c18ce0`
before and after the native runs. The repository source hash was
`8ea3c5c02a2210b372fdf9b6dd7d448bb890f4ab9432caaf8c491709f8628398`
before and after the identity test, and
`81d4795db6ac9e3077c05152e9024298c93bae8e0f96c6d93e1e9322e327b6bd`
before and after the later fields and collision tests. Thus each test has
stable named source files, but neither is a clean committed full-tree result.
Raw per-test hashes are retained in `native-hashes-confirm.txt`,
`native-hashes-fields.txt` and `result-collision-hashes.txt` in the output
directory. Individual test wall times were not separately recorded. The
label-verified owned container was removed; no existing container was changed.

Any correction needs a versioned decision about authoritative fields,
compatibility with historical result/checkpoint semantics, input validation,
and controlled handling of disagreements. A collision repair should compare
complete canonical persisted content transactionally, including JSONB and
NUMERIC semantics, reject changed content without partial writes, and test
same-chunk, cross-partition, concurrency, replay and caught exceptions.
Neither candidate is implemented or qualified by these probes.
