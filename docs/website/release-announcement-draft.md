# Release Announcement Draft

Draft announcement for ReconForge ERP v0.7.0 foundation-stage positioning. This is draft copy only; do not present it as a published release unless the release process is intentionally run.

## Title

ReconForge ERP v0.7.0 foundation-stage update: local finance controls, synthetic enterprise demo, buyer-readiness docs, and deployment smoke notes

## Draft Announcement

ReconForge ERP v0.7.0 continues the project's local-first, export-based direction for ERP reconciliation and finance controls review.

This foundation-stage update focuses on making local evaluation more complete and more honest. It includes broad DB-backed platform foundations, a synthetic enterprise demo package, conservative buyer, pilot, support, and release-readiness documentation, and deployment smoke check notes.

Highlights:

- local reconciliation and work-order control workflows from CSV/XLSX exports
- management packs, HTML reports, review registers, evidence binders, and client handoff packs
- local users/RBAC, audit events, workflow state machine, DB import/export, and backup foundations
- DB-backed foundations for accounts, close tasks, evidence registry, journal controls, intercompany, control testing, matching, unified exceptions, and metrics
- local REST API and Studio DB foundations for selected workflows
- synthetic enterprise demo for multi-entity platform walkthroughs without live customer data
- support playbook, pilot onboarding checklist, buyer FAQ, implementation package drafts, release readiness checklist, and expanded security questionnaire
- deployment smoke checklist and Docker verification commands for local release review

Run the demos:

```bash
reconforge demo run --output output/demo
reconforge demo enterprise --output output/enterprise_demo
```

Important boundaries:

- early-stage and pilot-ready for local evaluation
- local-first and export-based
- no hosted production service claim
- no direct ERP connector claim
- no audit opinion or compliance certification
- no legal signature or non-repudiation claim
- no customer adoption, revenue, testimonial, or ROI claim
- no vendor-replacement claim

## Suggested Closing

Feedback is welcome from finance controllers, internal audit reviewers, ERP consultants, and open-source maintainers. Please use synthetic or anonymized data in public issues.
