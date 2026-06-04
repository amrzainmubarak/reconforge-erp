# Feature Gap Matrix

This matrix compares broad public market expectations with ReconForge ERP v0.6.1 behavior and proposed ReconForge-native enhancements. It is not a claim of compatibility, replacement, certification, or vendor endorsement.

| Capability | Global platforms usually provide | ReconForge current state | Gap | Proposed ReconForge-native enhancement | Implementation phase | Business value | Technical risk | Security/privacy impact | Tests needed | Documentation needed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Transaction matching | Configurable matching, suggested matches, exception queues | Stock-to-GL matching with strategies and outputs | Matching confidence could be more visible | Explainable confidence report and candidate audit trail | v0.9.0 | Faster review of unmatched rows | Medium | Local files only; escape reports | Matching confidence tests | Reconciliation methodology |
| Account reconciliation | Account policies, preparer/reviewer workflow, certification | Exception review state and register | No account-level certification template | Lightweight account reconciliation template from exports | v0.8.0 | Better close documentation | Medium | Workflow metadata must not imply audit opinion | CLI/schema tests | Reconciliation certification |
| Close checklist | Calendar, tasks, owners, status dashboards | New local close checklist foundation | No dependencies or calendar yet | JSON/YAML checklist, local task status, close report | v0.7.0 foundation; v0.8.0 expansion | Month-end readiness visibility | Low | Plain text owners; HTML escape needed | CLI, malformed input, HTML escaping | Close workflow |
| Journal entry controls | JE workflow, approvals, posting integration | Rule packs can inspect GL exports | No journal-specific export checks | Manual journal and missing-reference control pack | v0.8.0 | Detect unsupported postings | Medium | No ERP writeback | Rule-pack tests | Controls docs |
| Evidence collection | Evidence requests, folders, audit trail | Evidence binder and checksum manifest | Coverage KPI and stronger chain-of-custody plan needed | Evidence coverage KPI and optional signing plan | v0.7.0-v0.9.0 | Audit prep clarity | Medium | Evidence may contain sensitive data | Evidence index and manifest tests | Evidence integrity |
| Audit trail | User workflow history, timestamps, immutable logs | Review state timestamps and evidence audit JSON | No append-only local activity log | Local activity log with checksums | v0.9.0 | Better defensibility | Medium | Avoid raw exception leakage | Append-only tests | Security model |
| Variance analysis | Flux reports, thresholds, explanations | Multi-period exception comparison | No numeric summary variance command | Local variance analysis from generated summaries | v0.7.0 foundation | Controller review support | Low | Escape HTML; no savings claims | CLI and malformed input tests | Variance analysis |
| Intercompany reconciliation | Entity matching, disputes, eliminations | Not implemented | Needs entity/currency exports | Export-based intercompany matching foundation | v0.9.0 | Common close pain point | High | Sensitive entity data | Synthetic fixtures | Intercompany docs |
| Risk/control testing | Control library, test plans, findings | Rule packs and risk scoring | No control matrix or testing register | Rule-pack-derived control matrix | v0.7.0 foundation | Internal audit handoff | Low | Markdown/HTML injection in descriptions | Matrix export tests | Control matrix |
| Exception workflow | Assignment, status, escalation, accepted risk, aging | Local review workflow and period comparison | Recurring exception aging is limited | Aging by comparison key and status | v0.9.0 | Prioritize chronic issues | Medium | Local state only | Period aging tests | Review workflow |
| Collaboration/review | Comments, notifications, permissions | Studio local review actions, CLI state | No auth or team workflow | Keep owner/reviewer fields only before v1.0 | Deferred | Avoids premature security scope | High if expanded | Auth/IAM would be high-risk | Not applicable yet | Limitations docs |
| Dashboards/KPIs | Close health, control health, risk dashboards | Static dashboard and management pack | KPIs need close/evidence/review signals | Review completion, unresolved high-risk, accepted risk, recurring, close completion, evidence coverage | v0.7.0 foundation | Executive scan value | Low | Must label unavailable data | Management pack tests | Report docs |
| ERP integrations/export workflows | Connectors, APIs, scheduled ingestion | Export profiles and mapping validation | No direct connectors | Continue export profiles and header inspection | Ongoing | Accessible pilots | Medium | Avoid credential handling | Mapping validation tests | ERP export profiles |
| AI assistant | Narrative generation, anomaly flags, workflow help | Offline deterministic explanations and AI architecture docs | No advanced anomaly scoring | Optional explainable anomaly scoring and local prompt packs | v0.9.0+ | Review prioritization | High | Avoid black-box decisions | Determinism tests | AI assistant architecture |
| Security/governance | Trust centers, certifications, access controls | Security docs, Bandit, CodeQL, checksums, redaction | No formal certification claims | Strengthen release verification and dependency posture | v0.7.0-v1.0.0 | Trust for pilots | Medium | No secrets, no telemetry | Security tests and audits | Security docs |
| Deployment/packaging | SaaS, managed cloud, Docker, APIs | Docker build workflow documented; runtime verification cautious | Runtime verification not claimed | Verified Docker build/run checklist and demo packaging | v0.7.0 | Public demo confidence | Medium | Avoid exposed local services | Smoke tests | Docker deployment |
| Commercial/pilot readiness | Customer onboarding, ROI, enterprise sales collateral | Pilot docs and conservative commercial docs | Need public pilot checklist and proof points | Pilot checklist, release integrity plan, demo pack refresh | v0.7.0 | Better evaluator journey | Low | Avoid fake adoption claims | Docs link tests | Commercial docs |

## Immediate Foundation Delivered

The v0.7.0 foundation work implemented now covers:

- Local close checklist workflow.
- Reconciliation certification metadata in review exports.
- Local variance analysis.
- Rule-pack-derived control matrix exports.
- Management pack KPI improvements.

These features deliberately avoid SaaS, direct ERP connectors, web authentication, hosted storage, legal sign-off, audit opinions, and digital signature claims.
