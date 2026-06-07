# Docker Verification

This page summarizes Docker verification commands for ReconForge ERP foundation-stage releases. Docker runtime verification depends on local Docker availability. If Docker Desktop, Docker Engine, or CI Docker support is unavailable, document that limitation and do not claim runtime verification.

## Build

```bash
docker build -t reconforge-erp .
```

## Run Doctor

```bash
docker run --rm reconforge-erp reconforge doctor
```

## Run Demo

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

## What To Record

- Docker version.
- Host operating system.
- Command output summaries.
- Whether the generated `output/demo` folder was created.
- Any Docker daemon, mount, permission, or networking issue.

## Claim Boundary

Passing these commands supports a Docker runtime verification note for the tested environment only. It does not imply hosted production service readiness, enterprise deployment readiness, compliance certification, audit opinion support, legal signature support, direct ERP connector behavior, customer adoption, ROI, or platform replacement.

See also:

- [Docker deployment](docker-deployment.md)
- [Deployment smoke check](deployment-smoke-check.md)
- [Historical Docker verification report](strategy/docker-verification-report.md)
