# ADR 0799: Validate evidence references independently of host path syntax

Date: 2026-10-03

Status: Accepted

## Context

Draft PR 109's Linux/Python 3.12 run rejected an invalid Windows evidence path
with a later digest-coverage error instead of enforcing the relative-path
contract. `Path.is_absolute()` interprets only the running host's path syntax.
Additional regression cases reproduced six failures on Windows for POSIX-rooted,
Windows-rooted and drive-relative references.

## Decision

Before resolving either a gate reference or digest-manifest reference, reject
any anchor parsed by either `PurePosixPath` or `PureWindowsPath`. This includes
absolute paths, drive-relative paths, UNC paths and extended Windows paths.
Retain the existing resolved-root containment and digest verification checks.
Valid repository-relative references and their digest semantics stay unchanged.

## Verification and rollback

The focused readiness suite passes 35 tests on Windows. A direct reader probe
passes all 16 new rejection cases and a valid matrix under Linux/Python 3.12.14
with the checkout mounted read-only. The Linux probe is not a full pytest run;
the cached image lacks pytest. Ruff, Mypy, Bandit and diff checks pass. Full
remote CI remains a separate acceptance gate. Revert the two source/test changes
to roll back; there is no database or evidence migration.
