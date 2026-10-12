# ADR 0733: Checksum-Bound Alpine Security APKs

- **Date**: 2026-08-28
- **Status**: Accepted
- **Context**: The digest-pinned `python:3.11-alpine` base image retained
  `libcrypto3/libssl3` at `3.5.7-r0`, while the reviewed fixed `3.5.8-r0`
  artifacts were available from Alpine but were not selected by the current
  repository index. An index-only `apk add package=version` therefore made a
  security-pinned build fail closed during ordinary mirror lag.
- **Decision**: Fetch the exact `linux/amd64` Alpine APK artifacts with
  BuildKit `ADD --checksum`, install those local files in both Docker stages,
  and remove the temporary artifacts in the same layer. Keep Alpine package
  signature verification through `apk`, retain the digest-pinned base image,
  and do not add the OpenSSL CLI.
- **Verification**: The current source builds successfully with
  `docker build --pull --no-cache --platform linux/amd64`; a hardened
  networkless non-root smoke test reports `libcrypto3/libssl3 3.5.8-r0`,
  confirms the OpenSSL CLI is absent, and `reconforge doctor` exits zero.
- **Compatibility**: The supported container build remains explicitly
  `linux/amd64`; Python packaging and application behavior are unchanged.
- **Rollback**: Revert E-1073 Dockerfile/tests and this ADR together only if
  an approved replacement keeps exact package identity and checksum-bound
  retrieval. Do not revert to an unbounded version lookup.
