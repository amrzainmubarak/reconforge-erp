# ADR 0533: Unify the fail-closed locked Python dependency audit

- **Date**: 2026-08-22
- **Status**: Accepted
- **Scope**: supply-chain audit reproducibility and `PYSEC-2026-3721`

## Context

The universal lock resolved `pip 26.1.2`, which the current pip-audit advisory
service identified as affected by `PYSEC-2026-3721` with `26.2` as the first
available fixed version inside the existing absolute upload cutoff. The hosted
security and release workflows audited a hash-bearing all-extras export, while
the Makefile invoked ambient `pip-audit` without binding the result to
`uv.lock`. A foreign or damaged project `.venv` could also prevent a local
`uv run --no-sync` audit even when the repository lock remained valid.

## Decision

Refresh only `pip` in `uv.lock` from `26.1.2` to `26.2`, retaining the existing
uv version and absolute upload cutoff. Add one cross-platform locked-audit
runner that:

- requires the exact policy-pinned uv version and a supported Python 3.11/3.12
  matrix cell;
- validates the closed supply-chain policy and current universal lock;
- exports all optional profiles with distribution hashes and excludes the
  unpublished project itself;
- runs the lock-resolved pip-audit with `--require-hashes` and `--disable-pip`;
- uses a temporary environment and cache locally, without trusting or repairing
  the project `.venv`;
- reuses the already-synchronized locked environment in CI/release; and
- passes the JSON report and exact scanner exit code to the existing exception
  validator so findings, malformed reports, disagreement, and operational
  scanner failures all fail closed.

CI, release, the Makefile, contribution guidance, and the normative security
runbook use this runner. Static policy validation rejects removal of its core
hash, export, isolation, and fail-closed arguments.

## Security and privacy

The runner makes advisory-service network requests only when the operator
explicitly runs the security audit. It emits package/advisory metadata but no
financial rows, tenant data, credentials, or project source. Temporary
requirements, cache, and JSON report files are deleted when the process exits.
This remediation establishes only a clean time-bounded scanner result; it does
not prove package provenance, malware absence, reachability, license
suitability, compliance, or production security.

## Compatibility

No application API, CLI, schema, migration, financial calculation, or runtime
dependency behavior changes. `pip` is a dev/audit transitive through
pip-audit's tooling graph, not a ReconForge runtime import. The local command
now requires the repository's already documented checksum-verified uv binary
and downloads/constructs a temporary locked tool environment when needed.

## Rollback

Revert the runner, workflow, Makefile, tests, documentation, and lock update as
one reviewed unit only if a replacement lock also passes the current advisory
gate. Never restore the known-affected lock or substitute an ambient/unlocked
audit as rollback. No persisted product data requires migration or recovery.

## Evidence boundary

Local Python 3.11 and 3.12 execution on 2026-08-22 reports zero known findings
for the 128-package all-extras export with pip-audit 2.10.1 and no active
exception. Fresh hosted Python 3.11/3.12 workflow results remain required before
this revision can be treated as hosted enforcement evidence. Publication
remains frozen by D-485.
