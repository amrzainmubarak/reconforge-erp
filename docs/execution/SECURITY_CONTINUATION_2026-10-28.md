# Locked dependency and quality continuation — 2026-10-28

Entry source `dfc9ad97649b4d458de5d56d8cd514da03168e54`. On PR 144,
locked Python audit jobs for 3.11 and 3.12 failed with the unexcepted
`CVE-2026-114613` on msgpack; the aggregate Python security job consequently
failed. The [upstream advisory](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-j586-36cw-2gc2)
identifies versions before 1.2.3 as affected and 1.2.3 as fixed. This is not
evidence that an untrusted product input reaches the affected code.

The lock-only upgrade changes msgpack 1.2.1 to 1.2.3. An independent comparison
of parsed before/after TOML found no changes to other package records. The
observed dependency path is the `dev` extra via `pip-audit[filecache]` and
`cachecontrol`; a local default-dependency export did not contain msgpack.
This does not establish the contents of every release artifact.

On Windows, a new task-owned Python 3.12.13 environment was synchronized from
the updated lock without replacing an existing environment. `uv lock --check`
passed; the environment imports msgpack 1.2.3. The full locked audit script
reported no known vulnerabilities and no active exceptions (67.73 s). The
existing locked-audit and supply-chain policy/claims suites gave 92 passes
in 9.98 s. The audit log SHA-256 is
`83fcd282ebf722ced0e4047305e68f0f99a2f67c75b394a6f712c56623028759`;
the local environment and log are retained at
`output/erp-vision-20261028/locked-312-env` and `locked-audit-312.log`.
The historical hosted failures remain failures; 3.11 and hosted checks of
the successor are separate gates.

An independent synthetic quality probe on PostgreSQL 16 with a restricted
non-superuser, non-BYPASSRLS role and ENABLE/FORCE RLS reproduced the existing
workspace-scoped NCR entity gap at the entry source: creation under A returned
200, B using scope A was denied 403, and B using scope B disposed the same NCR
with 200. The response says `inventory_effect=not_posted`. Evidence is retained
at `output/quality-entity-probe-d80a5b6f0e3c/result.json` (17.543 s); it does
not establish historical ownership or inventory/GL effects. No entity
attribution migration is implied by this result.

A second restricted-role PostgreSQL 16.14 probe at the same source observed
entity B reading and changing an inspection plan created under A, and creating
rework linked to the NCR; the API reports the financial effect as not posted.
Its retained result is `output/quality-entity-probe-d365b01e1b54/result.json`
(15.343 s). These behaviors expose the boundary of the present workspace
contract; they do not assign historical records to an inferred owner.

An attempted grouped-worker cancellation patch was rejected during independent
review. Its extra cancellation check acquired a second connection while its
supplier held one; a pool of one reproduced acquisition timeout. The draft and
test are retained under `output/erp-vision-20261028/` and are not applied. A
safe fix needs pool saturation and real PostgreSQL testing; FX and replay
remain open.
