# ADR 0069: Lock application dependencies and fail closed on supply-chain gates

- Status: Accepted
- Date: 2026-07-26
- Backlog: `P0-SEC-008`
- Decision owner: Security maintainers

## Context

ReconForge declared broad lower bounds in `pyproject.toml`, installed those
bounds directly in normal CI and the container, and ran `pip-audit` against the
ambient installed environment. That did not identify one reproducible runtime
or server dependency set. The web client had an npm v3 lock, but no release
gate checked it. Dependabot covered only Python and GitHub Actions. No repository
gate scanned both Git history and the checked-out tree for secrets, and no
machine-readable exception contract bounded owner, approvals, scope, or expiry.

Release-candidate build tools are separately hash-locked under ADR 0067. The
developer extra also includes the declared setuptools/wheel backend so a local
`build --no-isolation` is reproducible from the universal lock. These controls
remain distinct: candidate tool bootstrap identity and deployed dependency
identity answer different questions even where package names overlap.

## Decision

1. Keep broad dependency metadata in `pyproject.toml` for Python package
   compatibility, but commit universal `uv.lock` format v1/revision 3 as the
   application, server, build/developer, documentation, and DuckDB resolution.
2. Require uv 0.11.32 exactly and an absolute `exclude-newer` cutoff of
   `2026-07-26T00:00:00Z`. A reviewed dependency update moves the cutoff and
   regenerates the lock; normal install, CI, and release paths use `--locked`.
3. Pin uv's official Linux and Windows release archives by SHA-256. CI uses the
   full-commit-pinned official setup action plus the exact version. Docker uses
   the official Linux archive through checksum-verified remote `ADD` and installs
   production dependencies from `uv.lock` without developer extras or editable
   package state.
4. Preserve `package-lock.json` as the JavaScript exact-version resolution and
   use `npm ci`. Its current 209 non-root entries include 155 without embedded
   `resolved`/SRI pairs. This bounded integrity gap is machine-counted and must
   not be described as a complete artifact-hash lock.
5. Export every Python extra from `uv.lock` with hashes and run locked
   `pip-audit` under supported Python 3.11 and 3.12. Fail on every known advisory
   unless the exact package and advisory identifier has an active exception.
6. Run npm audit against the lock. Fail on high and critical findings. A critical
   npm finding cannot be excepted for release.
7. Pin Gitleaks 8.30.1 by its official release-archive SHA-256 and scan both all
   Git history and the checked-out tree with 100% redaction. Do not use a finding
   baseline, commit allowlist, disabled default rule, regex, or stopword
   allowlist. Only generated/tool-owned directory paths are excluded.
8. Keep supply-chain policy and exceptions in closed schema-v1 JSON. An active
   exception lasts at most 30 days, identifies the exact finding, links a
   repository issue, names an owner and compensating controls, has at least two
   distinct approvers, and cannot be self-approved. Expired and revoked entries
   never exempt a gate.
9. Run policy, lock, Python audit, npm audit, and both secret scans in the signed
   candidate workflow before registry authentication. Scanner operational errors
   fail closed. The normal security workflow repeats the dependency audits on
   both supported Python versions and the repository scans weekly and on change.
10. Add weekly Dependabot coverage for pip, npm, Docker, and GitHub Actions. Bot
    output remains a proposal: lock regeneration, tests, audit, and review are
    still required before merge.

## Consequences

- Normal CI, server CI, Docker, and release candidates resolve a named, hashed
  Python dependency graph instead of the latest graph available at run time.
- Application resolution is reviewable without narrowing public library
  metadata or breaking downstream installers that do not use uv.
- The locked all-extra profile can build the package without downloading an
  undeclared backend; release candidates retain their separate ADR 0067
  hash-locked bootstrap and verification boundary.
- Dependency scanners still depend on current advisory services. A clean result
  is time-bounded and does not prove safety, provenance, reachability, or license
  suitability.
- The npm version tree is deterministic, but incomplete embedded SRI remains a
  disclosed gap. A future reviewed regeneration on the supported hosted Node/npm
  platform must close it without silently changing cross-platform optional
  packages.
- Secret scanning is detection, not proof that secrets never existed or were
  rotated. A confirmed secret requires revocation/rotation and incident handling;
  deleting the string is insufficient.
- No hosted workflow, Docker build, branch-protection rule, release gate, or
  exception approval process is claimed to have operated from local evidence.

## Rollback

Revert this ADR's Docker, CI, release, policy, exception, lock, and scanner
changes together. Do not delete exception or audit evidence. Restore the previous
install path only as a temporary compatibility rollback, record that resolution
is again non-reproducible, and keep release publication disabled until a reviewed
replacement lock and gates pass.

## Verification

- `uv lock --check`
- `uv sync --locked --all-extras --no-editable --python 3.11`
- hash-exported `pip-audit` with policy enforcement
- npm lock audit with policy enforcement
- Gitleaks full-history and checked-tree scans
- `python .github/scripts/validate_supply_chain_policy.py --project-root .`
- schema, negative-policy, exception, audit, workflow-order, and pinning tests
- actionlint, Ruff, Mypy, focused tests, and the full suite

## Primary sources reviewed

- <https://docs.astral.sh/uv/concepts/projects/sync/>
- <https://docs.astral.sh/uv/reference/settings/>
- <https://github.com/astral-sh/uv/releases/tag/0.11.32>
- <https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1>
- <https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md>
- <https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/>
- <https://github.com/pypa/pip-audit>
- <https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file>
- <https://docs.docker.com/reference/dockerfile/#add---checksum>
