# Primary workspace consolidation — 2026-10-18

The explicit user request is complete: ongoing work is in `F:\reconforge-erp`;
no secondary Git worktrees remain. `AGENTS.md` and ADR0863 require future work
to use this directory, with branches when needed.

## Sources and preservation

- Former primary branch: `amr/global-erp-wave2-20261010`, source
  `6995141426fea1670b64313ae1a5b2f1d6064f8f`.
- Consolidated source: `bfc138a13c05513dc5c6e7bf23c81f013a0df123` from
  `amr/m7-monetary-integration-20261015`, a descendant 750 commits ahead.
- Current local branch: `amr/single-workspace-20261018`.
- `git fetch origin --prune` completed before comparison. No change to the
  remote repository or remote `main` was needed for this local operation.
- Native, product and quality leaf branches have only patch-equivalent commits
  beyond the integrated source; `git cherry -v` reports no missing `+` patches.
- All 51 previously registered heads, including detached heads, have archive
  refs under `refs/archive/single-workspace-20261018T013547Z/` and are present
  in the verified recovery bundle. Existing branch refs remain available.

Recovery directory:
`F:\reconforge-erp\output\worktree-consolidation-20261018T013547Z`

Its `manifest.json` records source heads, paths, artifact hashes and SQL hashes.
`repository.bundle` is 82,300,898 bytes and passes `git bundle verify`.
`primary-working-tree.patch`, `primary-index.patch` and `primary-original-files/`
retain the old primary changes. Stash `de2c0f7e441cdd34a7ddef40295081887c9649ac`
is retained both in the live repository and the bundle.

The two primary local edits reorganized static SQL fragments without changing
`REVERSE_CLOSE_SQL`, `UPGRADE_SQL` or `DOWNGRADE_SQL` bytes; all three were
compared independently for each file before switching source. The latest code
already splits those fragments and includes subsequent financial corrections.
The old patch is retained for recovery rather than reapplied over newer code.

Each removed worktree has a ZIP of its non-cache ignored artifacts, including
the native/quality XML evidence and generated product distribution files.
Every archived file was verified against its recorded SHA256 before and after
removal. Dependency directories and Python/tool caches were regenerable and
excluded. `npm ci` regenerated the primary web dependencies from its lockfile.

## Removal verification

Removed through `git worktree remove` without force:

- `F:\ReconForge_Worktrees\m7-integration-20261016`
- `F:\ReconForge_Worktrees\m7-native-20261016`
- `F:\ReconForge_Worktrees\m7-product-20261016`
- `F:\ReconForge_Worktrees\m7-quality-20261016`

`git worktree prune --expire now` removed 46 stale registrations. The empty
`F:\ReconForge_Worktrees` parent was removed after checking its resolved path
and that it contained no entries. Final Git inventory contains only the primary
checkout. `F:\ReconForge_Evidence` remains the existing evidence location.

## Verification and limits

Environment: Windows, Python 3.12.13 from the primary `.venv-amr-sprint`.
Raw command output and JSON duration records are inside the recovery directory.

| Command | Result | Wall seconds |
| --- | --- | ---: |
| `python -m ruff check .` | Pass | 0.312 |
| `python -m mypy reconforge` | Pass; 828 source files | 1.592 |
| Selected pytest command in `targeted-pytest-result.json` | 176 passed, zero skips | 16.227 |
| `npm --prefix apps/web ci` | Pass | 22.222 |
| `npm --prefix apps/web run typecheck` | Pass | 2.040 |
| `npm --prefix apps/web run test:run` | 1106 passed across 103 files | 90.150 |
| `npm --prefix apps/web run build` | Pass | 9.956 |
| `git diff --check` | Pass | 0.047 |
| Full `python -m pytest` | Stopped at approximately 17%; incomplete | 439.729 |

The selected tests cover execution-document contracts, asset/landed-cost
invariants, retained receivables policy and monetary valuation/admission/native
function contracts. This maintenance operation changes no application or test
source relative to the integrated source. Full pytest was stopped to bound the
workspace maintenance task; the incomplete run is not accepted as a full-suite
result. Native PostgreSQL, HTTPS/E2E, container and complete release acceptance
were not rerun here. The existing M7 blockers remain recorded in `STATE.md`.

## Recovery

Verify the bundle with `git bundle verify` and the absolute bundle path above.
Inspect `manifest.json` and `branches-before.txt` before selecting a recovery
ref. `git bundle list-heads` lists available refs; `git fetch <bundle-path>
<recorded-ref>:refs/heads/<recovery-branch>` imports a selected ref into an
existing repository. Original primary edits can be inspected with `git stash
show -p de2c0f7e441cdd34a7ddef40295081887c9649ac`; recover them against the
recorded former primary source. Extract a worktree's artifact ZIP into a chosen
evidence directory and compare its files with the manifest hashes. Keep this
recovery directory until the user explicitly decides it is no longer needed.
