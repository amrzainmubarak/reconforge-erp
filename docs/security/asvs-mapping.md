# OWASP ASVS Mapping

The normative mapping is
[`asvs-5.0.0-mapping.v1.yaml`](asvs-5.0.0-mapping.v1.yaml), validated by
[`asvs_mapping.schema.json`](../schemas/asvs_mapping.schema.json).

It is not a compliance assessment, certification, full ASVS verification,
penetration test, audit opinion, or secure-deployment guarantee. It maps 55
selected high-relevance requirements and leaves the other 290 requirements
explicitly **unassessed**. Unassessed does not mean implemented, failed,
planned, or not applicable.

## Official source pin

As verified on 2026-07-25, OWASP identifies ASVS 5.0.0 (released 2025-05-30)
as the latest stable version. The changing `master` release is labelled
Bleeding Edge and was excluded.

- Project: <https://owasp.org/www-project-application-security-verification-standard/>
- Stable release: <https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release>
- Release tag commit: `5cf9b032440be53ce345ab3c130fda46ba1ce7a2`
- Pinned English CSV: <https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0_release/5.0/docs_en/OWASP_Application_Security_Verification_Standard_5.0.0_en.csv>
- Pinned CSV bytes: `105100`
- Pinned CSV SHA-256: `98c8fe911b9edb403af8ee05d3ce8201ecac2659e313b053890a62847cdcf680`
- Upstream license: CC BY-SA 4.0

Requirement references include the version, following OWASP's recommended
`v<version>-<chapter>.<section>.<requirement>` form. The mapping records IDs,
levels, and ReconForge assessments without reproducing the complete upstream
requirement text.

## What the statuses mean

- `implemented` means only that the narrow `scope` field has direct code and
  test evidence. It does not cover the whole product, requirement, or deployed
  environment.
- `partial` means some relevant evidence exists but material requirement,
  product, or deployment scope remains open.
- `planned` means the requirement is relevant or expected to become relevant,
  but evidence is insufficient even for partial status.
- `not_applicable` means the named technology/capability is absent now and a
  concrete trigger requires reassessment if it is introduced.
- `unassessed` applies to every official requirement omitted from the selected
  set. No conclusion is attached to those requirements.

The selected status totals are: 4 implemented, 33 partial, 10 planned, and 8
not applicable. ReconForge is not assigned an ASVS verification level.

## Chapter coverage

| Chapter | Official requirements | Selected | Unassessed | Selected status mix |
| --- | ---: | ---: | ---: | --- |
| `V1` Encoding and Sanitization | 30 | 3 | 27 | 1 partial, 1 planned, 1 not applicable |
| `V2` Validation and Business Logic | 13 | 3 | 10 | 3 partial |
| `V3` Web Frontend Security | 31 | 3 | 28 | 1 implemented, 2 partial |
| `V4` API and Web Service | 16 | 4 | 12 | 2 partial, 2 not applicable |
| `V5` File Handling | 13 | 5 | 8 | 4 partial, 1 planned |
| `V6` Authentication | 47 | 4 | 43 | 2 partial, 2 planned |
| `V7` Session Management | 19 | 3 | 16 | 2 implemented, 1 partial |
| `V8` Authorization | 13 | 3 | 10 | 3 partial |
| `V9` Self-contained Tokens | 7 | 1 | 6 | 1 not applicable; opaque reference sessions only |
| `V10` OAuth and OIDC | 36 | 2 | 34 | 2 not applicable; no OAuth/OIDC role is implemented |
| `V11` Cryptography | 24 | 3 | 21 | 3 partial |
| `V12` Secure Communication | 12 | 3 | 9 | 2 partial, 1 planned |
| `V13` Configuration | 21 | 3 | 18 | 1 partial, 2 planned |
| `V14` Data Protection | 13 | 3 | 10 | 1 implemented, 2 partial |
| `V15` Secure Coding and Architecture | 21 | 4 | 17 | 3 partial, 1 planned |
| `V16` Security Logging and Error Handling | 17 | 6 | 11 | 4 partial, 2 planned |
| `V17` WebRTC | 12 | 2 | 10 | 2 not applicable; no WebRTC/TURN/media surface |
| **Total** | **345** | **55** | **290** | **4 implemented, 33 partial, 10 planned, 8 not applicable** |

## Important current gaps

The mapping makes several high-impact gaps visible rather than averaging them
away:

- spreadsheet formula-injection policy is not consistent across exports;
- canonical tabular and selected structured-document limits, including FI-011
  close files and two FI-012 manifest readers, are implemented; FI-012 also
  freezes resource-bounded JSON/CSV/text/non-redacted copies and stages the
  complete pack with handled-failure rollback. Crash-atomic existing-directory
  replacement, report/Studio readers, legacy XLS internals,
  authenticated provenance/disclosure authorization, and malware quarantine
  remain incomplete;
- password minimum/breached-password and secure recovery policies are absent;
- authorization is not yet complete field/entity/period/amount ABAC;
- TLS termination, protocol/certificate policy, and live negative-certificate
  tests are deployment gaps;
- no integrated secret manager, key lifecycle, or full cryptographic inventory
  exists;
- Python/server resolution is hash-locked locally, but hosted two-version and
  container enforcement plus signed release-bound SBOM/provenance remain
  unverified;
- failed-authorization logging and a complete classified log inventory are
  planned; and
- OAuth/OIDC, self-contained tokens, GraphQL, WebSocket, XML, and WebRTC must
  be reassessed before those surfaces are introduced.

## Maintenance gate

Review is required when OWASP publishes a newer stable ASVS version, the pinned
source changes, or ReconForge changes its browser/API/file/identity/token/
cryptography/network/logging/dependency/WebRTC surfaces. Source-version changes
must update the release pin, digest, chapter counts, selected ID/level fixture,
mapping, readable summary, ADR, and evidence together.

No public wording may turn this mapping into an ASVS pass, compliance,
certification, secure-product, enterprise-readiness, bank-grade, or
production-readiness claim.
