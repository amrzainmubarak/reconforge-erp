# Release Process

Use this checklist for ReconForge ERP releases. Keep release claims factual, local-first, and tied to commands that actually passed.

## Pre-Release Checklist

- Confirm the working tree is clean except for intended release changes.
- Review open security issues and release blockers.
- Confirm no generated output or live ERP data is staged unintentionally.
- Check README, docs, and CLI help for stale commands.
- Confirm Docker claims match observed Docker build/run results.

## Version Bump Checklist

- Update `pyproject.toml`.
- Update `reconforge/__init__.py` if it stores the package version.
- Update README project status.
- Update `docs/index.md` if the release name changes there.
- Update release notes under `docs/releases/` when appropriate.

## Changelog Checklist

- Add a concise entry to `CHANGELOG.md`.
- Separate user-facing changes from maintainer/security/docs changes.
- Note known limitations honestly.
- Do not claim adoption, certification, customer usage, or production readiness.

## Documentation Consistency Checklist

- README status, capabilities, and limitations are current.
- `SECURITY.md` and `docs/security-whitepaper.md` reflect workflow changes.
- `docs/docker-deployment.md` and Docker verification notes are aligned.
- `CONTRIBUTING.md`, `AGENTS.md`, and `.github/copilot-instructions.md` remain consistent.
- New maintainer docs are linked from README, CONTRIBUTING, or `docs/index.md`.

## Test Commands

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m reconforge.cli doctor
```

Recommended smoke commands:

```bash
reconforge demo run --output output/demo
reconforge report client-pack --input output/demo --output output/demo/client_pack --summary-only
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
reconforge mappings validate --pack control-packs/erpnext-stock-gl
reconforge mappings validate --pack control-packs/dynamics-inventory-gl
reconforge mappings validate --pack control-packs/netsuite-inventory-gl
```

## Security Commands

```bash
python -m bandit -q -r reconforge
pip-audit -r requirements.txt
```

Review OpenSSF Scorecard and SBOM workflow runs when available. They support security maturity review but are not guarantees.

## Docker Checks

Only claim Docker runtime verification after these commands pass in a live Docker environment:

```bash
docker build -t reconforge-erp .
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

If Docker is unavailable locally, document that limitation instead of claiming verification.

## Release Notes Template

```markdown
# ReconForge ERP vX.Y.Z - Release Name

## Summary

One short paragraph describing the release scope.

## Added

- 

## Changed

- 

## Fixed

- 

## Security And Supply Chain

- 

## Validation

- `python -m ruff check .`
- `python -m mypy reconforge`
- `python -m pytest`
- `python -m bandit -q -r reconforge`
- `python -m reconforge.cli doctor`

## Known Limitations

- 
```

## Post-Release Checklist

- Confirm the release tag and GitHub release notes are correct.
- Confirm CI/security workflows pass on the release commit or tag.
- Confirm SBOM artifact generation when applicable.
- Update docs or issue templates if new feedback channels are needed.
- Add follow-up issues for deferred release risks.

## Stale Installed Console Scripts

If `reconforge` reports an old version or missing command after a release:

```bash
python -m pip uninstall reconforge-erp
python -m pip install -e ".[dev]"
python -m reconforge.cli doctor
```

Prefer `python -m reconforge.cli ...` for sanity checks when diagnosing stale entry points.

## Patch vs Minor Release

Choose a patch release for:

- bug fixes
- docs corrections
- security hardening without new user workflow scope
- test and workflow fixes

Choose a minor release for:

- new rule packs
- new export profiles
- new commands or report outputs
- meaningful workflow changes

## When Not To Release

Do not release when:

- tests or core smoke commands fail
- docs imply unverified claims
- Docker runtime is claimed but not verified
- sample data may contain private information
- a security issue is unresolved and release notes would expose exploit details
