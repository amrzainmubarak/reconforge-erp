# Global Enterprise Capability Benchmark

This benchmark summarizes public capability patterns from finance close, account reconciliation, audit, GRC, ERP, and reporting platforms. It is functional research only. ReconForge does not copy proprietary product text, workflows, UI, names, templates, screenshots, or branding, and it is not positioned as a replacement for any enterprise platform.

Public sources reviewed include official product, documentation, security, and trust pages from BlackLine, Trintech Cadency, FloQast, Numeric, OneStream, Workiva, AuditBoard, ServiceNow GRC, MetricStream, SAP, Odoo, Oracle, NetSuite, Microsoft Dynamics, and ERPNext.

Representative public sources:

- <https://www.blackline.com/products/financial-close/account-reconciliations/>
- <https://www.trintech.com/cadency/>
- <https://www.floqast.com/trust-and-security/>
- <https://www.numeric.io/essentials>
- <https://documentation.onestream.com/9.2.0/Content/Financial%20Close/Overview.html>
- <https://www.workiva.com/solutions/audit-risk-compliance>
- <https://auditboard.com/platform>
- <https://www.servicenow.com/docs/r/governance-risk-compliance/r_WhatIsGRC.html>
- <https://www.metricstream.com/solutions/audit-management.htm>
- <https://www.odoo.com/documentation/>
- <https://help.sap.com/docs/>
- <https://docs.oracle.com/en/cloud/saas/financials/>
- <https://docs.oracle.com/en/cloud/saas/netsuite/>
- <https://learn.microsoft.com/en-us/dynamics365/supply-chain/cost-management/inventory-costing-faq>
- <https://docs.frappe.io/erpnext/>

## Capability Benchmark

