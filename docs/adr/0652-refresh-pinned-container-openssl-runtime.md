# ADR 0652: Refresh pinned container OpenSSL runtime libraries

- **Status:** Accepted for the bounded remediation slice
- **Date:** 2026-08-26
- **Scope:** E-959 / E-824 container security remediation

## Context

The reviewed official Python 3.11 Alpine index is digest-pinned in both
Docker stages. Its embedded Alpine packages were `libcrypto3` and `libssl3`
`3.5.7-r0`, while the supported Alpine repository exposed `3.5.8-r0`. A base
digest replacement was not available with independently verified current
image evidence. The release gate must not be made green by a broad ignore,
severity reduction, or unreviewed VEX statement.

## Decision

Keep the existing official Python digest and refresh only the two named
OpenSSL runtime libraries in both the builder and runtime stages:

```dockerfile
RUN apk add --no-cache --upgrade \
    libcrypto3=3.5.8-r0 \
    libssl3=3.5.8-r0
```

The OpenSSL CLI is intentionally not installed in the trimmed runtime. E-824
remains open until the exact Syft/Grype database, license, and hosted clean
build gates pass against the rebuilt image.

## Evidence and boundary

The local `reconforge:e824-openssl` linux/amd64 build completed. Runtime
inspection reported `libcrypto3-3.5.8-r0` and `libssl3-3.5.8-r0`; the hardened
Doctor smoke and Dockerfile regression test passed. Syft 1.51.0 emitted a
native SBOM after checksum verification. The Grype 0.117.0 database refresh
could not complete in the current container network/certificate environment,
so this ADR does not claim that the vulnerability gate passed or that the
image is releaseable.

## Rollback

Revert the two package-refresh instructions. This restores the previous
runtime construction and reopens the OpenSSL finding; it does not authorize a
VEX exception or severity override.
