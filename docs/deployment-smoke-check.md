# Deployment Smoke Check

Use this checklist to verify a local ReconForge ERP checkout before a foundation-stage release, demo rehearsal, or pilot evaluation. These checks are local-first and export-based. They do not create a hosted production service, direct ERP connector, audit opinion, legal signature, compliance certification, customer traction claim, ROI claim, or platform replacement claim.

## Quality And Security Gates

Run from the repository root:

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
python -m reconforge.cli doctor
git diff --check
```

Optional dependency audit:

```bash
python -m pip_audit -r requirements.txt
```

If your environment exposes `pip-audit` as a command instead of a module, use:

```bash
pip-audit -r requirements.txt
```

## Demo Smoke Checks

Run the standard demo:

```bash
reconforge demo run --output output/demo
```

Run the synthetic enterprise demo:

```bash
reconforge demo enterprise --output output/enterprise_demo
```

Review generated outputs locally. Do not commit generated demo folders unless a small artifact is intentionally reviewed for documentation.

## Local DB Smoke Check

Initialize a local SQLite database:

```bash
reconforge db init --db output/reconforge.db
```

This validates the local migration runner against a local file. It does not add a new schema or migration.

## Local API Smoke Check

Start the local API:

```bash
reconforge api serve --db output/reconforge.db --host 127.0.0.1 --port 8765
```

Expected result:

- The command starts a local server on `http://127.0.0.1:8765`.
- Stop it after confirming startup.
- Do not bind to public interfaces during release smoke checks.

## Local Studio Smoke Check

Start Studio without auth-required mode:

```bash
reconforge studio --input examples/sample_data --output output/demo
```

Start Studio with auth-required mode:

```bash
reconforge studio --input examples/sample_data --output output/demo --db output/reconforge.db --require-auth
```

Expected result:

- The command starts a local Studio server.
- The auth-required command uses the local DB path.
- Stop each server after confirming startup.
- These commands do not imply production identity readiness or hosted deployment support.

## Docker Smoke Checks

Docker runtime verification depends on Docker Desktop, Docker Engine, or CI Docker support being available.

Build:

```bash
docker build -t reconforge-erp .
```

Run doctor:

```bash
docker run --rm reconforge-erp reconforge doctor
```

Run demo with a mounted output folder:

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

Do not claim Docker runtime verification unless these commands pass in the environment being described.

## Release Claim Checklist

Before publishing release notes, confirm the release copy includes:

- no enterprise-ready claim
- no compliance certification claim
- no audit opinion claim
- no legal signature claim
- no direct connector claim
- no real customer, ROI, or testimonial claim
- no production SaaS claim

Preferred wording:

- foundation-stage
- local-first
- export-based
- pilot evaluation
- self-hosted/local-capable foundations
- finance controls platform foundations
- synthetic enterprise demo
