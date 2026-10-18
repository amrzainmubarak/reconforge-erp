# Repeatable current PostgreSQL close installation

Status: accepted on immutable cd67fc67; hosted rerun pending.
Date: 2026-10-03
Scope: current close installer and synthetic matching cleanup.

Hosted PR112/113 failed because PostgreSQL truncates explicit constraint names
to its identifier limit. Comparing those catalog `name` values with the full
text missed existing foreign keys and the ownership-link hierarchy constraint.
The historical revision0078 SQL is loaded from the runtime module, so rewriting
its existing constant would silently change migration history.

Preserve the historical SQL byte-for-byte. Expose a separate current constant
that casts exactly the two generated FK names and the oversized explicit
hierarchy name to PostgreSQL `name` when checking the catalog. The existing
current installer uses this constant. Current API fixtures use the installer;
historical Alembic0078 still loads the unchanged legacy constant.

Synthetic matching teardown suspends the0097 child guards only when present,
inside the existing administrative transaction that deletes explicitly owned
test tenants. It restores those guards and verifies their enabled state before
completion. No product guard is changed or disabled outside test cleanup.

The fixed-head live/compatibility gate passes96 tests with zero skips; fresh
full migration, repeated installation, unchanged catalog constraints/policies,
forced RLS, sibling/unscoped write/read denials, unknown-parent FK rejection,
existing close lifecycle and sealed reconciliation writes are covered. Global
Ruff/Mypy/Bandit pass. The failing original two-case reproduction, environment
URL error and intermediate fixture assertions remain separate retained evidence.

This repair preserves existing schema behavior. The additional attempted
same-name close periods in two entities exposed a retained legacy global unique
constraint whose automatically generated name differs from explicit identifier
truncation. It remains a separate versioned schema repair; this patch does not
drop it or claim complete hierarchy-key parity.

Rollback: redeploy a compatible reader and preserve schema/data. No new
migration or data deletion is introduced. Reverting the current installer
restores the reproduced repeated-installation failure. Do not disable guards
as an operational workaround.