| Capability group | Global platform pattern | Why it matters | ReconForge current state | Gap | Local-first ReconForge-native opportunity | Legal/compliance risk | Complexity | Priority | Target release phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Account reconciliation | Account schedules, preparer/reviewer ownership, balances, support, thresholds, certification | Gives controllers repeatable account-level close evidence | Exception review and management packs exist | No account-level template or balance certification workflow | File-based account reconciliation template with balance support and evidence references | High if framed as assurance | High | High | v0.9.0 |
| Transaction matching | Rule-driven and suggested matches with exception queues | Reduces manual matching burden and supports review | Stock-to-GL matching with configurable strategies | Confidence explanations can be richer | Explainable matching confidence and candidate register | Medium if opaque or overclaimed | Medium | High | v0.9.0 |
| Financial close checklist | Task lists, owners, due dates, blockers, close progress | Provides close readiness visibility | Local close checklist foundation | No dependencies or period calendar | JSON close state with readiness score and report | Low if workflow-only | Low | High | v0.8.0 |
| Close calendar | Period calendar, due dates, dependencies, recurring tasks | Helps teams coordinate close deadlines | Due dates are plain text in checklist | No generated calendar or recurrence | Local calendar export from template | Low | Medium | Medium | v0.8.0 |
| Certification/sign-off | Prepared/reviewed metadata, account certifications, evidence acknowledgement | Captures workflow accountability | Certification metadata foundation | No account-level workflow or authentication | Workflow metadata only with explicit no-signature boundary | High if treated as legal sign-off | Medium | High | v0.8.0 |
| Preparer/reviewer workflow | Segregation, comments, review queues, returned items | Improves quality of close evidence | Local review state and Studio updates | No RBAC, no queue ownership | Plain-text owner/reviewer fields and exportable review register | Medium | Medium | High | v0.8.0 |
| Journal entry controls | Manual JE review, approvals, posting checks, attachments | Manual postings are high-risk close items | GL export rules can inspect references and amounts | No JE-specific profile yet | Export-based journal control pack, no ERP writeback | Medium | Medium | High | v0.8.0 |
| Variance analysis | Flux reports, thresholds, explanations, sign-off | Controllers need period movement visibility | Variance foundation compares local summaries | No account-level variance explanations yet | Threshold-driven variance register with explanation placeholders | Medium if interpreted as assurance | Low | High | v0.9.0 |
| Intercompany reconciliation | Entity matching, dispute workflow, currency and elimination support | Important for multi-entity close | Not implemented | Needs entity and currency export schema | Export-based intercompany foundation with strict limits | Medium | High | Medium | v0.9.0 |
| Subledger-to-GL reconciliation | AR/AP/inventory/subledger to GL tie-out | Core finance control | Stock-to-GL implemented | Broader subledger profiles missing | Additional export profiles and mapping validation | Medium | High | High | v0.9.0 |
| Risk/control matrix | Controls, risks, owners, evidence, frequency | Gives audit and control visibility | Control matrix foundation from rule packs | No testing procedure register yet | GRC-lite matrix with owner/frequency placeholders | High if called certification | Low | High | v0.10.0 |
| Control testing | Test plans, samples, findings, remediation | Moves from detection to control operation review | Rules detect exceptions | No test workflow | Local control test register and evidence mapping | High | Medium | Medium | v0.10.0 |
| Audit evidence | Evidence requests, case files, support, index | Supports audit prep and handoff | Evidence binder exists | Evidence coverage and provenance can improve | Evidence coverage score and stronger manifest model | Medium | Medium | High | v0.10.0 |
| Evidence integrity | Checksums, manifests, provenance, retention | Helps verify generated files did not change | SHA-256 manifests exist | No signing/provenance release plan | Optional signed checksums plan, not legal signature | High if called digital signature | Medium | Medium | v0.13.0 |
| Task workflow | Statuses, blockers, ownership, aging | Helps teams resolve exceptions | Review state and close state exist | No unified task register | Local task register across close/exceptions/controls | Medium | Medium | Medium | v0.12.0 |
| Collaboration/review | Comments, notifications, teams, permissions | Enables multi-person work | Studio local review updates | No auth or notification | Keep local-only comments and exports before v1.0 | High if multi-user added prematurely | High | Low now | Deferred |
| Dashboards/KPIs | Close health, risk, review completion, aging, evidence coverage | Gives executives quick risk view | Static dashboard and management pack | KPI coverage still growing | Review completion, unresolved high-risk, evidence coverage, close completion | Low | Low | High | v0.7.0-v0.10.0 |
| ERP integrations/export workflows | API connectors, scheduled ingestion, saved reports | Reduces manual export work | Export profiles and mapping validation | No Oracle profile and no generic builder until now | Export profile layer, Oracle profile, profile template | Medium if connector implied | Medium | High | v0.11.0 |
| Data quality validation | Missing fields, invalid values, duplicate references | Bad exports undermine reconciliation | Input validation and mapping inspection exist | More profile confidence scoring needed | Profile confidence and data quality score | Low | Medium | High | v0.11.0 |
| Anomaly detection | Pattern detection, unusual values, AI triage | Helps prioritize review | Risk scoring and rules exist | No general anomaly score | Explainable local anomaly scoring | Medium | High | Medium | v0.9.0 |
| AI assistance | Narrative summaries, explanations, workflow help | Speeds review, but can obscure logic | Offline deterministic explanations and AI docs | No advanced assistant workflow | Optional local/bring-your-own assistant with deterministic fallback | High | High | Low now | v0.9.0+ |
| Governance/security | Trust centers, access controls, audit logs, certifications | Enterprise buyers expect controls | Security docs, tests, Bandit, CodeQL, checksums | No formal certification claim | Secure-by-design evidence, SBOM, Scorecard docs, release provenance plan | High if claims overreach | Medium | High | v0.13.0 |
| Deployment and packaging | SaaS, managed cloud, Docker, APIs, enterprise deployment | Evaluation and operations need repeatability | Docker workflow exists; runtime verification cautious | Need runtime verification before claims | Verified Docker runtime and static demo assets | Medium | Medium | High | v0.7.0 |
| Marketplace/plugins | Partner apps, rule libraries, integrations | Extends platform reach | Plugin foundation and rule packs exist | No curated local pack marketplace | Local rule/profile pack catalog and templates | Medium | Medium | Medium | v0.11.0 |
| Commercial/pilot readiness | Demo assets, onboarding, pilot checklist, support paths | Converts interest into credible pilots | Pilot docs exist | Need stronger proof points and release integrity | Public pilot checklist and demo output pack | Medium | Low | High | v0.7.0 |

## Source Themes

Enterprise platforms converge around structured ownership, evidence traceability, configurable controls, dashboards, and trust posture. ReconForge should adopt the underlying control patterns only where they fit local exports, transparent rules, and open-source review.

ReconForge should avoid enterprise claims that require hosted security operations, contractual assurance, direct ERP connectors, customer proof, legal sign-off, or formal compliance certification.
