# Security Questionnaire

This questionnaire summarizes the current ReconForge ERP security posture for local pilot and buyer review. It distinguishes implemented, partial, roadmap, and not-supported areas. It is not a SOC, ISO, SOX, GDPR, audit, legal, or compliance certification claim.

## Status Labels

| Label | Meaning |
| --- | --- |
| Implemented | Present in the repository and covered by current code/docs/tests to the extent described. |
| Partial | Implemented for a limited local scope, with important gaps or boundaries. |
| Roadmap | Designed or planned, but not implemented as a supported product capability. |
| Not supported | Not currently provided and should not be claimed. |

## Data Flow And Hosting

| Area | Status | Notes |
| --- | --- | --- |
| Local-first core workflows | Implemented | CLI workflows read local CSV/XLSX exports and write local outputs. |
| Export-based ERP model | Implemented | Mapping profiles and docs describe local exports, not live ERP connections. |
| SaaS hosting | Not supported | ReconForge does not provide a production SaaS tenant or hosted storage. |
| Cloud upload for core workflows | Not supported | Core workflows do not require cloud upload, telemetry, or a paid API. |
| Direct ERP connectors | Not supported | No live ERP API connector, sync, writeback, vendor-certified integration, or ERP credential handling is claimed. |

## Identity And Access

| Area | Status | Notes |
| --- | --- | --- |
| Local users and password hashing | Implemented | Local SQLite-backed users use password hashing for supported auth-required workflows. |
| RBAC roles | Implemented | Built-in local roles and permission checks exist for implemented DB/API/Studio paths. |
| Session token hashing | Implemented | Local API/Studio session-token hashing is implemented for supported auth flows. |
| Studio auth-required mode | Partial | Auth-required mode protects implemented Studio DB actions; this is not production identity infrastructure. |
| SSO/OIDC/SAML | Roadmap | Design docs exist; implementation is not supported today. |
| SCIM | Roadmap | Design docs exist; implementation is not supported today. |
| Enterprise identity readiness | Not supported | No production identity readiness, managed tenant administration, or enterprise IAM certification is claimed. |

## Audit Events, Evidence, And Integrity

| Area | Status | Notes |
| --- | --- | --- |
| Append-only audit event hash chain | Implemented | Local audit events include hash-chain verification aids. |
| Evidence manifests/checksums | Implemented | Evidence and client-pack workflows can include SHA-256 integrity aids. |
| DB backup checksum manifest | Implemented | Local DB backup/restore includes checksum validation. |
| Legal digital signatures | Not supported | Checksums and workflow metadata are not signatures or non-repudiation controls. |
| Audit opinions or assurance conclusions | Not supported | ReconForge does not issue or imply audit opinions. |
| Compliance certification | Not supported | No SOC, ISO, SOX, GDPR, tax, regulatory, or audit compliance certification is claimed. |

## Secure Handling And Output Safety

| Area | Status | Notes |
| --- | --- | --- |
| Safe YAML parsing | Implemented | Rule and mapping YAML should be loaded through safe parsing and schema validation. |
| HTML escaping posture | Implemented | Generated report and Studio routes use escaping/path safety patterns where implemented. |
| Download/path traversal controls | Implemented | Download-like routes use allowlists, suffix checks, and resolved-path checks. |
| Sanitized DB export | Implemented | DB export excludes credential and session material. |
| Redaction controls | Partial | Client packs support redaction options, but users must review outputs before sharing. |
| Anonymization | Partial | Anonymization is local and useful for demos, but it is not a guarantee that data is safe to publish. |

## Development And Release Posture

| Area | Status | Notes |
| --- | --- | --- |
| Ruff, mypy, pytest gates | Implemented | Required local quality commands are documented. |
| Bandit and pip-audit checks | Implemented | Security checks are documented for release and PR review. |
| CodeQL workflow | Implemented | Repository workflow support exists where configured. |
| SBOM workflow | Implemented | SBOM workflow support exists for release/manual workflow contexts. |
| Docker build workflow | Implemented | Docker build support is documented. |
| Docker runtime verification | Partial | Only claim runtime verification after documented Docker build/run commands pass in a live Docker environment. |

## Support And Data Sharing

| Area | Status | Notes |
| --- | --- | --- |
| Support playbook | Implemented | Draft, non-contractual support guidance exists for issue intake and escalation. |
| Public issue data rules | Implemented | Docs instruct users not to share live customer data publicly. |
| Contractual SLA | Not supported | No SLA is guaranteed by the open-source project. |
| Incident response service | Not supported | No managed incident-response commitment is provided by the open-source project. |

## Buyer Review Notes

- Treat live ERP exports, generated evidence, client packs, backups, and SQLite databases as sensitive unless a data owner classifies them otherwise.
- Use synthetic or anonymized data for public issues, screenshots, and demos.
- Do not infer production readiness, compliance certification, or legal assurance from tests, checksums, badges, or security docs.
- Use the release readiness checklist before relying on version-specific claims.
