# Deployment Smoke Check

Use this checklist to verify a local ReconForge ERP checkout before a foundation-stage release, demo rehearsal, or pilot evaluation. These checks are local-first and export-based. They do not create a hosted production service, direct ERP connector, audit opinion, legal signature, compliance certification, customer traction claim, ROI claim, or platform replacement claim.

## Quality And Security Gates

Run from the repository root:

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
uv lock --check
python .github/scripts/validate_supply_chain_policy.py
python -m reconforge.cli doctor
git diff --check
```

Hash-locked dependency audit (the temporary files are evidence inputs and must
not be committed):

```bash
uv export --locked --all-extras --no-emit-project --format requirements.txt --output-file audit-requirements.txt
pip-audit --require-hashes --disable-pip -r audit-requirements.txt --format json --output pip-audit.json
python .github/scripts/validate_supply_chain_policy.py --pip-audit-report pip-audit.json --pip-audit-exit-code 0
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
docker build --pull --no-cache --platform linux/amd64 -t reconforge-erp .
```

Run doctor:

```bash
docker run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges reconforge-erp reconforge doctor
```

Run a bounded demo smoke with ephemeral output:

```bash
docker run --rm --network=none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0700 \
  --tmpfs /app/output:rw,noexec,nosuid,size=256m,uid=10001,gid=10001,mode=0700 \
  reconforge-erp reconforge demo run --output output/demo
```

For retained artifacts, use a narrowly scoped host directory or managed volume
instead of the tmpfs mount, review ownership for UID/GID `10001:10001`, and
record that the retained-output run has a different write boundary. Do not claim Docker runtime verification unless these commands pass in the environment being described.

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
