# Web accessibility test continuation — 2026-10-28

At entry `dfc9ad97649b4d458de5d56d8cd514da03168e54`, the hosted web job
failed because the combined critical English/Arabic route test exhausted its
60-second total timeout. Its result was 43 passed, 9 skipped and one timeout.
The original local combined test also timed out under concurrent workload; its
trace reached the final Arabic route. A single-worker diagnostic completed in
31.3 seconds. These observations identify a cumulative test budget, not a
proven root cause of the hosted load.

The test now runs one case per language, with the same 13 routes and Axe tags,
the same heading assertions, and explicit `lang` and direction assertions for
both languages. Each case has the existing 60-second timeout. This increases
the combined maximum budget and isolates browser contexts; a separate existing
navigation test covers switching locale through the UI. It does not prove all
cross-route state accumulation or WCAG conformance.

With the final test edit, local Node 26.3.0 / Chromium E2E returned 45 passed
and 9 skipped in about 1 minute (62.77 s wall time), 8 workers, isolated output:
`output/erp-vision-20261028/web-final-e2e/run.log`. The skipped cases require
live prerequisites. The previous negative run remains in
`output/web-baseline-isolated-20261028/e2e.log`; its trace remains there.
Vitest passed 1,284 cases across 118 files in an isolated temporary directory,
147.74 s, before the final E2E-only assertion change; Vite build to a separate
output passed. Hosted Node 22 and live authenticated journeys are separate
gates, not established by this local result.
