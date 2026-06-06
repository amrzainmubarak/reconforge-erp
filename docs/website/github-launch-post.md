# GitHub Launch Post Draft

Draft open-source launch/update post. Keep the tone practical and avoid unsupported claims.

## Title

ReconForge ERP: local-first ERP reconciliation and finance controls from exports

## Post

I am sharing ReconForge ERP, an open-source toolkit for local-first, export-based ERP reconciliation and finance controls review.

The project is aimed at finance controllers, internal audit teams, ERP consultants, and maintainers who need a transparent way to inspect stock-to-GL differences, WIP/work-order controls, rule-pack findings, evidence folders, review state, and local handoff artifacts from CSV/XLSX exports.

Current scope includes:

- stock-to-GL and work-order reconciliation workflows
- rule packs and mapping validation
- management packs, HTML reports, review registers, and evidence binders
- anonymization and synthetic data generation
- synthetic enterprise demo package for platform-foundation walkthroughs
- foundation-stage local SQLite services for accounts, close tasks, evidence, journals, intercompany, controls, matching, exceptions, metrics, API routes, and Studio DB pages
- buyer, pilot, support, and release-readiness docs for honest evaluation

The project is intentionally conservative about claims:

- local-first and export-based
- no direct ERP connectors
- no SaaS hosting
- no audit opinion
- no compliance certification
- no legal signature workflow
- no customer adoption or ROI claims
- not a replacement for ERP, audit, GRC, or enterprise close platforms

Try the demos:

```bash
reconforge demo run --output output/demo
reconforge demo enterprise --output output/enterprise_demo
```

Contributions that would help:

- better synthetic scenarios
- export-profile improvements
- rule-pack tests
- docs feedback from controllers, auditors, and ERP consultants
- issue reports using synthetic or anonymized data only

Repository: `https://github.com/<owner>/<repo>`

## Maintainer Note

Replace the repository URL placeholder before posting. Do not add logos, customer names, screenshots from private data, savings claims, certification claims, or enterprise-readiness wording.
