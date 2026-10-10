# ADR 0852: Scoped original stock revenue inverse dispatch

Status: Accepted engineering decision; corrective native acceptance pending.

## Trigger and decision

Hosted PR #130 at `6642ab61d9c7546b481ceb3385b4ed2cf26b232a` exposed a least-privilege compatibility failure. The retained stock-sale deferred dispatcher planned an unconditional subquery over `operational_finance_links` during ordinary manual journal and snapshot writes. PostgreSQL required the protected relation privilege even when the reversal reference was null. The resulting transaction refusal also caused downstream API failures. These failed runs remain evidence of the defect; they do not count as acceptance.

Apply an additive revision `0132_pg_stock_inverse_dispatch` after `0131_pg_fx_revaluation`. It changes owner discovery in `stock_sales_native_close` while preserving the published customer-return revision 0126 and its exact source and inverse closure. Only a non-null original effect reference causes a lookup through the native posting effect and its immutable original entry. The entry must retain both an exact lowercase `OPS1-` plan reference and the corresponding uppercase entry number before that reference can select a stock-sale owner. An unrelated manual entry whose free-form reference copies an OPS1 plan therefore remains on the ordinary dispatch path.

The existing owner predicate compares the resolved plan to the stock-sale invoice plan. The existing full financial and inventory checks still decide whether an owned inverse may commit. There is no new grant, security-definer function, replacement ledger, or relaxation of tenant RLS. An owned source that cannot be read with current invoker privileges fails closed.

## Migration and rollback

Upgrade checks that each retained function anchor occurs exactly once and that the corrective route is absent. Downgrade checks the reciprocal anchors and restores the original function definition byte for byte. Either operation refuses an unexpected function body. Function ownership, ACL, security mode, configuration, table privileges and FORCE RLS must remain unchanged. The full ordered Alembic chain is required for rolling back earlier owner revisions; directly invoking an older migration body above dependent owner revisions is not a supported rollback.

The package and migration registry expose all 132 revisions while preserving the accepted 125-revision prefix. Historical acceptance packets and benchmark index entries retain their original bytes and source identities. This revision has no data-rewriting phase; rolling it back reinstates the recorded ordinary-role compatibility defect.

## Verification contract and limits

The complete fixture-only `tests/test_postgres_stock_sales_reversal_dispatch.py` runs in the mandatory finance-integrity shard. Its four cases cover reciprocal function and privilege parity, the ordinary 1,000-line snapshot and full native manual inverse with protected OPS-link SELECT revoked, refusal of an owned original revenue inverse under an arbitrary Generated number, and an unrelated manual inverse whose external reference copies a real OPS1 plan. General Python collection excludes this fixture-only file; the mandatory shard executes the whole file without a selector or added skip.

Existing native posting, dimensional snapshot, customer return, direct SQL, and API cases remain required. The customer-return migration case follows the real ordered downgrade and reupgrade, retains exact function bodies and financial snapshots, and verifies that populated rollback refusal retains the actual head and original command acknowledgement. The synthetic corrupted-customer fixture drains deferred checks before restoring its immutability trigger, preserving the original refusal assertion under additive migrations.

Static and pure contract checks do not establish native correctness, restore acceptance, or a performance improvement. The corrective runtime gate and fresh comparable performance pairs must finish on a frozen corrected source before their results can be claimed.
