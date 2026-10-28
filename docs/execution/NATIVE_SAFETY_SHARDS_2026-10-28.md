# Native safety shard qualification — 2026-10-28

Two independent `server-boundaries` matrix shards now select the complete
worker-amount and quality-direct test files with `tests.mandatory_native_gate`.
That gate rejects skips, xfails, xpasses and missing collection. The general
Python job excludes those files because it has no PostgreSQL service. Each new
shard owns a fresh migrated service; its fixture grants cover named tables and
omit DELETE and `ALL TABLES`. The 37 previous shards keep their commands and
do not receive these grants. This does not establish a least-privilege operator
configuration.

Local Windows/Python 3.12.13 experiments used two separate synthetic PostgreSQL
16.15 services on the image digest configured by CI. The SQL grants were read
from the workflow and the pytest command used the mandatory gate without a
diagnostic plugin. Worker: 5 passed / 0 skips, 19.586 s including setup.
Quality: 3 passed / 0 skips, 34.224 s including setup, one Starlette warning.
Receipts and raw logs are under `output/ci-native-frozen2-20261028/`. The
receipts record entry HEAD `0611dc16` with uncommitted worker/test/workflow
changes and equal before/after hashes for nine selected files; they are not a
whole-tree or hosted CI qualification. The local run did not supply extra
Redis, container and PGSERVICEFILE variables unused by these two cases.

The worker tests validate the stated policy scenarios, not derivation of a
known amount from inputs or safety of caller-supplied exposure. The quality
tests do not establish entity isolation or caller identity binding. Retain
earlier fixture failures and plugin-assisted diagnostics as distinct evidence.
Hosted successor CI, operating grants, migration/restore and full release
gates remain open.
