# ADR 0583: Configurable loopback port for web E2E runtime

## Status

Accepted — 2026-08-23

## Context

The web Playwright configuration used a fixed loopback port (`4173`) for both
the Vite development server and the test base URL. A constrained execution host
returned `EACCES` before any browser test ran, even though the web client built
and its component tests passed.

## Decision

Read `RECONFORGE_WEB_PORT` in `apps/web/playwright.config.ts` and use the same
value for the Vite `--port` argument and Playwright `baseURL`. Preserve `4173`
as the default so existing local commands and CI remain backward compatible.

## Safety and boundaries

- The server remains bound to `127.0.0.1`; this does not expose the dev server
  to the network.
- The setting changes test-host portability only. It does not enable live API
  sessions, HTTPS hosting, provider calls, or production deployment claims.
- Live browser-session and HTTPS scenarios remain explicit opt-ins through
  their existing `RECONFORGE_LIVE_*` controls.

## Evidence and rollback

`RECONFORGE_WEB_PORT=5180 npm --prefix apps/web run e2e` passed 16 tests with
five explicit opt-in skips on 2026-08-23. Rollback is a one-file revert of the
Playwright configuration; the default remains unchanged.
