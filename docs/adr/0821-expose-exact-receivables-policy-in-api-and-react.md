# Expose retained AR monetary interpretation without browser rounding

Status: accepted for the bounded AR API and React workflow.
Date: 2026-10-03
Scope: PROD033; additive exposure over SQLite49 and PostgreSQL0099.

The API exposes the eleven-field retained monetary policy through existing
authorized customer, invoice and receipt projections. It derives canonical
`*_minor_text` fields from exact stored integers, including nested lines,
allocations and signed credit exposure. Recursive allowlists remove internal
snapshot and storage fields. Existing integer fields remain compatible.

All eight monetary request positions validate before Pydantic coercion. Actual
integers and bounded ASCII integer strings remain accepted; booleans, floats,
decimal spellings and exponent strings are refused. The server does not impose
the browser's safe-number limit on other exact integer clients.

React uses exact text and BigInt to interpret money with the record's retained
precision. JPY has zero places and KWD has three. Unit-price and cash inputs use
explicit major units; excess precision is refused without rounding. Arabic
digits and decimal separators remain usable. Browser writes require safe JSON
integers; larger stored values remain readable through exact text. An unsafe
numeric transport and its text companion must represent the same rounded JSON
number before the exact text is used.

All-NULL history remains readable as explicitly labeled original minor units.
The UI refuses new financial actions that require unverified interpretation.
Credit exposure has exact text but no aggregate policy and is labeled as minor
units. Cash allocation requires complete policy affinity between its sources.
The browser never submits a replacement policy. Existing unknown-outcome
request freezing, bounded exact retries, authoritative allocation readback,
CSRF, step-up and scope/session invalidation remain in force.

A separate reproducible AdminAudit race was repaired: committed view lifetime
and current security revision authorize commands; passive read-controller
creation is not a prerequisite for logout. Layout cleanup invalidates removed
views immediately. Old success or invalid-token completions cannot alter a
replacement tenant/session or a remounted view.

Acceptance: the corrected authenticated SQLite/PostgreSQL HTTP selection passes
11 tests without skips and positively measures five new AR Outbox events per
JPY/KWD lifecycle. A broader local contract passes120 with one live prerequisite.
Full React passes202 tests; the deterministic AdminAudit selection passes9.
A fresh HTTPS PostgreSQL0099 browser run passes both cash/policy journeys in
32.0s, with stable source hashes and independent database cleanup. English and
Arabic Axe checks, 390px layouts and keyboard disclosures are covered. The
retained executable fixture is `tests/receivables_policy_ui_runtime.py`.
Independent review passes111 Python/77 overlapping web tests, sixteen Python
and twenty-one actual Python-to-JSON-to-TypeScript probes. Counts are not summed.

Earlier failures and the original insufficient PostgreSQL Outbox predicate
remain retained. Evidence is in RECEIVABLES_POLICY_API_2026-10-03.json and
RECEIVABLES_POLICY_UI_2026-10-03.json. Hosted acceptance and a new immutable
whole-repository gate remain separate. The preexisting invoice request/cache
identity gap is assigned separately; this exposure does not repair it. No GL,
full trade cycle, FX conversion, customer outcome or auditor acceptance follows
from these AR tests.

Rollback: redeploy the compatible prior reader without changing stored policy
or money. Exact integer clients remain compatible; clients relying on silent
float/boolean coercion must send exact minor-unit integers. Keep verified
backups and unresolved history; do not rescale or delete retained evidence.
