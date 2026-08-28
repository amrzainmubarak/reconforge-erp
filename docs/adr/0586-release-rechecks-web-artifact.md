# ADR 0586: Release workflow rechecks the web artifact

## Status

Accepted — 2026-08-23

## Context

The signed-tag release workflow audited the npm lock but could build and publish
the Python release without executing the web typecheck, component tests,
production bundle, or browser/accessibility tests on the exact release commit.

## Decision

After npm lock auditing and before Python artifact construction, the release
workflow installs the locked web dependencies and runs typecheck, Vitest,
production build, Chromium installation, and standard Playwright E2E. The job
uses the existing pinned Node 22 setup and the configurable loopback port.

## Boundaries

- Live API-session and HTTPS production-bundle E2E remain opt-in and are not
  enabled with credentials in the release workflow.
- This rechecks the checked-out signed tag; it does not prove external IdP,
  provider, production API, or hosted deployment behavior.
- A web verification failure blocks the release job before source/package/image
  publication steps.

## Rollback

Remove the added web verification steps from `.github/workflows/release.yml`.
No application runtime or schema migration is involved.
