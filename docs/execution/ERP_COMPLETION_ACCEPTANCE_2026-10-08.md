# ERP completion acceptance checkpoint

Bounded local acceptance passed at `547b653915873ed010e70c0a96ae9aee4b8cc4b6`. [Draft review](https://github.com/amrzainmubarak/reconforge-erp/pull/125) is stacked on `amr/global-platform-execution-20261008`; main remains `b61ea56b`. This checkpoint establishes the connected experimental cycles below. The original global ERP scope remains unfinished. Current hosted verification is separately authoritative at [PR checks](https://github.com/amrzainmubarak/reconforge-erp/pull/125/checks); this local index makes no hosted success claim.

| Gate | Result | Actual execution source |
|---|---|---|
| full-python | 4538 passed; 595 explicit skips; 0 failures/0 errors | `caf98d08a307` |
| critical-pg17 | 564 passed; 0 explicit skips; 0 failures/0 errors | `caf98d08a307` |
| native-recovery-pg16 | 33 passed; 0 explicit skips; 0 failures/0 errors | `caf98d08a307` |
| ruff | Passed; invocation and log hashes in companion JSON | `caf98d08a307` |
| mypy | Passed; invocation and log hashes in companion JSON | `caf98d08a307` |
| production-web-build | Passed; invocation and log hashes in companion JSON | `518590f6410c` |
| whole-web-unit | 261 passed; 0 pending; 0 failed | `518590f6410c` |
| web-typecheck | Passed; invocation and log hashes in companion JSON | `518590f6410c` |
| standard-19-e2e | 19 passed; 0 explicit skips; 0 failures/0 errors | `518590f6410c` |
| wire-https-erp-native-restore | Actual wire HTTPS ERP; hashes of all195 tables (69 nonempty); 3 tamper refusals | `518590f6410c` |
| current-security-package-image-performance-reliability | 14 actual or exact unchanged-subject gates; package/secrets freshly executed | `547b65391587` |
| current-default-ledger-secrets | Passed; invocation and log hashes in companion JSON | `547b65391587` |

The sprint composes existing PostgreSQL identity, organization/workspace/entity scope,
currency registry, AR, AP, FIFO, reviewed inventory receipt and Finance posting engines.
It adds real source ownership and shared transaction participation before extending
the user interface. The implementation is a modular monolith with additive revisions
0109 -> 0110 -> 0111. It preserves main and the previous accepted platform branch.

Three managed worktrees separate Sales, Procurement and operational Finance.
The integration lead owns shared API registration, authorization and migration
inventories, Studio navigation, packaging, CI and final evidence.

## Connected use cases

Service Sales creates a scoped customer with the existing credit controls, prepares
an exact discounted quotation, requires independent approval, records an order and
actual service completion, and creates a native AR invoice. Reviewed revenue posting
and native invoice publication share one transaction. Full collection commits its
native cash receipt, AR allocation, cash/AR journal, source links, immutable command,
audit and outbox together. The final state is Paid.

Procurement creates a scoped supplier and one-line PO, requires independent review,
and records a full untracked Stock/Consumable receipt. Stock movement, FIFO layer,
inventory/clearing GL and native AP goods receipt share one transaction. The exact
three-way-matched supplier invoice produces clearing/AP GL. Independently reviewed
full payment produces AP/cash GL and the native AP settlement link atomically.
The final state is Paid.

Studio exposes live `/sales-revenue`, `/procurement-operations` and
`/enterprise-finance`, with `/erp` as the shared Finance entry. Customer/supplier
creation, authorized master selections, workflow actions, review and posting are
actual API writes. English/Arabic messages, RTL, keyboard flows, responsive layout
and posted selected-period net-activity reporting are included. JSON report download
uses actual posted effects. It does not include opening balances.

## Financial and security boundaries

One scoped READ COMMITTED transaction owns each business effect; native engines
participate without committing separately. Exact integer minor units and retained
currency precision determine each amount. Maker/checker/poster separation, scoped
amount authority, current persisted identity and fresh step-up are checked before
every mutation and frozen retry. An idempotent acknowledgement belongs to the
original actor and exact command payload and is checked against persisted effects.

Deferred database guards close the Sales/Procurement source, native AR/AP/IRP and
OPS/GL phases in both directions, including OLD and NEW parent references. Generic
native or Finance endpoints cannot advance an owned source ahead of its business
workflow. Exact named SQLSTATE23514 owner refusals map to a safe409, including a
bounded explicit native AR error-wrapper chain; unrelated failures retain503.
Historical unowned native workflows keep their original semantics.

Sales reserves each collection reference in the existing tenant/workspace native
AR namespace before financial capture. The reservation retains only opaque owner
kind/id, is immutable and coordinates concurrent and hidden sibling-entity names.
New Sales references are canonical uppercase ASCII letters/digits/dot/underscore/
hyphen, at most64 characters. Unowned Unicode native receipt history remains
compatible. Deterministic backfill uses immutable source timestamps; empty downgrade
removes only the new reservation hooks/keys, while populated financial history is
protected. No new table, broad grant, security-definer or RLS bypass is introduced.

## Verification discipline

Final counts and acceptance status must come from completed source-bound reports.
The actual browser uses a normal trusted HTTPS listener and production-built Studio;
HTTPS-origin TestClient owner regression evidence is separately identified.
Native groups require zero failures/errors/skips. Whole Python environmental skips
are retained with reasons and covered by separately configured service groups where
available. Tests never disable business guards during the exercised workflow.
Finite administrative synthetic-tenant teardown checks exact installed DELETE hooks,
flushes deferred constraints and restores hooks before commit.

Original failures remain retained: stale AST/CI/fixture expectations, real public
owner bypasses, premature native Procurement source capture, shared receipt-name
collisions, wrapped owner error classification, snapshot/timestamp fixture mistakes,
and the native fixture teardown error. Superseded or aborted readers do not count as
final acceptance. The test-hygiene-only518590->caf98 delta changes exactly two named
test files; unchanged web/image subjects retain their actual source and byte hashes.
Current full Python/native/security-secret/package gates run on the final test source.

## Scope and recovery

These are experimental functional-currency, zero-tax, full-settlement cycles.
Sales covers completed services with1..16 lines. Procurement covers one fully
received untracked Stock/Consumable FIFO line and one full payment. Inventory and
Finance master configuration uses the existing governed engines.

The sprint does not complete stock Sales/COGS, customer/supplier returns or credit
notes, refunds or new OPS financial inverses, PR/RFQ, partial fulfillment/receiving/
payment, tax or FX ERP cycles, fixed assets/expense/Treasury/intercompany/budgeting
ERP integration, complete CRM or live banking execution. It initiates no external
bank transfer. No Production Ready, Banking Grade, certification, compliance,
adoption or unrestricted capacity claim is made.

Additive migrations require the finite scoped SELECT dependencies documented in
the module runbooks for reverse integrity checks; owner DML remains denied.
Populated downgrade refuses evidence loss. Application rollback retains upgraded
schemas; recovery uses verified pre-upgrade backups or a forward fix. The native
ERP restore compares all195 tables in the populated database (69 nonempty) and the complete function/trigger,
constraint/index, ACL and RLS catalog, then checks restricted tamper refusal.
The separate hardened container is the CLI/module profile. Its scan is not proof
of a hosted Studio/PostgreSQL Docker deployment. Single-host manual HA drills do
not establish host-loss tolerance or an automated production RPO/RTO.

Actual full/native executions use `caf98d08`; the later `547b6539` changes exactly one MANIFEST inclusion and freshly passes packaging/default secrets. Production/web/image subjects remain `518590f6` through a complete Git/content proof for the two test-hygiene files and that one packaging line. Each gate retains its original identity. Browser worktree LF and root CRLF bytes are explicitly distinguished; the root image is verified against actual root runtime bytes. Native33 is a five-file recovery profile, not33 separate database restores. Performance figures concern the measured reconciliation workload, not ERP transaction capacity.
