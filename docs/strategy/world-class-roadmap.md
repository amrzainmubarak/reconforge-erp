# World-Class Roadmap

This roadmap translates global finance, reconciliation, close, audit, and GRC capability patterns into original ReconForge-native work. It preserves the local-first, export-based, open-source model and avoids SaaS, direct ERP credentials, vendor endorsement, audit-opinion claims, and compliance-certification claims.

## v0.7.0 - Public Demo and Deployment Trust

Focus: prove that ReconForge can be evaluated safely and repeatably by public users, consultants, maintainers, and pilot teams.

Planned scope:

- Docker runtime verification with documented build/run commands before any runtime claim.
- Demo video assets, refreshed screenshots, and reproducible sample outputs.
- GitHub Pages/static landing page publishing docs.
- Release artifact integrity plan with checksum guidance.
- Reviewed demo output pack with privacy notes.
- Public pilot checklist for local evaluations.
- Close checklist foundation.
- Variance analysis foundation.
- Control matrix export foundation.
- Certification metadata in local review exports.
- KPI dashboard improvements from local artifacts.

Exit criteria:

- `python -m ruff check .`, `python -m mypy reconforge`, `python -m pytest`, `python -m bandit -q -r reconforge`, `python -m reconforge.cli doctor`, and `git diff --check` pass.
- Docker runtime verification is either completed and documented or explicitly not claimed.
- Public docs state local-first, export-based, no audit opinion, no legal/tax/compliance advice, no cloud upload, and no direct connectors.

## v0.8.0 - Close and Control Workflow Foundation

Focus: give controllers and consultants a practical month-end workflow layer while staying file-based.

Planned scope:

- Monthly close calendar generated from a local template.
- Task ownership in local JSON state.
- Reconciliation certification workflow with preparer/reviewer fields, no full RBAC.
- Review sign-off metadata clearly framed as workflow metadata only.
- Period close readiness report.
- Journal entry control checks from GL exports.
- Variance analysis expansion with materiality profiles and explanation fields.
- Close checklist dependencies if they can be represented safely in local files.

Not in scope:

- Web authentication.
- Email notifications.
- ERP journal posting.
- Legal signatures.
- Audit assurance conclusions.

Exit criteria:

- Close state schema documented and backward compatible.
- CLI and report tests cover malformed close state, invalid statuses, HTML escaping, and missing files.
- Management pack and client pack include clear workflow-boundary wording.

## v0.9.0 - Advanced Audit Intelligence

Focus: deepen repeatable control insight without hiding decisions in opaque automation.

Planned scope:

- Control testing workflows from rule packs.
- Risk/control matrix with test procedures and evidence references.
- Recurring exception aging by comparison key and status.
- Intercompany/export reconciliation foundation.
- Explainable anomaly scoring from local exports.
- Explainable matching confidence reports.
- Richer management KPIs for control health, evidence coverage, review completion, accepted risk, and recurring issues.
- Audit trail hardening with append-only local activity logs and checksums.
- Stronger evidence integrity and optional signing plan, clearly separated from legal digital signature claims.

Not in scope:

- Black-box AI approvals.
- Direct ERP connector runtime.
- Compliance certification.
- Multi-tenant user management.

Exit criteria:

- Deterministic anomaly/matching explanations.
- Security tests for file handling, HTML escaping, local logs, and evidence output.
- Documentation explains limitations and user responsibilities.

## v1.0.0 - Stable Pilot Baseline

Focus: establish a stable early pilot baseline without overstating enterprise readiness.

Planned scope:

- Stable CLI contracts and file output contracts.
- Strong docs for installation, demos, mapping, controls, review workflow, evidence, security, redaction, and release verification.
- Expanded sample datasets and anonymized fixtures.
- Deployment verification with documented results.
- Pilot feedback loop and issue triage process.
- Security posture review and dependency audit.
- Conservative public messaging: pilot-ready open-source toolkit, early-stage, export-based, local-first.

Not in scope:

- Fake customers, adoption, revenue, savings, audit opinions, or certification claims.
- Direct ERP connectors unless separately implemented and tested.
- Enterprise production-readiness claims.

Exit criteria:

- Full quality and security gates pass.
- Release process checklist is followed.
- Changelog, release notes, README, docs index, and version metadata are aligned.
- Known limitations are visible and specific.
