# ADR 0500: Preserve contiguous CLI validation errors on narrow terminals

- **Status**: Accepted
- **Date**: 2026-08-10
- **Decision**: Configure the shared Rich CLI error printer with
  `soft_wrap=True` so observable validation phrases are not folded at the
  terminal width.
- **Rationale**: The complete local suite found that a narrow TTY split the
  existing ownership-change error phrase and broke a machine-facing assertion.
  The command was correctly fail-closed; only the presentation contract was
  unstable.
- **Verification**: E-663 focused ownership-change and complete local pytest
  gates pass after the change.
- **Boundary**: CLI presentation/compatibility only. No financial calculation,
  schema, authorization, provider, HA/DR, hosted, or production claim follows.
- **Rollback**: Revert the `soft_wrap=True` argument and remove E-663 evidence;
  retain the existing validation and exit-code behavior.
