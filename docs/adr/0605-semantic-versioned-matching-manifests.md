# ADR 0605: Require semantic versions for matching manifests

## Status

Accepted — 2026-08-23

## Decision

Matching strategy manifests accept only strict `MAJOR.MINOR.PATCH` semantic
versions with no leading zero components. The version is part of the registry
identity and digest, so malformed versions cannot enter replay or migration
boundaries.

## Boundary

This validates version syntax and identity stability. It does not prove
semantic compatibility between releases or replace a migration/deprecation
policy.

## Rollback

Relaxation requires a versioned contract migration and compatibility tests;
silently admitting opaque version strings is not an allowed rollback.
