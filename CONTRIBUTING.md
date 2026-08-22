# Contributing to ReconForge ERP

Thank you for helping improve ReconForge ERP. Contributions are most useful when they strengthen real accounting controls, improve export mapping, add tests, make generated outputs safer, or clarify docs for finance, stores, workshop, ERP, and audit users.

ReconForge ERP is early-stage, local-first, and export-based. Keep contributions focused and conservative.

For AI coding agents, also read [AGENTS.md](AGENTS.md).

## Development Setup

Use Python 3.11 or 3.12 and the exact `uv` version declared in
`pyproject.toml`. Install `uv` through the checksum-verified procedure in the
[supply-chain policy](docs/security/supply-chain-policy.md), then synchronize
the reviewed universal lock:

```bash
uv sync --locked --all-extras --no-editable --python 3.12
uv run --no-sync pre-commit install
```

If the installed `reconforge` command appears stale after a CLI or version change:

```bash
uv sync --locked --all-extras --no-editable --python 3.12 --refresh-package reconforge-erp
uv run --no-sync python -m reconforge.cli doctor
```

## Quality Commands

Run these before opening a pull request:

```bash
uv run --no-sync ruff check .
uv run --no-sync mypy reconforge
uv run --no-sync pytest
```

For report, mapping, rule-pack, or CLI changes, also run relevant smoke commands:

```bash
reconforge validate examples/sample_data
reconforge rules validate --pack control-packs/audit-basic
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge report client-pack --input output --output output/client_pack --summary-only
```

## Security Commands

```bash
uv run --no-sync bandit -q -r reconforge
python .github/scripts/run_locked_python_audit.py --project-root .
npm --prefix apps/web audit --package-lock-only --audit-level=high
```

The Python audit runner verifies the exact `uv` version, the closed policy, and
`uv.lock`; exports every optional profile with hashes; and uses a temporary
isolated Python 3.12 environment by default. It does not trust or repair the
project `.venv`. Do not replace it with an ambient environment audit, floating
scanner, or broad finding baseline.

Security-sensitive changes include path handling, generated HTML, href values, YAML parsing, Studio routes, report output, evidence binder output, client packs, redaction, dependency workflows, and any code that handles user-controlled files.

## Coding Standards

- Use supported Python 3.11 or 3.12 with type hints.
- Keep reconciliation logic deterministic and explainable.
- Prefer schema-driven validation over hidden assumptions.
- Keep core functionality local-first.
- Do not add paid API dependencies, cloud upload, SaaS flows, telemetry, or live ERP credential handling for core workflows.
- Keep generated evidence and reports auditable.
- Avoid committing generated outputs unless they are intentionally small documentation examples.

## How To Add A Control Pack

Control packs live under `control-packs/<pack-name>/` and should include:

- `pack.yml`
- `rules.yml`
- `mapping.yml`
- `risk_model.yml` when risk scoring is used
- `README.md`
- `expected-exceptions.md`
- `sample-command.md`

Good control packs:

- explain the business risk in plain English
- use supported rule operators only
- preserve source-document traceability
- include expected exceptions and review guidance
- validate with synthetic or anonymized data

## How To Add An ERP Export Profile

ReconForge supports export-based profiles, not live or direct ERP connectors.

An ERP export profile should:

- name the ERP export/report source
- list required CSV/XLSX files
- map source fields into canonical ReconForge files
- include sanitized headers or synthetic examples only
- validate with `reconforge mappings validate --pack <path>`
- avoid vendor certification, live sync, or direct connector claims

Useful profile issue reports include sanitized headers, expected canonical files, and the reconciliation workflow the profile should support.

## How To Add Tests

Add tests when you change:

- reconciliation matching or exception classification
- risk scoring or rule evaluation
- mapping validation or profile behavior
- generated HTML, Markdown, Excel, CSV, JSON, or evidence output
- Studio routes or review workflow behavior
- safe path handling, redaction, or client packs

Use synthetic or anonymized fixtures only. Tests should cover successful behavior and at least one failure or edge case when practical.

## Documentation Expectations

Update docs when a user-facing command, workflow, schema, rule pack, profile, report, or security behavior changes.

- README should stay concise.
- `docs/index.md` should link important new docs.
- Security docs should be updated for file handling, generated output, redaction, evidence, and workflow changes.
- Release docs should be updated when release behavior or validation changes.

## Claim Boundaries

Do not claim:

- real customers, adoption, testimonials, or production usage unless documented
- audit opinions, audit sign-off, or assurance conclusions
- legal, tax, regulatory, or compliance certification
- direct ERP connectors or vendor-certified integrations
- enterprise production readiness
- signed artifacts unless signing is implemented
- Docker runtime verification unless the documented build and run commands pass

Preferred wording includes "local-first", "export-based", "early-stage", "pilot-ready open-source toolkit", "evidence preparation", and "integrity aid".

## Pull Request Checklist

- [ ] Scope is focused and clearly described.
- [ ] Tests cover new behavior or regressions.
- [ ] Quality commands pass.
- [ ] Security commands pass when relevant.
- [ ] Docs are updated for changed commands, schemas, reports, workflows, or claims.
- [ ] No live customer, supplier, employee, vehicle, asset, invoice, GL, or financial data is included.
- [ ] Local-first behavior is preserved.
- [ ] Generated HTML escapes user-controlled values and URL-quotes href path segments.
- [ ] User-controlled paths cannot traverse outside intended input/output locations.
- [ ] YAML parsing remains safe.

## Good First Contribution Examples

- Add missing CLI examples to a rule-pack README.
- Add sanitized header examples to an export profile doc.
- Improve glossary wording for finance/audit terms.
- Add a focused test for a mapping validation edge case.
- Improve a client-pack privacy checklist.
- Review docs for direct connector or compliance overclaims.

See [docs/maintainers/suggested-issues.md](docs/maintainers/suggested-issues.md) for ready-to-copy issue ideas.

## Reporting Mapping Or Profile Issues

Use the ERP mapping profile issue template. Include:

- ERP name and export/report source
- CSV/XLSX file names
- sanitized column headers
- expected canonical ReconForge files
- command attempted
- expected and actual behavior

Do not attach live ERP data or screenshots containing private identifiers.

## Submitting Anonymized Scenarios Safely

Before sharing a scenario:

- remove or mask customer, supplier, employee, vehicle, asset, invoice, GL, and financial identifiers
- check hidden workbook sheets
- keep row samples small
- explain the expected exception in plain English
- use GitHub Issues or Discussions only for data that is safe to publish

The built-in anonymizer can help preserve referential integrity:

```bash
reconforge anonymize --input examples/sample_data --output examples/anonymized_data --seed 42 --date-shift-days 30
```

## AI-Assisted Contributions

AI-generated PRs are welcome only when:

- tests pass
- claims are verified
- security rules are followed
- generated content is reviewed by a human
- no private client or ERP data is included

AI tools should not invent adoption, customer proof, compliance claims, direct ERP integrations, or Docker/runtime evidence. Human maintainers remain responsible for review and merge decisions.
