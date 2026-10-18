# Production foundation and customer-evidence roadmap

Date: 2026-10-03 (Africa/Cairo). Source baseline:
`1551e8ae69a2982961a315c40be1c4ac2b8c8bc5`.
Owner: ReconForge maintainers. This is an execution plan, not a maturity claim.

User steering: the full individual-to-bank/institution scope remains the target.
No company pilot is currently available. The [open-source engineering track](OPEN_SOURCE_ENGINEERING_2026-10-03.md)
supplies verified references and planned synthetic workload execution; it does not
replace the separately measured company-outcome gate.

## Outcome and product boundary

The acceptance target is a customer-operated workflow whose input counts,
reconciliation definitions, decisions, discrepancies, staff effort and reviewer
acceptance can be independently checked. Test counts do not establish that outcome.
Keep the MIT, local-first Community mode and finance-controls positioning. Build
an opt-in operational subledger and posting capability in bounded modules; do not
relabel the existing control ledger as a statutory general ledger.

## What exists and what is missing

| Requested capability | Observed implementation | Required closure evidence |
| --- | --- | --- |
| PostgreSQL-first production mode | 92 Alembic revisions; repository/application adapters; real HTTP boundaries; current clean migration succeeds | Complete supported workflow through authenticated HTTP, worker recovery, native backup/restore, upgrade/rollback, deployment validation and non-privileged runtime enforcement |
| Tenant isolation end to end | 167 migrated tables enable and force RLS; transaction-local hierarchy scope and granted scopes | Reject unsafe runtime roles; tenant/workspace/entity adversarial HTTP/worker/export tests; no local fallback; fix CI deselection; exercise real browser sessions |
| Double-entry Finance Core / GL | Balanced control entries, account hierarchy, dimensions, trial balance and consolidation control journals | Append-only posting/reversal domain, explicit currency/rounding, period locks, source posting identity, exact subledger-to-GL reconciliation and concurrency proofs |
| Sales to cash | AR invoices, credit checks, receipts, allocations and aging | Sales order, reservation, shipment, inventory valuation/COGS, AR posting, cash posting, returns/reversals and evidence within one tested cycle |
| Purchase to payment | PO, receipt, invoice and three-way-match foundations | Cumulative receipt/invoice integrity, stock integration, GRNI/AP posting, payment records and allocation, returns/reversals and evidence within one tested cycle |
| React production application | Synthetic financial pages; real administration writes and HTTPS hosting | Shared authenticated tenant context, session recovery, real financial forms, permissions/conflicts, jobs, evidence drill-down and PostgreSQL browser E2E |
| Company outcomes | Synthetic case studies and historical synthetic benchmark reports | Authorized company pilot, measured manual baseline, accepted discrepancies, reviewer identity/outcome and permission to publish aggregate results |

## Ordered work and gates

Each row is a gate, not a calendar promise. Complete a small tested slice before
expanding it. Preserve the existing historical Phase 1-4 records; the PROD tasks
track the new production objective without rewriting old evidence.

| Backlog ID | Priority / owner | Deliverable | Exit gate / dependencies |
| --- | --- | --- | --- |
| PROD-001 | P0 / QA + architecture | Current reproducible baseline and factual inventory | Commands, versions, durations, failures/skips and raw log hashes recorded before feature edits |
| PROD-002 | P0 / finance + database | Prevent cumulative AP over-approval; exact quantity arithmetic | Independent invoices and duplicate PO-line rows cannot consume the same received quantity twice; concurrent SQLite/PostgreSQL approvals serialize; audit/outbox rollback; depends PROD-001 |
| PROD-003 | P0 / SRE + QA | Restore PostgreSQL CI coverage | Intended RLS/migration/parity nodes survive effective pytest selection; expensive scales stay separately opt-in; depends PROD-001 |
| PROD-004 | P0 / security | Remediate current dependency disclosures | Targeted Python/npm lock changes, upstream advisory review, clean audits, compatibility/security/build gates; depends PROD-001 |
| PROD-005 | P0 / UI + identity | Shared live tenant/session and recoverable reauthentication | Login-to-live metrics carries selected tenant, rejects unauthorized tenant, never persists credentials/CSRF, clears stale data on scope change; depends PROD-001 |
| PROD-006 | P0 / database + security | Enforce safe runtime PostgreSQL role | SUPERUSER/BYPASSRLS/unsafe owner denied on runtime path; administrator migrations remain separate; pool reuse tested; depends PROD-003 |
| PROD-007 | P0 / finance | AR currency and customer-status invariants | Existing document currencies cannot be relabeled through customer upsert; inactive customer approval rejected on both engines; depends PROD-001 |
| PROD-008 | P1 / backend + security | PostgreSQL exception/review vertical slice | Authenticated tenant/workspace/entity-scoped list/get/assign/transition, SoD and audit; sibling scope denial; no SQLite fallback; depends PROD-005, PROD-006 |
| PROD-009 | P1 / accounting + database | Append-only posting kernel | Balanced exact lines by currency, immutable posted entry/lines, explicit reversal, unique source posting key, period lock serialization, TB and source drill-down; migration/restore/parity tests; depends PROD-002, PROD-007 |
| PROD-010 | P1 / operations + finance | Purchase-to-payment vertical slice | Receipt produces stock and GRNI; invoice clears GRNI to AP; payment clears AP to cash; atomicity, retry, partial quantities, returns, rounding and period tests; depends PROD-009 |
| PROD-011 | P1 / operations + finance | Sales-to-cash vertical slice | Shipment changes stock/COGS; invoice changes AR/revenue; receipt clears AR to cash; atomicity, partial shipment/payment, return, credit and period tests; depends PROD-009 |
| PROD-012 | P1 / UI + QA | Financial write journeys | Backend-driven drafts, review/approval, idempotency/conflict handling, accessible Arabic/English forms, keyboard/error recovery and evidence links; real browser to PostgreSQL tests; depends PROD-008, PROD-010, PROD-011 |
| PROD-013 | P1 / SRE + performance | Deployable measured workload | Pinned server profile, non-root app, health/readiness, backup/restore, crash/resume, metrics without raw rows; synthetic scale progression with correctness oracle; depends PROD-006, PROD-008, PROD-009 |
| PROD-014 | P1 / product + independent reviewer | Controlled company pilots | Authorized company/data/reviewer, reproducible measurements and signed-off findings; publication permission separately recorded; depends PROD-012, PROD-013 |

