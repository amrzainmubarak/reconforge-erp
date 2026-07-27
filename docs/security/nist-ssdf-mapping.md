# NIST SSDF 1.1 Repository Mapping

The normative source is `docs/security/nist-ssdf-1.1-mapping.v1.yaml`, validated
by `docs/schemas/ssdf_mapping.schema.json`. This readable view is not an SSDF conformance
assessment, certification, independent review, deployment assessment, or claim
that the process operates continuously.

## Official source boundary

- Final source: NIST SP 800-218, SSDF 1.1, published 2022-02-03.
- Official publication: <https://csrc.nist.gov/pubs/sp/800/218/final>
- DOI: <https://doi.org/10.6028/NIST.SP.800-218>
- PDF: 739,891 bytes, SHA-256
  `617746e553a9e2da49bfbd4eef0dfc3094758a39b869314e4173ac36605cde22`.
- Official Excel table: 50,039 bytes, SHA-256
  `f5729c4c6c792cbf6cfbea74eee7cc84c579b2109006fe3cbfa8934eb460bd55`.
- Reviewed structure: 4 groups, 19 practices, and all 42 tasks.
- NIST SP 800-218 Rev. 1 / SSDF 1.2, published 2025-12-17, is an
  initial public draft and is monitored but excluded from this final-source
  mapping.
- NIST SP 800-218A is a final supplemental community profile. ReconForge needs
  a separate profile assessment before any model-backed AI capability is
  promoted; this matrix does not silently mark that profile covered or not
  applicable.

The NIST artifacts were read in memory to verify identifiers and counts. They
and their full task prose are not copied into this repository.

## Status result

| Status | Tasks | Meaning here |
| --- | ---: | --- |
| Implemented-bounded | 0 | No task received this label from repository presence alone |
| Partial | 28 | Existing files/tests address a bounded part while explicit gaps remain |
| Planned | 14 | No sufficient positive repository evidence supports the outcome |
| Not applicable | 0 | No core SSDF 1.1 task was excluded |

Every task has an owner, assessment, gap, and next action. Partial tasks also
have existing evidence and test paths. Planned tasks have no positive evidence
links. Review is owned by `release-security` every 90 days; the next scheduled
review is 2026-10-23, with earlier review on a final SSDF successor, material
SDLC/security change, model-backed AI promotion, or material vulnerability.

## Complete task coverage

### `PO` — Prepare the Organization

| Practice | Official practice name | Task status |
| --- | --- | --- |
| `PO.1` | Define Security Requirements for Software Development | PO.1.1 partial; PO.1.2 partial; PO.1.3 planned |
| `PO.2` | Implement Roles and Responsibilities | PO.2.1 partial; PO.2.2 planned; PO.2.3 planned |
| `PO.3` | Implement Supporting Toolchains | PO.3.1 partial; PO.3.2 partial; PO.3.3 partial |
| `PO.4` | Define and Use Criteria for Software Security Checks | PO.4.1 partial; PO.4.2 partial |
| `PO.5` | Implement and Maintain Secure Environments for Software Development | PO.5.1 partial; PO.5.2 planned |

Primary open outcomes are an approved requirements/exception lifecycle,
role-based training and management commitment, protected SDLC evidence,
hash-locked/reproducible toolchains, verified environment separation, and
developer endpoint hardening.

### `PS` — Protect the Software

| Practice | Official practice name | Task status |
| --- | --- | --- |
| `PS.1` | Protect All Forms of Code from Unauthorized Access and Tampering | PS.1.1 partial |
| `PS.2` | Provide a Mechanism for Verifying Software Release Integrity | PS.2.1 planned |
| `PS.3` | Archive and Protect Each Software Release | PS.3.1 partial; PS.3.2 planned |

CODEOWNERS and least-privilege workflow declarations are intent, not verified
repository/ruleset access. Signed release verification, protected archives,
hosted signed release-bound SBOM/provenance execution and protected publication are not implemented; only candidate definitions and bounded local SBOM outputs exist.

### `PW` — Produce Well-Secured Software

| Practice | Official practice name | Task status |
| --- | --- | --- |
| `PW.1` | Design Software to Meet Security Requirements and Mitigate Security Risks | PW.1.1 partial; PW.1.2 partial; PW.1.3 partial |
| `PW.2` | Review the Software Design to Verify Compliance with Security Requirements and Risk Information | PW.2.1 partial |
| `PW.4` | Reuse Existing Well-Secured Software When Feasible | PW.4.1 partial; PW.4.2 partial; PW.4.4 partial |
| `PW.5` | Create Source Code by Adhering to Secure Coding Practices | PW.5.1 partial |
| `PW.6` | Configure Compilation Interpreter and Build Processes for Executable Security | PW.6.1 partial; PW.6.2 planned |
| `PW.7` | Review or Analyze Human-Readable Code | PW.7.1 partial; PW.7.2 partial |
| `PW.8` | Test Executable Code for Vulnerabilities and Security Requirements | PW.8.1 partial; PW.8.2 planned |
| `PW.9` | Configure Software to Have Secure Settings by Default | PW.9.1 partial; PW.9.2 partial |

The repository has strong bounded design/test evidence, but lacks independent
design review records, hosted/provenanced component governance, complete secure
coding standards, approved interpreter/build hardening, DAST/fuzz/penetration
program evidence, and a closed administrator setting inventory.

### `RV` — Respond to Vulnerabilities

| Practice | Official practice name | Task status |
| --- | --- | --- |
| `RV.1` | Identify and Confirm Vulnerabilities on an Ongoing Basis | RV.1.1 partial; RV.1.2 partial; RV.1.3 partial |
| `RV.2` | Assess Prioritize and Remediate Vulnerabilities | RV.2.1 planned; RV.2.2 planned |
| `RV.3` | Analyze Vulnerabilities to Identify Their Root Causes | RV.3.1 planned; RV.3.2 planned; RV.3.3 planned; RV.3.4 planned |

Private reporting and scheduled analysis exist as definitions. The repository
does not prove intake operation, protected vulnerability cases, assessment and
remediation SLAs, advisories/backports, root-cause analysis, class eradication,
or root-cause-driven SDLC improvement.

## Claim boundary

This matrix supports the wording: “ReconForge maintains a version-pinned,
all-task repository evidence/gap mapping for NIST SSDF 1.1.” It must not be used
to claim SSDF conformance, a secure SDLC, a secure product, compliance,
certification, independent assurance, or production readiness.
