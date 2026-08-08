# Threat Model

The normative module index is
[`threat-model-index.v1.yaml`](threat-model-index.v1.yaml), validated by
[`threat_model_index.schema.json`](../schemas/threat_model_index.schema.json).
It is joined to the active runtime module registry, Security Architecture v2,
and the normalized risk register. A module addition or interface/data-class
change is incomplete until its threat entry and evidence are updated.

This is repository design and test evidence. It is not a security guarantee,
compliance assessment, certification, penetration-test result, or proof that a
deployed control operates continuously.

## Module coverage

| Active module | Owner | Primary assets and boundaries | Threat posture |
| --- | --- | --- | --- |
| `platform.core` | Platform Security | identity, sessions, local DB/backups, audit/workflow; API, local storage, tenant server, build | Legacy DB import and backup/manifest restore JSON are resource-bounded, duplicate-safe, ambiguity-checked, and validated before mutation/allocation; the central policy and inventoried approval services provide bounded permission/scope/SoD properties, while universal route/repository ABAC, privileged access, encryption/authenticated provenance, tenant context, atomic evidence, malware scanning, real recovery exercises, and supply chain remain partial or deployment-dependent |
| `platform.master-data` | Domain Integrity | organization, entity, branch, currency, period, change evidence; API, local/server storage, disclosure | Authorization and hosted isolation are partial; bounded local integrity does not control a source ERP |
| `finance.core` | Financial Integrity | control ledger, exact entry lines, trial balances, mutation evidence; API, local/server storage, disclosure | Exact arithmetic is bounded; identity, hosted persistence, and disclosure remain partial/deployment-dependent |
| `inventory.core` | Financial Integrity | movements, counts, FIFO layers, valuations/reversals, Finance Draft evidence; API, storage, disclosure | Exact implemented strategies are bounded; identity, lifecycle coverage, and disclosure remain limited |
| `finance.controls` | Domain Integrity | reconciliation/close/control workflows, exceptions, evidence metadata; API, storage, optional dependencies, disclosure | Local FI-011 close files are structurally bounded; permission, tenant, atomic delivery, authenticated provenance, and artifact handling remain incomplete end to end |
| `reconciliation.core` | Financial Integrity | source records, rules, candidates/decisions, reviews, reports/evidence; file ingress, local storage, disclosure, build | Canonical tabular, selected configuration/control YAML, two FI-012 manifests, and staged resource-bounded FI-012 JSON/CSV/text/non-redacted copies have handled-failure rollback plus explicit integrity-checked local interruption recovery; replacement remains non-observer/crash-atomic, the marker is not authenticated, and real host/filesystem loss, report/Studio readers, legacy XLS internals, malware quarantine, disclosure authorization, upstream authenticity, and supported-version parity remain open |
| `mapping.profiles` | Platform Security | mapping configuration and inspected export headers; file ingress, local storage, disclosure | Tabular header and bounded mapping-YAML safeguards exist; semantic correctness, origin authenticity, malware assurance, and disclosure still require human governance |
| `connectors.boundary` | Platform Security | CAMT.053 statements, normalized payment pages, connector manifests, endpoint policy, credential references; file ingress, optional network, build | Offline XML and provider-neutral connector bounds are tested; source authenticity, provider identity, live vendor conformance, payment/write-back, and deployment isolation remain partial or deployment-dependent |
| `packs.lifecycle` | Platform Security | signed declarative packs, publisher keys, approvals, immutable versions, lifecycle events; file ingress, local storage, build | Closed data-only signatures, maker-checker, compatibility, disable, and rollback are synthetic/local; legal publisher identity, production trust administration, distributed activation, and business-effectiveness assurance remain absent |
| `plugins.export` | Platform Security | built-in adapter registry, local exports, canonical projections; file ingress, local storage, build | Allowlisted built-in CSV reads share bounded preflight and signed manifest-only network foundations are synthetic; malware assurance, production credentials, vendor interoperability, distributed quotas, and writeback are absent |
| `retail.settlement` | Platform Security | exported POS/processor records, exact settlement decisions, input fingerprints, digest-bound reports; file ingress, SQLite/PostgreSQL persistence, API authorization, read-only modern Studio disclosure | Exact non-posting arithmetic, ambiguity, duplicate, unmatched, replay, workspace isolation, immutable persistence, and the synthetic English/Arabic Studio projection are bounded locally/server-contract tested; provider authenticity, settlement finality, fraud, posting, write-back, hosted deployment, HA/DR, and production operation remain outside the slice |
| `bank.cash-reconciliation` | Platform Security | CAMT.053 statement lines, ledger exports, exact control decisions, input fingerprints, digest-bound reports, synthetic Studio projection; file ingress, local storage, browser disclosure | Exact non-posting reference/amount/date-window control, ambiguity, duplicate, unmatched, tamper, and bounded read-only Studio checks are local; bank authenticity, provider connectivity, authenticated live API, posting, write-back, and production operation remain outside the slice |
| `manufacturing.cost-control` | Platform Security | production orders, material issues, completions, scrap events, exact cost/quantity decisions, input fingerprints, digest-bound reports, synthetic Studio projection; file ingress, local storage, browser disclosure | Exact non-posting cost/quantity, scrap, unknown-order, tamper, and bounded read-only Studio checks are local; statutory valuation, ERP authenticity/connectivity, authenticated live API, inventory/WIP/GL posting, write-back, and production operation remain outside the slice |
| `professional.invoice-payment` | Platform Security | exported professional invoices and client payments, exact client/amount/due-date decisions, input fingerprints, digest-bound reports; file ingress, local storage, disclosure | Exact non-posting invoice/payment arithmetic, client binding, ambiguity, unmatched, unapplied-cash, and tamper controls are bounded locally; revenue recognition, billing authenticity/connectivity, receivables allocation, posting, write-back, persistence/API/Studio, and production operation remain outside the slice |
| `studio.modern` | Evidence Security | marked synthetic contracts, frontend build, rendering, screenshots; disclosure and build | Synthetic/read-only guards are bounded; edited artifacts, browser storage, recipients, provenance, and public hosting remain outside assurance |

