# Contributing to ReconForge ERP

Thank you for helping improve an open-source ERP reconciliation and audit intelligence platform. Contributions are most useful when they strengthen real accounting controls, improve data mapping, add tests, or make reports clearer for finance, stores, workshop, and audit teams.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Quality Checks

Run these before opening a pull request:

```bash
ruff check .
mypy reconforge
pytest
```

For report or CLI changes, also run:

```bash
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
```

## Coding Standards

- Use Python 3.11+ with type hints.
- Keep reconciliation logic deterministic and explainable.
- Prefer schema-driven validation over hidden assumptions.
- Keep core functionality local-first.
- Do not add paid API dependencies for core workflows.
- Keep generated evidence and reports auditable.
- Avoid committing generated outputs unless they are intentionally small documentation examples.

## Domain Standards

- Controls should name the business risk clearly.
- Rule packs should include expected inputs, common exceptions, and recommended workflow.
- Tests should cover both successful matches and exception classification.
- Sample data must be synthetic or anonymized.
- New ERP mappings should preserve source-document traceability.

## Branch Naming

- `feature/rule-pack-fleet-repeated-repairs`
- `fix/gl-date-proximity-match`
- `docs/sap-export-playbook`
- `test/anonymizer-reference-integrity`

## Pull Request Checklist

- Scope is focused and clearly described.
- Tests cover new behavior.
- Documentation is updated for changed commands, schemas, or methodology.
- No live customer, supplier, employee, vehicle, asset, or financial data is included.
- Security impact has been considered for file handling and generated outputs.
- New dependencies are justified and compatible with local-first usage.

## Adding Rule Packs

Each rule pack should include:

- `pack.yml`
- `rules.yml`
- `mapping.yml`
- `README.md`
- `expected-exceptions.md`

Rules should be practical, explainable, and testable against synthetic or anonymized data.

## Adding ERP Connectors

New connectors should map source ERP fields into the canonical ReconForge schema first. Keep connector logic separate from reconciliation logic so controls remain consistent across Odoo, SAP exports, ERPNext, NetSuite, and generic CSV workflows.
