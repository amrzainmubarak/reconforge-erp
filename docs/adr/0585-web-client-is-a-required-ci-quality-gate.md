# ADR 0585: Web client verification is a required CI quality gate

## Status

Accepted — 2026-08-23

## Context

The web client had typecheck, component tests, production build, and Playwright
coverage that could be run locally, but the general pull-request CI workflow
did not execute them. A Python-only green build could therefore miss a broken
browser bundle, accessibility regression, or route-level E2E failure.

## Decision

Add a dedicated `web` job to `.github/workflows/ci.yml` that uses the pinned
Node 22 toolchain and locked npm dependencies to run, in order:

1. TypeScript typecheck.
2. Vitest component tests.
3. Production Vite build.
4. Chromium installation with Playwright system dependencies.
5. Standard browser/accessibility E2E.

The job is required on the workflow's normal pull-request/push execution. The
existing live browser-session and HTTPS production-bundle tests remain explicit
opt-ins and are not silently enabled in shared CI.

## Safety and boundaries

- Checkout credentials remain disabled and no secrets or customer data are
  required.
- The browser server binds to loopback and uses the default `RECONFORGE_WEB_PORT`
  value of 4173 in CI.
- This is a quality gate, not evidence of live API, external IdP, provider, or
  production HTTPS availability.

## Rollback

Remove the `web` job from `ci.yml`; no application schema or runtime migration
is involved.
