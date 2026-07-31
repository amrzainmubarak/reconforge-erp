# ReconForge Security Architecture v2

Status: evidence-bounded baseline, reviewed 2026-07-26.

The normative registry is
[`security-architecture.v2.yaml`](security-architecture.v2.yaml), validated by
[`security_architecture.schema.json`](../schemas/security_architecture.schema.json)
and `tests/test_security_architecture.py`. This readable view explains that
contract. It is not a compliance certification, security guarantee,
penetration-test result, audit opinion, or production-readiness claim.

## Product and deployment boundary

ReconForge remains a local/file-first financial reconciliation and controls
platform beside source systems. Core Community workflows do not require a
vendor cloud, telemetry, or automatic upload. Optional PostgreSQL, Redis, and
S3-compatible boundaries activate only through explicit operator configuration.
Their existence does not make the complete product hosted, multi-tenant, or
enterprise-ready.

| Mode | Evidence status | Security boundary |
| --- | --- | --- |
| Community Local | Implemented, bounded | Trusted local operator/host; SQLite and local files; local OS/filesystem access remains an operator dependency |
| Team / Server | Experimental, bounded | Bounded PostgreSQL identity/domain repositories plus optional Redis/S3 adapters; no end-to-end proof covers every domain, worker, cache, object, export, and restore path |
| Regulated | Planned only | No supported air-gap package, customer-key enforcement, WORM integration, privileged-access workflow, HA/DR package, or independent validation |

## Data classification

Generated output is not public merely because it was generated locally or
redacted. The workspace data owner authorizes classification, retention, and
disclosure.

| ID | Class | Sensitivity | Required treatment |
| --- | --- | --- | --- |
| DC-001 | Public synthetic | Public | Classification must be explicit; only published docs, public schemas, and explicitly marked synthetic fixtures qualify by default |
| DC-002 | Internal configuration | Internal | Validate schemas/paths and keep credentials out of committed configuration |
| DC-003 | Financial sensitive | Confidential | Restrict local/tenant storage and disclosure; do not log raw financial rows by default |
| DC-004 | Identity restricted | Restricted | Never export raw passwords/tokens; protect backups containing verifier material |
| DC-005 | Security/audit sensitive | Restricted | Restrict access and preserve integrity/lineage metadata; hashes are not signatures |
| DC-006 | Secret | Secret | Supply through deployment secret mechanisms; never commit or place in fixtures, docs, or logs |

## Trust boundaries

| ID | Boundary | Principal threats | Current control IDs |
| --- | --- | --- | --- |
| TB-001 | Untrusted file ingress → readers/validation | Malformed values, traversal, unsafe YAML, formula/parser abuse, silent numeric coercion | SEC-C-001, SEC-C-002 |
| TB-002 | Browser/API caller → application/domain authorization | Authentication bypass, actor spoofing, self-approval, injection, tenant escape, token disclosure | SEC-C-003, SEC-C-004 |
| TB-003 | Local process → SQLite/files/reports/backups | Host access, partial commit, backup disclosure, overwrite, artifact tampering | SEC-C-001, SEC-C-005, SEC-C-006, SEC-C-007, SEC-C-008 |
| TB-004 | Server application → PostgreSQL tenant repositories | Missing RLS/principal context, tenant escape, unsafe query, incomplete migration | SEC-C-003, SEC-C-004, SEC-C-005 |
| TB-005 | Server adapters/workers → Redis/S3/publisher boundary | Credential leak, wrong tenant key, transport error, endpoint abuse, duplicate/lost delivery | SEC-C-004, SEC-C-005, SEC-C-009, SEC-C-010 |
| TB-006 | Generated artifact → external recipient/storage | Unauthorized disclosure, incomplete redaction, reversible anonymization, path leak, checksum overclaim | SEC-C-006, SEC-C-007, SEC-C-008, SEC-C-009 |
| TB-007 | Contributor/dependencies/CI → release artifacts | Dependency drift, secret inclusion, dirty build, unreviewed workflow, unsigned output | SEC-C-008, SEC-C-010 |

Every boundary in the normative registry lists concrete code and test paths.
The contract test fails if a referenced path disappears or a boundary loses
either implementation or test evidence.

## Control ownership and status

Owners are accountable repository roles, not claims about staffed operational
teams. Deployment operators and workspace data owners retain responsibility for
host access, secrets, retention, classification, and disclosure.

