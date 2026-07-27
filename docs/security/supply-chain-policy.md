# Supply-chain dependency, secret, and exception policy

The normative machine-readable contract is
`docs/security/supply-chain-policy.v1.json`; active and historical decisions are
in `docs/security/supply-chain-exceptions.v1.json`. Their schemas are closed.
This page explains how maintainers operate those contracts. It is not a claim
that hosted controls ran or that dependencies are safe.

## Resolution boundaries

| Surface | Normative input | Installation boundary | Current limitation |
| --- | --- | --- | --- |
| Python runtime/server/tools | `pyproject.toml` + universal `uv.lock` | `uv sync --locked`; supported Python 3.11/3.12 | Lock applies to the application and repository workflows, not downstream library consumers |
| Web client | `apps/web/package.json` + npm v3 lock | `npm ci` | 155 of 209 non-root records lack embedded SRI and are counted as a known integrity gap |
| Container | digest-pinned Python base + checksum-pinned uv archive + `uv.lock` | non-editable runtime-only sync | Docker is unavailable in the current local environment; no image build result exists |
| Release build tools | `.github/release-build-requirements.txt` | pip `--require-hashes` | Separate from application resolution under ADR 0067 |

The absolute uv cutoff makes an unchanged lock regeneration independent of
future uploads. Move it only in the same reviewed change that intentionally
updates dependencies and records audit/test evidence. Never use `--frozen` in a
gate: `--locked`/`uv lock --check` must detect manifest drift.

## Required gates

Run locally with an official checksum-verified uv 0.11.32 binary:

```bash
uv lock --check
uv sync --locked --all-extras --no-editable --python 3.11
uv export --locked --all-extras --no-emit-project \
  --format requirements.txt --output-file all-extras.txt
uv run --no-sync pip-audit --require-hashes --disable-pip \
  --requirement all-extras.txt
npm --prefix apps/web audit --package-lock-only --audit-level=high
python .github/scripts/validate_supply_chain_policy.py --project-root .
```

CI captures JSON scanner output and gives the scanner exit code to the policy
validator. Exit codes other than the scanner's clean/finding values fail as
operational errors. The validator also rejects disagreement between the report
and exit code.

With the checksum-verified Gitleaks 8.30.1 binary:

```bash
gitleaks git --config .gitleaks.toml --log-opts="--all" \
  --redact=100 --no-banner --no-color --timeout 120 .
gitleaks dir --config .gitleaks.toml \
  --redact=100 --no-banner --no-color --timeout 120 .
```

Do not publish raw secret reports. Output remains redacted. The checked-tree
scan includes source, tests, fixtures, documentation, examples, and lockfiles.
Only generated/tool-owned directories in `.gitleaks.toml` are excluded.

## Dependency update workflow

1. Start from a clean, reviewed revision. Do not combine a lock update with
   unrelated feature changes.
2. Review the upstream release, ownership, source, supported Python/Node
   platforms, transitive diff, license metadata, and known advisories.
3. Move the uv cutoff to the review time and run the exact pinned uv version.
   For npm, use the supported hosted Node/npm platform so cross-platform optional
   packages are retained; do not regenerate the lock casually on one workstation.
4. Inspect the lock diff. Reject new Git/path/plain-HTTP/credential-bearing
   sources. Every non-root uv distribution must retain a SHA-256, positive size,
   and official PyPI/files host.
5. Run both supported Python profiles, npm install/test/build, policy validation,
   audits, security scans, package build, Docker build where available, and the
   full test suite.
6. Update the SBOM/evidence record and disclose any remaining completeness gap.
7. Merge only after normal code review. Dependabot output does not bypass these
   steps.

Weekly automation covers pip, npm, Docker, and GitHub Actions. A newly known
vulnerability or confirmed secret triggers immediate review rather than waiting
for the next weekly window.

## Exception workflow

There are no active exceptions at policy inception. To propose one, add a closed
entry to the exception registry containing:

- exact ecosystem, subject, and advisory/finding identifiers;
- owner, justification, and concrete compensating controls;
- a repository issue with evidence and remediation plan;
- two distinct approvers who are not the owner; and
- creation/expiry dates no more than 30 days apart.

An expired or revoked entry remains history but never exempts a gate. Critical
npm findings cannot be excepted for release. Secret scan findings are not
silenced by this registry: remove a demonstrable false-positive pattern through
a narrowly reviewed code/config change, or rotate/revoke and handle a confirmed
secret. Never add the secret value to an allowlist or log it in an issue.

## Incident and rollback boundary

For a confirmed secret, revoke or rotate it first, identify exposure and use,
preserve redacted evidence, and follow the incident runbook. Git history rewrite
is a separate destructive decision and is not performed automatically.

For a harmful dependency update, revert manifest, lock, and container changes as
one reviewed unit, retain the vulnerable artifact/advisory evidence, and keep
release publication disabled until the previous or repaired lock passes every
gate. Do not run an unlocked install as a silent rollback.

## Claim boundary

A current lock plus clean audits proves only that named scanner versions found no
known findings in the examined inputs at that time. It does not prove absence of
malware, undisclosed vulnerabilities, compromised maintainers, build provenance,
runtime reachability, license suitability, hosted enforcement, compliance, or
production readiness.
