# Competitor Capability Matrix (Competitively Bounded, Evidence-Led)

Last updated: 2026-07-31

This is a bounded competitive assessment only. It compares reconforge observed capabilities to
public, first-party platform documentation and does **not** claim compliance, certification,
enterprise-grade guarantees, or competitive superiority.

## Public Sources Reviewed (Primary Sources)

- BlackLine product and trust pages: <https://www.blackline.com/products/financial-close/account-reconciliations/>,
  <https://www.blackline.com/legal/security/>
- Trintech Cadency pages: <https://www.trintech.com/cadency/>, <https://www.trintech.com/solutions-cloud-trintech/>
- FloQast product trust pages: <https://www.floqast.com/trust-and-security/>
- Workiva security and trust pages: <https://support.workiva.com/hc/en-us/articles/10982212432148-Security-and-compliance-portal>
- OneStream and SAP reference pages: <https://documentation.onestream.com/9.2.0/Content/Financial%20Close/Overview.html>,
  <https://help.sap.com/docs/SAP_S4HANA_CLOUD/0fa84c9d9c634132b7c4abb9ffdd8f06/98d060a69b8a47e6a83e60104943d756-552.html>
- Odoo and Oracle financial docs: <https://www.odoo.com/documentation/15.0/applications/inventory_and_mrp/inventory/management/reporting/using_inventory_valuation.html>,
  <https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4843345777.html>
- AuditBoard and MetricStream trust/overview pages: <https://auditboard.com/trust-security/>, <https://www.metricstream.com/solutions/audit-management.htm>
- ServiceNow trust and documentation: <https://www.servicenow.com/company/trust.html>

## Dimension Matrix (2026-07-31 snapshot)

| Dimension | Competitor Baseline | Evidence-led ReconForge Position | Known Limits / Unknowns | Measurement Status |
| --- | --- | --- | --- | --- |
| Deployment sovereignty | Most platform pages emphasize managed SaaS, cloud multi-tenant control planes, or vendor-hosted operations. | ReconForge uses local-first execution (`apps/web` + Community CLI) and explicitly documents air-gapped/sovereign offline flow in `docs/operations/offline` and related evidence files. | Multi-region active/active hosting and hardware-assisted key-management are not yet proven in this workspace. | Bounded by local/offline docs and drills (`P3-ENT-011`, `E-214`–`E-220`). |
| Determinism | Vendors describe stable matching workflows and controls but usually at black-box platform API level. | Deterministic pipelines are implemented for critical matching/finance paths with versioned strategies, strict inputs, and digest-bound outputs in matching and finance modules. | Not all strategies are proven equivalent at cloud-scale or cross-host concurrency. | Core replay/permutation invariance evidence in `E-004`–`E-006`, plus strategy and reconciliation contracts (`E-105` onward). |
| Evidence lineage | Enterprise vendors provide audit/control workflows with platform-trace artifacts, often not fully exportable from a single manifest. | ReconForge maintains evidence manifests and artifact digests for most synthetic and local runs (for example `docs/execution/EVIDENCE.md` entries and schema-bound files), including hash chaining for incident recovery (`E-227`). | End-to-end immutable external trust chain and signed multi-source evidence are only partially implemented. | Lineage evidence in `E-103`–`E-110`, `E-092`, `E-227`, `E-228` and related ADRs. |
| Matching breadth | Global suites offer broad domain matching options and ERP-native coverage. | Current active engines cover multiple strategies, strategy budgets, grouped matching, FX awareness, tolerance/bucketing, and ambiguity output (`RF` runbooks) in local pipelines. | No evidence yet for broad many-to-many production scale at all datasets and all connectors. | Local engine breadth in `P1-REC-004`, `P1-REC-007`, `P1-REC-005`, and benchmark suites. |
| Scale evidence | Public platforms publish scale indicators in marketing and operational literature. | ReconForge has reproducible benchmark files and measured local profile evidence up to 100K/1M synthetic runs in previous plan slices. | 1M and 10M enterprise-level external workload claims are not yet proven in production network environments. | Reproducibility evidence in `docs/execution/PERFORMANCE_BASELINE.md` and `E-113`. |
| Connector ecosystem | Vendors advertise broad native connectors and integration catalogs. | ReconForge currently uses explicit local/CSV-led connectors, manifests, and a read-only connector model as closed policy (`P3-ENT-007`, `E-208`). | Direct live read/write integrations and connector conformance at scale remain a planned Phase 3/4 task. | Connector policy evidence in `docs/execution/EVIDENCE.md` and `docs/execution/BACKLOG.yaml`. |
| AI governance | Vendors position AI assistance at varying autonomy. | ReconForge keeps AI constrained, optional, and non-authoritative with explicit local/offline-first posture in security/reliability architecture docs. | Full AI quality, prompt injection, and operator-policy validation at enterprise depth remain bounded and still expanding. | AI governance notes in the architecture/ADR set and `P3-ENT-012` runbook scope. |
| Security posture | Vendor trust pages combine controls, certifications, and enterprise assurance claims. | ReconForge documents security architecture, ASVS/SSDF mappings, and signed-candidate hardening with dependency policy in local evidence (`E-001` through `E-087`, `E-103`–`E-104`). | No independent certification, no official SOC/ISO/PCI claim from this repo, and no external assurance report yet. | Internal control evidence is extensive; external attestation remains open (`P3-EXT-002`). |
| UX and accessibility | Many suites are broad and full-service, but often assume enterprise onboarding, admin structure, and remote identity. | ReconForge tracks RTL/localization direction and exposes lightweight review/exception and studio primitives in documented phases. | Deep accessibility automation across every path and multilingual workflow is still in progression. | Documented as bounded in `docs/execution/CLAIMS_EVIDENCE_MATRIX.md` and `P3-ENT-012` evidence. |
| Extensibility | Vendor ecosystems are commercially controlled and extension-heavy. | ReconForge supports pack + manifest patterns and explicit modularity in code and packaging, with explicit boundaries on what is currently local-only. | Industrial pack authoring depth and third-party plugin ecosystem are bounded and evidence-driven. | Evidence in `P1-PLAT-001`→`P1-REC-009`, `P3-ENT-007`, and module descriptors. |

## Comparison Notes (No Competitor Superiority Claims)

- Stronger for open-source and sovereign-first operations:
  - Local/air-gap deployment narratives are explicit and bounded.
  - Evidence manifests and deterministic synthetic drills are first-class.
- Stronger for global platform breadth:
  - Broad native connector catalogs and high-scale managed controls are materially broader in established commercial products.
- Missing for ReconForge (before production claim):
  - Independent external security review (`P3-EXT-002`), verified enterprise pilots (`P3-EXT-001`), broader connector trust programs, and true multi-node HA/DR production evidence.

## Required Evidence Before Marketing Wording Claims

- Any claim on matching scale, governance, compliance, or deployment readiness must cite bounded evidence IDs in `docs/execution/EVIDENCE.md`.
- All claims must avoid generic “enterprise” or certification language unless each claim maps to dated evidence and an approved external review gate.
- Unknown costs (time-to-onboard, support cost, and enterprise run cost) must remain explicit until validated with pilots.

## Maintenance

This document must be updated with exact dates, public-source snapshots, and evidence IDs when:
- New reconforge enterprise slices close.
- A pilot produces approved, scoped business outcomes.
- Independent security review closes open high-risk claims.

