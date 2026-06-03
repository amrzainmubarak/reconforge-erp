# Maintainer Guide

## Architecture

ReconForge ERP separates responsibilities:

- `reconforge/io`: CSV, XLSX, JSON, and Excel workbook helpers
- `reconforge/validators.py`: schema, type, duplicate, amount, and reference checks
- `reconforge/reconciliation`: matching and control engines
- `reconforge/reports`: WIP, Markdown, HTML, and management pack outputs
- `reconforge/dashboard`: local FastAPI dashboard
- `reconforge/cli.py`: Typer command surface

## Adding a Control

1. Add the pure control function in the relevant reconciliation module.
2. Add risk scoring support when a new exception type is introduced.
3. Include the frame in result dataclasses and report writers.
4. Add tests for positive and negative cases.
5. Update docs and README when the control is user-facing.

## Adding a New ERP Mapping

Connector work should map source ERP fields into the canonical ReconForge files. Keep source-specific parsing separate from matching logic so the same controls work across ERP systems.

## Release Checks

```bash
ruff check .
mypy reconforge
pytest
python -m build
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
```

## Repository Settings

Review [repository settings](maintainers/repository-settings.md) after workflow, branch protection, security policy, or Scorecard changes. Some settings, including required reviews and default workflow token permissions, must be enforced in GitHub rather than in tracked source files.

Use [Scorecard alert triage](maintainers/scorecard-alert-triage.md) to separate source-file fixes from GitHub settings, project-history, and OpenSSF Best Practices badge actions.

## Data Governance

Never commit live ERP data. Keep sample data synthetic and useful enough to exercise the control logic.
