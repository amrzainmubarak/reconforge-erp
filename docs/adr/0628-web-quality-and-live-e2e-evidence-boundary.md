# ADR 0628: Web quality and live E2E evidence boundary

- Status: Accepted
- Date: 2026-08-25
- Scope: `apps/web` local quality and browser regression evidence

## Context

ReconForge has a bilingual React/Vite Studio with automated component and
browser tests. The release gates must distinguish reproducible local UI quality
from live identity, hosted deployment, and independent accessibility assurance.
The browser suite includes opt-in tests that can revoke a current synthetic
session or mutate a provisioned synthetic user/role, plus an opt-in HTTPS
production-bundle test.

## Decision

Record the following as a bounded local gate:

- `npm ci` from the committed lockfile;
- TypeScript typecheck;
- the complete Vitest run;
- the production Vite build; and
- the complete Playwright command, including passing Axe/RTL, keyboard,
  responsive, redaction, and route-contract tests.

The command remains successful when explicitly skipped tests are reported. In
standard mode the suite records 16 passes and 5 skips. The opt-in local HTTPS
production-bundle mode records 17 passes and 4 skips and verifies HSTS, CSP,
same-origin health, no inline script/style execution, and zero observed CSP
violations. The four remaining browser-session and administration mutation
tests require explicitly provisioned local API/session targets. Public wording
must call this local regression evidence, not live IAM, hosted deployment, WCAG
certification, or production availability evidence.

## Consequences

The repository has a reproducible local UI quality gate and makes missing live
environment prerequisites visible. A future release candidate must run the
skipped tests in a disposable, synthetic environment and retain the resulting
artifacts before claiming live browser/session or HTTPS deployment coverage.
Independent assistive-technology assessment and hosted operational evidence
remain separate gates.

## Rollback

This is a documentation/evidence classification decision. Revert the ADR and
execution-log entries if the test contract or evidence policy changes; do not
silently change skip behavior or reinterpret old results.