## Posting architecture decisions to validate

Use the existing modular monolith and application ports. A source operation and
its stock/subledger/posting effect must commit in one database transaction with
audit and outbox records. An outbox consumer may drive external side effects, but
must not create a window where an acknowledged invoice lacks its accounting
entry. Store a unique tenant/entity/source-document/posting-version identity.
Repeated requests return the same effect; conflicting payloads fail explicitly.

Keep operational quantity precision independent from currency precision. Use
canonical Decimal text and exact accumulation, not ambient Decimal context or
binary float. Resolve stock cost using the accepted valuation strategy before
posting. Currency conversion always includes rate source, effective date and
rounding policy. Every posted balance reconciles to immutable source effects.

Introduce new posted/reversal semantics through a versioned module/migration.
Existing control-entry validation/void behavior remains a compatibility contract;
do not silently reinterpret historical control entries as legal-book postings.
Database constraints/triggers, service authorization and property tests enforce
complementary invariants. Bound retries, lock order and transaction duration.

## React UX acceptance

Start with an explicit authenticated tenant, workspace, entity and period context.
Use one connected journey: import/preview -> validation -> run -> exception ->
independent review -> evidence. Financial forms show exact currency, rounding,
posting preview, source references, field errors and recovery from stale versions.
Controls reflect server permissions; client hiding never substitutes for server
authorization. No success toast before committed effect. Scope changes clear old
records and cancel or ignore stale responses. Preserve Arabic RTL, keyboard
navigation, focus restoration, accessible labels and reduced-motion behavior.

## Scale and pilot protocol

1. Validate 10K and 100K synthetic records with a known discrepancy oracle, then
   1M, then a proposed 5M/30-reconciliation workload only after resource/correctness
   gates hold. Count input records, not jobs or partition effects, as transactions.
2. Report hardware, versions, image/source/rule/input/output digests, currencies,
   date spread, duplicate/reference density, candidates, ambiguity, confirmed
   discrepancies, missed seeded discrepancies, peak RSS, CPU, wall time, database
   size and recovery behavior. Run repeat/permutation checks and retain failures.
3. Recruit 3-5 controlled pilots in bank/cash reconciliation, inventory-to-GL and
   retail settlement. Engagement and access require a named company sponsor;
   there is no authorization in this plan to contact companies or upload data.
4. Before automation, observe staff minutes for mapping, correction, matching,
   review and evidence preparation on a defined recurring workload. Measure the
   same tasks after adoption. Report setup/training separately. Saved hours =
   comparable manual staff minutes minus assisted staff minutes, divided by 60;
   machine runtime is a separate metric. Avoid double-counting parallel staff.
5. Record actual transaction and reconciliation counts, input quality, confirmed
   differences by currency, false positives, unresolved cases and reviewer
   exceptions. A reviewer records acceptance/rejection, exact evidence digest,
   date, scope and outstanding requests. A checksum alone is not acceptance.
6. Keep raw customer data outside Git. Retain an approved aggregate case study
   only after privacy and publication approval. No company, hours-saved figure or
   external-review acceptance is currently asserted.

## Research basis checked 2026-10-03

- PostgreSQL documents that SUPERUSER and BYPASSRLS bypass row policies even
  when application scope is set: [row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
- Security mapping baseline: [OWASP ASVS 5.0.0](https://owasp.org/projects/asvs),
  [NIST SSDF 1.1 Final; 1.2 remains Draft](https://csrc.nist.gov/projects/ssdf/publications),
  and [SLSA 1.2 Approved](https://slsa.dev/spec/v1.2/). These are design/reference
  mappings, not attestations that ReconForge meets an assurance level.
- [ERPNext immutable ledger](https://docs.frappe.io/erpnext/immutable-ledger-in-erpnext)
  and [inventory accounting](https://docs.frappe.io/erpnext/accounting-of-inventory-stock)
  provide public reference behavior for reversal and stock/accounting integration.
- [BlackLine transaction matching](https://www.blackline.com/products/financial-close/transaction-matching/)
  and [Trintech Cadency Match](https://www.trintech.com/cadency/match/) describe
  established matching/workflow offerings. Public descriptions are not controlled
  comparative benchmarks. Differentiation must be measured on identical authorized
  workloads: reproducibility, source traceability, local operation, recovery,
  reviewer effort and total operating cost.

## Delivery and rollback discipline

One branch holds reviewed small commits; existing unrelated untracked work is
preserved. Run focused gates after each slice, then the relevant full gates once
changes settle. Record baseline failures separately from regressions. Revert
application-only slices by commit; migration slices require tested restore or
compatible readers. A draft PR can expose evidence and remaining gaps; it must
not imply a production release, company outcome or independently validated rank.
