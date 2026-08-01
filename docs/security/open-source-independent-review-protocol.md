# Open-Source Independent Security Review Protocol

Status: optional assurance protocol; deferred by owner decision E-251

Protocol version: 1

Date checked: 2026-08-01

## Boundary

Open-source scanners and reproducible public-data runs provide useful technical
evidence, but they do not constitute an independent security review. If optional
`P3-EXT-002` assurance is resumed, it requires a qualified independent human reviewer, an explicit scope,
a dated report, reproducible findings, remediation/retest state, and residual
risk acceptance by an authorized human.

Private vulnerability reporting is currently disabled for
`amrzainmubarak/reconforge-erp`; this was read through GitHub's repository API on
2026-08-01 and no setting was changed. The repository owner must enable it before
any optional public review solicitation. Until a private channel is verified end to end,
vulnerability details must not be filed in a public issue, pull request,
discussion, operator attestation, or public-data artifact.

GitHub's private-reporting documentation is:
<https://docs.github.com/en/code-security/concepts/vulnerability-reporting-and-management/repository-security-advisories>.

## Automated open-source evidence supplied to the reviewer

The exact reviewed commit should include and pass:

- GitHub CodeQL for Python.
- OpenSSF Scorecard as a repository-practice signal, not a product-security score.
- Ruff, mypy, pytest, Bandit, hash-locked `pip-audit`, npm audit, and Gitleaks.
- Build, SBOM, provenance, signature, migration/restore, authorization/SoD,
  tenant-isolation, file-ingress abuse, connector-network, upgrade/rollback, and
  deterministic-replay tests already named in the execution evidence index.
- The public financial evidence workflow as a real-data integrity and safe-egress
  exercise, not a penetration test.

The reviewer must receive raw logs through the private review workspace. Public
summaries may include only safe counts, tool versions, commit digests, and closed
finding identifiers after coordinated disclosure.

## Minimum independent reviewer criteria

- Demonstrated application-security/code-review capability relevant to Python,
  FastAPI, PostgreSQL, browser/API authorization, cryptographic package trust,
  and CI supply chain, with limitations declared.
- No authorship or approval responsibility for the code under review.
- A signed conflict-of-interest and confidentiality statement.
- Independence from the maintainer who accepts residual risk; one person cannot
  act as implementer, independent reviewer, and risk accepter.
- Agreement to use synthetic or already-public data only and to avoid destructive
  testing against uncontrolled infrastructure.

No claim of certification, compliance, penetration-test accreditation, or
universal security follows from satisfying these criteria.

## Required review scope

1. Threat-model and trust-boundary review: local/community, server/PostgreSQL,
   tenant/workspace, identity federation, connectors, jobs, evidence, upgrades,
   air-gap bundle, observability, and release provenance.
2. Targeted code review: strict file and structured-data ingress, path/archive
   handling, authentication/session/WebAuthn, centralized authorization and SoD,
   PostgreSQL RLS/transactions, network allowlists/redirects/proxies, secret/log
   redaction, signature verification, and rollback/isolation behavior.
3. Targeted adversarial tests using synthetic/public inputs: schema confusion,
   parser abuse, traversal, decompression limits, SSRF/redirect/proxy behavior,
   cross-tenant access, self-approval, replay/idempotency, evidence tampering,
   dependency or pack tampering, and failure recovery.
4. Supply-chain review: pinned Actions/tools, locked dependencies, exceptions,
   SBOM completeness, exact-subject attestations, release permissions, and
   secret scanning.
5. Claim review: distinguish implemented controls from hosted enforcement,
   operator configuration, external assurance, compliance, and certification.

Exclusions must be explicit. Any untested production cloud, identity provider,
HSM/KMS, multi-host HA, physical air gap, WORM store, or customer integration
remains unverified.

## Finding lifecycle and fail-closed exit

Each finding received through any channel must include a stable ID, severity rationale, affected exact commit
and artifact, safe reproduction, impact, remediation owner, target state, and
disclosure classification. Critical/high unresolved findings keep publication
blocked unless an authorized human documents time-bounded risk acceptance with
compensating controls; acceptance is not remediation. This known-finding rule
remains a release control even though obtaining an independent review is optional.

Retest must reference the fixing commit, repeat the original reproduction, state
the result, and identify regression tests. The final report must use
`docs/execution/P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md` and be signed
or linked to a verifiable formal statement. An upstream maintainer verifies the
artifact and a separate authorized human accepts residual risk. Only then may
optional `P3-EXT-002` move to `verified`. Its deferred state does not block an
owner/team release and must not be represented as independent assurance.

## Next action if optional assurance is resumed

1. Repository owner enables GitHub private vulnerability reporting.
2. Maintainer performs a harmless private test report and closes it, proving the
   channel works without public disclosure.
3. A qualified independent reviewer accepts the scope and conflict statement.
4. The reviewer works from an exact commit and returns the dated report privately.
5. Findings are remediated/retested or explicitly accepted before claiming the
   optional independent assurance item.