All fifteen modules are `experimental` in the runtime registry. The index cannot
promote that maturity: every entry is `evidence-bounded`, and every module has
at least one `partial`, `deployment-dependent`, or `planned` threat case.

## Actors and trust

The index distinguishes the trusted deployment dependency (workspace
operator), authenticated but limited application users and browser viewers,
untrusted input providers/API callers/contributors/dependency endpoints, and
external artifact recipients. Trust is scoped: an authenticated user is not
implicitly authorized for a tenant, object, amount, period, or approval; a
local operator can still misconfigure paths, endpoints, retention, or sharing.

## Threat catalog

The shared catalog covers:

- untrusted path and parser abuse;
- financial-input or decision manipulation;
- authentication, authorization, and segregation-of-duties bypass;
- tenant or optional-dependency context escape;
- partial mutation, audit gaps, and replay;
- artifact tampering or unauthorized disclosure;
- extension, build, egress, and dependency supply-chain risk; and
- UI-content or synthetic-boundary confusion.

Each module applies only relevant threats and links each case to Security
Architecture v2 controls, existing test files, residual-risk IDs where an
appropriate normalized risk exists, explicit limitations, assumptions, and
out-of-scope capabilities. An empty risk link does not mean zero risk; it means
the threat has no exact normalized risk entry and must not be assigned an
invented score in this index.

## Review gate

Review is required at least every 90 days and whenever a module, interface,
network dependency, persistent store, actor, permission, data class, linked
control, risk, code path, or test materially changes. An incident,
vulnerability, failed isolation test, or external assessment also triggers
review.

The contract tests require:

- exact parity with every active runtime module and its maturity, capability,
  interfaces, data classifications, and existing module test evidence;
- closed owner, actor, trust-boundary, data-class, threat, control, and risk
  references;
- existing evidence paths for every module and threat case; and
- visible residual limitations with no unbounded security status.

## Deployment boundary

Community Local trusts the operator-controlled account, filesystem, database,
and backup protections. Team/Server remains experimental and does not yet have
one live end-to-end PostgreSQL/Redis/object-storage isolation and recovery
proof. Regulated deployment is planned-only: air-gap packaging, customer-managed
keys, WORM enforcement, HA/DR, privileged access, and independent validation
are not implemented.

Do not infer internet-facing hardening, hosted multi-tenant readiness, legal
non-repudiation, external audit assurance, compliance, certification,
bank-grade quality, enterprise readiness, or production readiness from this
index.