| Control | Status | Owner | Bounded outcome |
| --- | --- | --- | --- |
| SEC-C-001 Path/output safety | Implemented, bounded | platform-security | Reject supported traversal/overlap patterns; OS permissions and legacy callers remain outside the guarantee |
| SEC-C-002 Exact/safe ingress | Implemented, bounded | financial-integrity | Preserve current financial lexemes and explicit display compatibility; bound selected JSON/YAML—including FI-009 DB files, FI-011 close, FI-014/FI-015/FI-016, AP/AR, PostgreSQL reconciliation, SQLite matching/public export, and Redis session FI-013 state, two FI-012 manifests, and FI-012 JSON redaction—plus CSV/XLS/XLSX, FI-005/FI-006/FI-007 generated artifacts, and resource-bounded staged FI-012 text/non-redacted copies; exact AST allowlists close current direct tabular/JSON/YAML calls; legacy XLS internals, export crash atomicity, and real host/filesystem loss remain separate/incomplete |
| SEC-C-007 DB import/backup/restore integrity | Implemented, bounded | workspace-data-owner | Bound duplicate-safe legacy DB import and backup/manifest JSON before mutation/allocation, reject ambiguous import envelopes, retain parsed-byte import provenance, verify restore checksum/bytes/schema and known tables, and avoid target replacement by default; record semantics, encryption, authenticated provenance, centralized authorization, malware scanning, real host-loss recovery, cross-edition restore, and DR exercises remain |
| SEC-C-003 Authentication/principal/RBAC | Partial | identity-security | Named-permission and supplied-scope denial, an exact no-self-approval inventory, PostgreSQL sessions, bounded OIDC/SAML assertion verification, authenticated role-free SCIM, typed role-free HTTP service principals, central machine human-action denial, session-bound password step-up, maker-checker emergency review, optional user-verified WebAuthn enforcement, human/MFA-governed optimistic PostgreSQL user/session/role/policy lifecycle, and optimistic runtime disable of four native integration kinds are tested; universal route/repository ABAC, amount/region/data-class policy, integration creation/enable/secret rotation, recovery/attestation governance, workload federation, hosted provider/authenticator interoperability, independent assurance, and deployed effectiveness remain open |
| SEC-C-004 Tenant/dependency isolation | Partial | platform-security | Validated tenant paths/transactions/keys on implemented adapters; no complete hosted isolation proof |
| SEC-C-005 Atomic audit/outbox | Partial | domain-integrity | Business/audit/outbox atomicity on migrated mutations; legacy and external publisher gaps remain |
| SEC-C-006 Evidence/report integrity | Partial | evidence-security | Versioned policy and SHA-256 consistency metadata; no signature, authenticity, completeness, or approval |
| SEC-C-008 Secret exclusion/claim boundary | Implemented, bounded | release-security | Sanitized exports, bounded local redacted history/tree scans, and maturity-claim gates; no hosted/arbitrary-upload/rotation guarantee |
| SEC-C-009 Object storage/sharing | Partial | evidence-security | Explicit tenant keys, TLS defaults, checksums, a monotonic versioned PostgreSQL evidence-retention metadata floor with append-only assignments, and bounded staged client-pack copies; no verified floor propagation to object stores/backups/replicas/exports, legal-hold authority, crash recovery, redaction completeness, malware/KMS, or authorized-delivery pipeline |
| SEC-C-010 Pinned CI/build gates | Partial | release-security | Digest-pinned actions, universal Python/server resolution, and configured dependency/secret/exception gates; hosted execution, npm SRI completeness, reproducible images, signing/provenance, and parity remain open |

## Residual risk linkage

The normative registry maps controls to the existing governed risk records, not
to a duplicate risk rating. Its test enforces owner and residual-rating parity
with `docs/risk-register.yaml`.

High residual risks remain for hosted tenant escape (R-001), incomplete atomic
audit coverage (R-003), financial compatibility readers (R-004), unbound local
actors (R-011), inactive complete multi-worker coordination (R-013), incomplete
central evidence handling (R-014), incomplete PostgreSQL coverage (R-015), and
re-identification/reversibility (R-017), incomplete hostile-file coverage
(R-018), and network-connector trust/egress/replay (R-019). Enterprise identity (R-007) and hosted
outbox delivery (R-008) remain medium residual risks. Controls reduce exposure;
they do not close these records.

## Verification and change rules

1. A control may be `implemented-bounded` only with existing code and test
   evidence plus an explicit limitation.
2. References between editions, classes, boundaries, controls, owners, and
   residual risks must remain closed under the schema and contract test.
3. A new network, storage, identity, sharing, or release path requires a trust-
   boundary update in the same slice.
4. A changed risk owner/rating must update the governed risk register first;
   architecture mapping follows and cannot silently override it.
5. Regulated mode remains planned until air-gap, key, WORM, privileged access,
   HA/DR, release, and independent validation gates exist.
6. Do not derive `secure`, `compliant`, `certified`, `bank-grade`,
   `enterprise-ready`, or public-internet-ready wording from this document.

Related governed registries: the active-module threat-model index is documented
in `docs/security/threat-model.md`; the scoped official OWASP ASVS 5.0.0 mapping
is documented in `docs/security/asvs-mapping.md`; and the final-source NIST SSDF
1.1 all-task mapping is documented in `docs/security/nist-ssdf-mapping.md`. The
Approved-SLSA-1.2-pinned provenance plan is documented in
`docs/security/slsa-provenance-plan.md`; both SLSA tracks remain unevaluated.
None establishes deployed control effectiveness or independent assurance.
