# Release Readiness Checklist

Use this checklist before proposing or publishing a ReconForge ERP release. Keep release notes factual, local-first, export-based, and tied to commands that actually passed.

## Quality Gates

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
python -m reconforge.cli doctor
git diff --check
```

Record command output summaries in the release notes or maintainer handoff. Do not mark a gate complete if it was skipped.

## Security Checks

```bash
python -m bandit -q -r reconforge
pip-audit -r requirements.txt
```

Also check:

- CodeQL workflow status when available.
- OpenSSF Scorecard status when available.
- Dependency lock/update notes.
- Any change touching file handling, generated HTML, YAML loading, downloads, Studio routes, evidence output, client packs, DB import/export, backup, or mapping validation has targeted tests.

## Documentation Checks

- README project status matches the version being released.
- `docs/index.md` links important new docs.
- Security docs match implemented behavior.
- Demo docs use synthetic or anonymized data only.
- Release docs and changelog are updated.
- CLI examples still work or are clearly marked as examples.
- No docs ask users to share live customer data in public channels.

## Deployment Smoke Checks

Run the local demo and platform-foundation smoke commands before publishing a foundation-stage release note:

```bash
reconforge demo run --output output/demo
reconforge demo enterprise --output output/enterprise_demo
reconforge db init --db output/reconforge.db
reconforge api serve --db output/reconforge.db --host 127.0.0.1 --port 8765
reconforge studio --input examples/sample_data --output output/demo
reconforge studio --input examples/sample_data --output output/demo --db output/reconforge.db --require-auth
```

The API and Studio commands are local long-running server checks. Start them, confirm local startup, and stop them before continuing.

## Claim-Boundary Checks

Before release, search docs, README, changelog, and release notes for unsupported claims:

- no enterprise-ready claim
- no production-ready claim
- no compliance certification claim
- no audit opinion claim
- no legal signature claim
- no direct connector claim
- no real customer, ROI, testimonial, logo, adoption, or revenue claim
- no production SaaS claim
- no vendor-replacement or feature-parity claim against enterprise close, GRC, ERP, or audit platforms

Preferred wording:

- "pilot-ready open-source toolkit"
- "local-first and export-based"
- "supports local evidence preparation"
- "helps review export-based reconciliation workflows"
- "provides checksum integrity aids"
- "foundation-stage DB-backed workflows"

## Docker Build And Runtime Verification

Docker build support and Docker runtime verification are separate claims.

Before claiming Docker runtime verification, run in a live Docker environment:

```bash
docker build -t reconforge-erp .
docker run --rm reconforge-erp reconforge doctor
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

If Docker is unavailable or any command fails, document the limitation and do not claim runtime verification.

## SBOM And Release Artifacts

- Confirm dependency files are intentional.
- Confirm SBOM workflow status when available.
- Do not commit generated demo output, evidence packs, local DBs, backups, or binaries unless intentionally reviewed as a small documentation artifact.
- Verify generated release artifacts do not contain secrets, live customer data, local usernames, private paths, or source exports.

## Version Bump Checklist

- `pyproject.toml`
- `reconforge/__init__.py` if versioned there
- README project status
- docs index release status
- changelog
- release notes under `docs/releases/` when applicable
- Docker docs only when runtime verification actually passed

## Release Notes Checklist

- Summarize implemented behavior only.
- Include local-first/export-based boundaries.
- Mention quality and security gates that passed.
- Mention skipped gates clearly.
- Mention known limitations.
- Avoid adoption, ROI, certification, audit-opinion, direct-connector, SaaS, and vendor-replacement claims.

## Blockers Before Stronger Readiness Claims

Do not call a release enterprise-ready unless there is documented evidence for:

- production deployment model and hardening guidance
- mature identity and access controls for the claimed deployment mode
- support policy and operational ownership
- release provenance and dependency posture
- tested backup/restore and upgrade procedures
- Docker/runtime verification or equivalent deployment verification
- real pilot feedback with approved public wording, if any customer proof is referenced
- legal review for any compliance, assurance, or certification wording

Until then, keep wording at "pilot-ready", "early-stage", "local-first", and "export-based".
