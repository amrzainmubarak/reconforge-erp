# Commercial Strategy

This strategy assumes ReconForge ERP remains a useful open-source project even if no commercial edition is purchased.

## 1. Open-Source Core

The open-source core should include:

- CLI workflows.
- Canonical schemas.
- Stock-to-GL reconciliation.
- WIP and work-order controls.
- Rule engine.
- Control packs.
- Evidence binder.
- Anonymization.
- Synthetic data.
- Benchmarking.
- Local Studio baseline.
- Export-based mapping profiles.

## 2. Paid Self-Hosted Edition

Possible later paid edition:

- Local authentication.
- Reviewer roles.
- Persistent SQLite/Postgres state.
- Saved review sessions.
- Team workflows.
- Evidence attachments.
- Admin dashboard.
- Advanced branding.

This should remain self-hosted first. SaaS should not be the near-term default.

## 3. Implementation Services

Services can include:

- Data export mapping.
- Odoo/SAP workflow setup.
- Control-pack configuration.
- Evidence binder setup.
- Training.
- Pilot close support.

## 4. Audit-Pack Service

Offer scoped audit packs:

- Inventory valuation audit pack.
- WIP aging and work-order pack.
- Purchase-to-pay pack.
- High-risk transaction pack.
- SAP export review pack.
- Odoo stock valuation pack.

Deliverables should include mapping notes, rule results, exception summary, and evidence register.

## 5. Monthly Reconciliation Service

For companies without internal automation capacity:

- Client exports data locally.
- Client anonymizes samples for support if needed.
- Service helps configure and interpret outputs.
- Sensitive production files should stay in client-controlled environments unless a formal data agreement exists.

## 6. Support Subscription

Support can include:

- Installation help.
- Pack validation support.
- Mapping review.
- Priority bug triage.
- Release upgrade guidance.
- Security and deployment advice.

## 7. Training And Certification

Training can be paid without restricting the open-source core:

- Controller training.
- Auditor training.
- Odoo consultant training.
- SAP export reconciliation training.
- Rule-pack author training.

Certification should come after real community usage and stable schemas.

## 8. Partner Program For Odoo Consultants

Offer:

- Mapping templates.
- Implementation playbooks.
- Demo packs.
- Training.
- Co-maintained Odoo profile improvements.

Do not compete with OCA. ReconForge should complement Odoo implementations by auditing exports.

## 9. Partner Program For Auditors

Offer:

- Evidence pack methodology.
- Control-pack templates.
- Anonymized scenario library.
- Review checklists.
- Training for deterministic rule review.

## 10. SaaS Option Later, Not Now

SaaS may be useful later for collaboration and scheduled monitoring, but it would change the data trust model. The near-term category advantage is local-first and self-hosted. Do not weaken that wedge.

## 11. Pricing Hypotheses

These are hypotheses, not published prices:

- Implementation package: fixed-scope project fee.
- Support subscription: monthly or annual tier by response expectations.
- Training: per-seat or cohort fee.
- Self-hosted edition: annual subscription by environment or company size.
- Audit-pack service: fixed fee by pack and period.

Any public pricing should be simple and honest once service delivery is proven.

## 12. Buyer Personas

- Finance controller: wants faster close and fewer unexplained exceptions.
- Internal audit director: wants repeatable evidence and defensible controls.
- ERP consultant: wants a client-safe audit/reconciliation toolkit.
- Inventory or warehouse manager: wants stock movement exceptions explained.
- Workshop or manufacturing manager: wants WIP and work-order risk visibility.
- CFO: wants reduced close risk without exposing sensitive data.

## 13. Sales Channels

- GitHub and open-source adoption.
- Odoo consultant network.
- SAP consultant network.
- Accounting/audit LinkedIn content.
- Training workshops.
- Implementation partner referrals.
- Direct pilot outreach to mid-market finance teams.

## 14. Risk Analysis

| Risk | Mitigation |
| --- | --- |
| Commercial work starves open-source core | Keep roadmap and core feature boundary public. |
| Users expect enterprise close suite | Position as export-based audit intelligence, not full close platform. |
| Sensitive data exposure | Keep local-first posture and anonymization workflow central. |
| Unsupported ERP connector claims | Use "export-based" until direct connectors are implemented and tested. |
| Services become bespoke consulting only | Productize repeated mapping and evidence workflows. |
| Control packs produce false confidence | Document limitations and require reviewer judgment. |

## 15. Ethical Boundaries

- Do not imply audit sign-off is automated.
- Do not accept public live customer data.
- Do not sell private customer mappings as community packs without permission.
- Do not hide critical security issues.
- Do not make adoption claims without evidence.

## 16. What Must Remain Free

- Core CLI.
- Canonical schemas.
- Rule engine.
- Public control packs.
- Odoo/SAP export mapping profiles.
- Evidence binder baseline.
- Anonymizer.
- Synthetic data generator.
- Benchmark runner.
- Security and schema docs.

## 17. What Can Be Commercial Later

- Multi-user self-hosted review platform.
- Advanced role workflows.
- Branded handoff packs.
- Managed private control packs.
- Implementation services.
- Support subscription.
- Training and certification.
- Optional SaaS collaboration after local/self-hosted maturity.
