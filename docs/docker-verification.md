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

The image runs as fixed UID/GID `10001:10001`. A bind-mounted output directory
must grant that identity write access, or the operator must deliberately map a
host identity after evaluating local ownership requirements. Do not restore a
root container default to work around a host-permission error.

## Hardened local smoke profile

The CLI can be verified without network access and with a read-only root. The
only writable locations in this profile are bounded in-memory mounts:

```bash
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0700 \
  --tmpfs /app/output:rw,noexec,nosuid,size=64m,uid=10001,gid=10001,mode=0700 \
  reconforge-erp reconforge doctor

docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0700 \
  --tmpfs /app/output:rw,noexec,nosuid,size=256m,uid=10001,gid=10001,mode=0700 \
  reconforge-erp reconforge demo run --output output/demo
```

The tmpfs demo proves execution but intentionally does not retain artifacts.
Use a narrowly scoped, correctly permissioned host directory or managed volume
when retained evidence is required.

## Current local result (E-822)

On 2026-08-22, Docker Desktop 4.87.0/Linux engine 29.7.2 built the current
two-stage image and passed identity, runtime-content, Doctor, sample-validation,
audit-basic control-pack, and complete-demo checks. The measured final build
context was 216.25 KB and the Python 3.11 Alpine image was 58,773,988 bytes;
runtime UID/GID was 10001. Docker Scout 1.24.0 indexed 82 packages and reported
zero findings at all severities. This result is bounded to that host, revision,
and scanner database time.

## What To Record

- Docker version.
- Host operating system.
- Command output summaries.
- Whether the generated `output/demo` folder was created.
- Any Docker daemon, mount, permission, or networking issue.
- Runtime UID/GID and whether the root filesystem/network were restricted.
- Build-context bytes, exact image ID/digest, and image size.

## Claim Boundary

Passing these commands supports a Docker runtime verification note for the tested environment only. It does not imply hosted production service readiness, enterprise deployment readiness, compliance certification, audit opinion support, legal signature support, direct ERP connector behavior, customer adoption, ROI, or platform replacement.

See also:

- [Docker deployment](docker-deployment.md)
- [Deployment smoke check](deployment-smoke-check.md)
- [Historical Docker verification report](strategy/docker-verification-report.md)
