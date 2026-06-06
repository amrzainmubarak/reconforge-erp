# Roadmap

ReconForge ERP is a local-first, export-based ERP reconciliation and finance controls toolkit. The roadmap should deepen implemented foundations without implying SaaS behavior, direct ERP connectivity, compliance certification, audit opinions, or production identity readiness.

## Completed Foundations

- P0 Enterprise Backbone: completed as a foundation-stage local platform layer covering the SQLite DB, audit events, local users/RBAC, workflow state machine, REST API, Studio auth-required mode, DB import/export, backup bridge, security docs, and roadmap docs.
- Broad finance workflow foundations: completed as foundation-stage DB-backed records and services for account reconciliations, close management, approvals/certification metadata, evidence registry, journal controls, intercompany, controls testing, matching, unified exceptions, and metrics.
- Studio DB pages and API routes: completed for the current foundation scope, including local Studio pages and implemented API routes for accounts, close, exceptions, and metrics.
- Export-based ERP profile coverage: completed for Odoo, SAP, ERPNext, Dynamics, NetSuite, and Oracle mapping profiles without direct connector claims.
- Pilot readiness hardening: completed for local demo, synthetic enterprise demo, client pack, redaction, checksum manifests, Docker build workflow, conservative security/commercial documentation, support playbook, buyer FAQ, pilot onboarding checklist, draft implementation packages, release readiness checklist, and conservative website/launch copy drafts.

## Next Phase

- Deeper workflow depth for account reconciliation, close management, approvals metadata, evidence registry, journal controls, intercompany, controls testing, matching, unified exceptions, and metrics.
- Richer Studio actions for implemented DB-backed workflows, with local RBAC checks where authenticated local users are present.
- Website refresh implementation using conservative launch copy that presents current foundations accurately and avoids replacement, compliance, or assurance claims.
- Deployment smoke automation for Docker build/run checks before runtime verification is described as complete.
- Observability depth for local audit events, diagnostics, operational health checks, and supportable troubleshooting.

## Future Design Work

- Real SSO/OIDC/SAML and SCIM remain optional future work after design review, threat modeling, and local-first boundary review.
- Direct ERP connectors remain future/design work only. Current profiles are export-based mapping aids, not live ERP integrations.
- Connector SDK ideas should remain separate from core workflows unless security, credential handling, test coverage, and docs are ready.
- Optional packaged desktop or self-hosted distribution can be explored after local workflow, deployment, and security boundaries mature.

## Product Guardrails

- Keep core reconciliation local-first and export-based.
- Avoid fake adoption, production readiness, compliance, legal, audit opinion, and vendor-replacement claims.
- Keep controls explainable, deterministic, and testable.
- Keep generated data synthetic or anonymized.
- Prioritize practical finance control depth over broad claims.
