# ADR 0534: Use platform-specific, non-destructive developer environments

- **Date**: 2026-08-22
- **Status**: Accepted
- **Scope**: contributor bootstrap and local environment diagnosis

## Context

The ignored project `.venv` can be created by a different operating system or
tool session. On this Windows checkout it contained Linux metadata and no
Windows interpreter; normal `uv run --no-sync` attempted to use or repair that
foreign directory and could not proceed. Deleting, replacing, or silently
repairing an existing developer environment risks removing user-owned state and
makes evidence depend on workstation history.

## Decision

Add a repository developer-environment manager with two explicit operations:

- `doctor` verifies the exact policy-pinned uv version, supported Python matrix,
  current `uv.lock`, the selected platform interpreter, and a stable set of
  machine-readable findings without modifying either environment;
- `bootstrap` creates or re-synchronizes only a direct project child named
  `.venv-*`, using `UV_PROJECT_ENVIRONMENT`, `--locked`, all extras,
  non-editable installation, and an explicit supported Python version, then
  runs the product Doctor from that environment.

The default target is `.venv-windows`, `.venv-macos`, or `.venv-linux` according
to the host. An existing failed/malformed target, symbolic-link/reparse target,
path outside the project, nested path, or unsupported Python version is
refused. The traditional `.venv` is reported as legacy state and is never
deleted, moved, or repaired by the tool. Platform-specific targets are ignored
by Git.

## Security and privacy

All subprocess calls use closed argument arrays without a shell. Environment
paths are restricted to direct `.venv-*` children of the resolved repository.
The report exposes only relative environment names, versions, stable finding
codes, and generic details; it does not emit credentials, package indexes,
financial data, or source records. Bootstrap may access configured package
indexes through uv, exactly as the documented locked dependency setup does.

## Compatibility

This adds developer tooling and Makefile targets only. Existing `.venv`, CLI,
API, schemas, migrations, runtime configuration, and product data remain
unchanged. Contributors may continue using another valid environment, but it
does not count as the repository's reproducible bootstrap evidence.

## Rollback

Remove the manager, tests, Makefile targets, `.gitignore` pattern, contributor
instructions, and this ADR. Platform-specific environments are ignored local
developer artifacts and are not automatically deleted during rollback. No
product migration or data recovery is required.

## Evidence boundary

On 2026-08-22 the Doctor identified the preserved Linux-origin `.venv` on
Windows as `DEVENV-ENV-FOREIGN`, created no change there, bootstrapped a locked
Python 3.12 `.venv-windows`, ran ReconForge Doctor successfully, and then
reported `DEVENV-READY`. Repeating bootstrap also succeeded. This is one local
Windows host; hosted, macOS, Linux, proxy/private-index, air-gap, and clean-host
bootstrap evidence remain separate.
