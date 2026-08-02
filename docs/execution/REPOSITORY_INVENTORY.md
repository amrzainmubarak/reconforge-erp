# Repository Inventory

Measured on 2026-07-26 against the dirty worktree documented in `STATE.md`.

## Quantitative inventory

| Surface | Count |
| --- | ---: |
| Python source files under `reconforge/` | 212 |
| `tests/test_*.py` files | 126 |
| Collected Python tests | 1,088 |
| Control-pack directories | 19 |
| Alembic PostgreSQL revisions | 11 |
| JSON schemas under `docs/schemas/` | 49 |
| ADR files | 81 |
| GitHub Actions workflows | 6 |

Generated `__pycache__`, build, distribution, test-temp, Node, and output artifacts are excluded from file counts.

E-052 adds one test module with 14 collected contracts, one release-manifest
schema, ADR 0067, and the tag-only candidate workflow. Its two repository-only
Python helpers do not change the 208-file runtime source count.

E-053 adds one test module with five collected contracts, one SBOM-manifest
schema, ADR 0068, and one repository-only SBOM builder/normalizer. It integrates
SBOMs into the candidate workflow and removes the separate legacy SBOM workflow,
so runtime source remains 208 while workflow count decreases by one.

E-252 adds three runtime files for the deterministic consolidation domain,
application port, and immutable object adapter; two focused execution/test
modules; one closed artifact schema; ADR 0210; and bounded Finance Core,
threat-model, claims, gap, and operator documentation. It adds no database
migration, network call, UI route, API route, CLI command, or source write-back.

E-254 adds one deterministic consolidation-lifecycle domain file, extends the
existing consolidation application service and Finance Core manifest, adds one
focused test module, one closed worksheet schema, ADR 0211, and one operator
document. It adds no database migration or adapter, persisted ownership/run
state, journal/posting surface, network call, UI/API/CLI route, live rate, or
ERP/bank write-back. NCI is a non-posting presentation allocation rather than
acquisition accounting or a statutory statement.

E-256 adds one backend-neutral consolidation-close application boundary, one
local SQLite consolidation-close repository, migration 25 with six local
control-journal lifecycle tables and trigger guards, one focused SQLite/restore
test module, ADR 0212, one operator document, and backup/restore membership for
the new lifecycle tables. It adds no PostgreSQL parity, hosted API, CLI command,
UI route, live ERP/bank connector, live rate provider, legal-book posting,
statutory statement, tag, release, deployment, or write-back surface.

E-258 adds one local cancellation-under-load benchmark harness, one focused
profile test module, ADR 0214, and MANIFEST.in membership. It adds no new
persistence primitive, migration, repository method, API, CLI, UI, PostgreSQL
adapter, provider call, scale publication, tag, release, deployment, or
production mutation.

E-054 adds one test module with 13 collected contracts, two supply-chain
schemas, ADR 0069, the universal `uv.lock`, closed policy/exception registries,
one repository-only validator, Gitleaks configuration, Dependabot definitions,
and locked security/candidate gates. Runtime source remains 208 and workflow
count remains six.

E-055 adds runtime tabular-ingress policy, one dedicated hostile-input test
module, one parser-inventory contract module, one file-ingestion schema, and
ADR 0070. It raises runtime source to 209, test modules to 115, collected tests
to 903, schemas to 49, and ADRs to 70.

E-056 adds runtime structured-document policy, extends the shared YAML loader,
adds one dedicated test module with 27 cases plus two new inventory contracts,
and adds ADR 0071. It raises runtime source to 210, test modules to 116,
collected tests to 932, and ADRs to 71; schema and workflow counts remain 49
and six.

E-057 routes FI-011 close checklist JSON and JSON/YAML templates through the
same structured-document policy, adds one dedicated test module with ten
hostile/compatibility cases, and adds ADR 0072. Runtime source remains 210;
test modules rise to 117, collected tests to 942, and ADRs to 72; schema and
workflow counts remain 49 and six.

E-058 routes the FI-012 client-pack manifest and evidence-index JSON readers
through the structured-document policy while retaining the redaction/copy
compatibility paths as partial. It adds one dedicated test module with ten
hostile cases and ADR 0073. Runtime source remains 210; test modules rise to
118, collected tests to 952, and ADRs to 73; schema and workflow counts remain
49 and six.

E-059 adds an exact-float-lexeme mode to bounded JSON parsing and routes FI-012
client-pack JSON redaction through it with preflight before fingerprint hashing
or destination preparation. It adds one dedicated test module with six hostile
integration cases plus one shared-reader case and ADR 0074. Runtime source
remains 210; test modules rise to 119, collected tests to 959, and ADRs to 74;
schema and workflow counts remain 49 and six.

E-060 routes FI-012 CSV redaction through tabular preflight, rejects duplicate
headers, and streams exact field strings through per-file temporary replace. It
adds one dedicated test module with ten hostile/compatibility/rollback cases and
ADR 0075. Runtime source remains 210; test modules rise to 120, collected tests
to 969, and ADRs to 75; schema and workflow counts remain 49 and six.

E-061 freezes and resource-bounds FI-012 candidate/selected source sets, streams
strict generic text and bounded non-redacted bytes, bounds output verification,
and builds the complete pack in a sibling staging directory with handled-failure
rollback. It adds one dedicated test module with 17 hostile/resource/race/
publication/compatibility cases and ADR 0076. Runtime source remains 210; test
modules rise to 121, collected tests to 986, and ADRs to 76; schema and workflow
counts remain 49 and six.

E-062 adds a schema-v1 path-minimized local marker and explicit recovery CLI for
the existing-output two-rename window. Exact sibling names and bounded
previous/staged tree digests feed a four-state allowlist; missing, multiple,
tampered, changed, reparse, unknown-sibling, and ambiguous states fail closed.
The marker is explicitly unkeyed/self-consistency only, and simulated abrupt
loss is not real host/filesystem durability evidence. Thirteen dedicated cases
and ADR 0077 cover this bounded recovery slice. Runtime source remains 210; test
modules rise to 122, collected tests to 999, and ADRs to 77; schema and workflow
counts remain 49 and six.

E-063 bounds the actual FI-009 two-file database restore contract without
inventing an archive format. The named profile rejects reparse/non-regular,
unstable, oversized, duplicate-key, non-finite, over-depth/width/node/scalar,
and structurally open JSON before target preparation; the closed manifest binds
the sole `backup.json` artifact by bytes and unkeyed SHA-256. Nineteen dedicated
hostile/compatibility/schema cases, two JSON schemas, and ADR 0078 cover the
slice. Runtime source remains 210; test modules rise to 123, collected tests to
1,018, schemas to 51, and ADRs to 78; workflow count remains six. The separate
database importer JSON reader remains outside the shared policy.

E-064 bounds the remaining FI-009 account/control import JSON reader under a
named stable-read profile, rejects duplicates/non-finite/resource excess and
ambiguous or silently-empty envelope shapes before database inspection, and
retains parsed-byte digest/size/profile evidence. Twenty-five dedicated cases,
two compatibility schemas, and ADR 0079 cover direct-list, single-envelope,
keyed-map, TOCTOU, reparse, and pre-mutation behavior. Runtime source remains
210; test modules rise to 124, collected tests to 1,043, schemas to 53, and ADRs
to 79; workflow count remains six. FI-009 parser coverage is bounded, while
record semantics and operational authorization/encryption/malware/DR controls
remain outside that result.

E-065 adds `reconforge/io/records.py`, routes the inventoried FI-008 consumers
through its bounded exact-text CSV/JSON document, and adds one dedicated module
with 21 cases plus one updated strict-matching regression and ADR 0080. Runtime
source rises to 211, test modules to 125, collected tests to 1,064, and ADRs to
80; schemas remain 53 and workflows remain six.

E-066 adds `reconforge/io/generated.py`, routes every FI-007 Studio CSV/JSON
view through stable bounded readers, and adds one dedicated module with 24
hostile/resource/TOCTOU/companion/display/route/AST cases plus ADR 0081.
Runtime source rises to 212, test modules to 126, collected tests to 1,088, and
ADRs to 81; schemas remain 53 and workflows remain six.

## Runtime and interface surfaces

- `reconforge/cli.py`: Typer CLI and compatibility surface.
- `reconforge/api/`: FastAPI app, local routes, and optional server-profile boundaries.
- `reconforge/studio/`: current local/server-rendered Studio surfaces.
- `apps/web/`: experimental React/Vite/TypeScript read-only Studio; package-lock present.
- `reconforge/dashboard/`: dashboard compatibility layer.

## Domain and application surfaces

- `reconforge/platform/`: application services for accounts, close, controls, evidence, exceptions, finance, inventory, matching, AP/AR, metrics, and outbox.
- `reconforge/reconciliation/`: stock/GL and work-order reconciliation, matching, and risk.
- `reconforge/config.py`: exact Decimal runtime configuration with explicit legacy/strict YAML ingress through the bounded structured-document policy; current callers preserve decimal lexemes before validation, while direct Python defaults remain compatibility readers.
- `reconforge/rules/`: bounded declarative rule evaluation and Reconciliation-as-Code YAML parsing with explicit strict/legacy financial ingress, normalized executable-pack/input/decision provenance, and historical/current result readers; broader reconciliation-as-code remains a foundation.
- `reconforge/workflow/`, `reconforge/review/`, `reconforge/close/`: workflow and close-state foundations; current review/period callers preserve exact exception lexemes and period-comparison v2 records bounded input/digest provenance while direct Python defaults remain legacy readers.
- `reconforge/domain/`: domain models plus repository protocols; migration toward the target modular-monolith layers is partial.

## Data, persistence, and jobs

- `reconforge/db/`: SQLite schema/migrations, import/export, backup/restore, optional authenticated backup encryption, and tenant routing helpers. Database import and restore JSON use separate named, bounded, strict, duplicate-safe profiles; malware scanning, managed key lifecycle, and complete DR remain gaps.
- `alembic/versions/`: 11 optional PostgreSQL server-profile migrations.
- `reconforge/infrastructure/`: PostgreSQL repositories, Redis coordination, and object-storage adapters.
- `reconforge/workers/`: outbox and PostgreSQL reconciliation workers.
- `reconforge/engines/`: Pandas and optional DuckDB execution plus reconciliation signatures.

## Evidence, security, and extension surfaces

- `reconforge/evidence/`: evidence binder, strict/legacy CSV ingress, v2/v3 evidence-index compatibility/verification, checksum manifest, and graph foundation.
- `reconforge/auth/`, `reconforge/audit/`: local identity/RBAC/policy and append-oriented audit foundations.
- `reconforge/plugins/`: file/export-profile adapters. These are not proven live ERP connectors.
- `reconforge/io/`: versioned bounded tabular, structured-document, business-record, and generated-artifact ingress for the inventoried protected paths, including FI-005/FI-006/FI-007/FI-014, FI-011 close files, and two FI-012 manifests. FI-012 JSON/CSV/text/non-redacted client-pack copies additionally use frozen resource budgets, bounded output recheck, full-pack sibling staging, and handled-failure rollback; Windows existing-directory crash recovery and legacy XLS remain explicitly partial.
- E-067 extends generated-artifact CSV documents with recorded display/exact-text modes and routes FI-006 variance CSV/JSON plus management-report JSON through the same bounded, stable-byte helper. Studio retains display inference; variance preserves source lexemes before Decimal validation. FI-005 remained partial at that slice boundary and is addressed by E-068 below.
- E-068 routes FI-005 evidence/review CSV through those explicit modes, caches each selected binder CSV once, derives evidence-index v3 CSV fingerprints from the parsed document, and verifies its stable bytes before publication.
- E-069 inventories FI-014 and routes `review_state.json` through a narrower bounded, duplicate-safe, stable-byte generated-local JSON profile while preserving valid historical direct-map/envelope entry coercion. Malformed present input is no longer hidden as empty state.
- E-070 adds an exact direct-JSON AST allowlist, classifies all 14 remaining stdlib calls as central/persisted/package-text paths, and removes all six direct filesystem calls. FI-015 generated report/workflow/demo readers use bounded stable display-number compatibility; FI-016 user-selected exception explanation uses a narrower bounded profile and path-free errors. Exact-text remains the default for current financial JSON readers.
- E-071 adds `reconforge/io/persisted.py` and a recursive AP/AR idempotency response schema. Both producers and consumers share canonical integer-token-only JSON and fixed byte/graph ceilings; the exact direct-JSON allowlist contracts from 14 to 12 calls while FI-013 remains partial for ten direct stored-value decoders.
- E-074 adds one recursive PostgreSQL reconciliation object schema and four field-specific persisted profiles. Rule, attributes, lineage, and evidence producers plus repository/worker consumers share canonical finite object and graph budgets; attributes preserve the prior 100000-byte limit. Three reconciliation calls leave the direct-JSON allowlist, leaving five total calls: three FI-013, one central bounded parser, and one packaged registry parser.
- E-075 adds one recursive SQLite matching-rule schema and named persisted profile. One pre-transaction encoding is shared by both rule table writes; replay and job readers enforce the same finite object/graph budget while preserving historical spaced text and missing-policy defaults. The matching call leaves the direct-JSON allowlist, leaving four total calls: two FI-013, one central bounded parser, and one packaged registry parser.
- E-076 adds one closed Redis session schema and named persisted profile. The optional tenant store validates four bounded strings, a token digest, and explicit UTC expiry before client access/read use while preserving compact producer text, tenant key hashing, TTL, missing-key, and ID-match behavior. The Redis call leaves the direct-JSON allowlist, leaving three total calls: one FI-013 generic export, one central bounded parser, and one packaged registry parser.
- E-077 inventories all five public SQLite export `_json` fields, reuses audit/rule profiles, adds legacy-summary and matching-lineage producer/consumer profiles, and validates every payload before destination creation while preserving all format-v1 shapes. The exporter leaves the direct-JSON allowlist; two calls remain repository-wide: the central bounded parser and packaged currency registry, neither an FI-013 direct decoder.
- E-078 adds a deterministic tenth `export_manifest.json`, same-parent staged directory publication, bounded rollback markers, and explicit recovery. The nine format-v1 documents and field shapes remain unchanged; the schema and publication regression contract are source-distribution artifacts and ADR 0093 is repository-only.
- E-079/P0-SEC-010 closes the local authorization property gate: `auth/policy.py` requires a named permission and exact supplied scope grants; `auth/rbac.py` centralizes actor equality; an exact nine-method platform approval/review inventory plus generated scope/ownership and integration contracts cover generic, workflow, AP/AR, account, certification, count, valuation, and reversal SoD. ADR 0094 records the intentional self-approval/override tightening.
- E-082/P0-005 closes implicit financial compatibility defaults: 52 `FinancialInputPolicy` defaults across 23 runtime files now select strict v2, `Money` scalar operators reject binary floats, explicit/versioned historical readers retain legacy replay, and the sdist includes the migration guide plus the repository-wide default regression. ADR 0097 and the changelog mark the direct-Python break.
- `control-packs/`: YAML mappings, rules, risk models, expected-exception documentation, and sample commands.
- `docs/security/`: 15 security/operations Markdown documents plus normative Security Architecture v2, module threat-model, scoped ASVS 5.0.0, all-task NIST SSDF 1.1, SLSA 1.2 provenance-plan, file-ingestion inventory YAML registries, and closed JSON supply-chain policy/exception registries.

## Contracts and delivery

- `docs/schemas/`: 64 JSON schemas, including matching-strategy and backup/restore manifests, field-specific persisted JSON, database backup/import, file-ingestion, evidence/report compatibility, release/SBOM/supply-chain, golden-data, risk/maturity/engine, security/threat/ASVS/SSDF/SLSA, browser, and module contracts.
- `tests/golden/`: schema-validated synthetic finance registry and five frozen registry/input files with layered SHA-256 evidence, including bounded dense ambiguity; these are correctness fixtures, not performance datasets.
- `docs/risk-register.yaml`: normalized 18-risk governance source with schema/rating/evidence/review validation; the Markdown register remains its readable narrative view.
- `docs/execution/MATURITY_POLICY.yaml`: evidence-linked ceilings for all nine modules and seven designated publishing surfaces; all current modules are Experimental.
- `docs/security/security-architecture.v2.yaml`: schema-v2 source of truth for bounded deployment-mode labels, data classes, trust boundaries, evidence-linked controls, owners, and normalized residual risks; it is not operating-effectiveness or compliance evidence.
- `docs/security/threat-model-index.v1.yaml`: exact active-module threat coverage joined to the module registry, architecture controls, and normalized risks; it is not penetration-test or deployed mitigation evidence.
- `docs/security/asvs-5.0.0-mapping.v1.yaml`: official-source-pinned scoped mapping for 55 selected OWASP ASVS 5.0.0 requirements across all 17 chapters, with 290 requirements explicitly unassessed; it establishes no ASVS level or compliance assurance.
- `docs/security/nist-ssdf-1.1-mapping.v1.yaml`: official-final-source-pinned mapping for all 42 NIST SSDF 1.1 tasks with architecture owners, bounded evidence, gaps, actions, and review cadence; it establishes no SSDF conformance or operating-process assurance.
- `docs/security/slsa-provenance-plan.v1.yaml`: Approved-SLSA-1.2-pinned plan for five artifact identities, seven trust boundaries, attestation/verification/failure/rollback contracts, and 12 gates; both tracks remain UNEVALUATED.
- `.github/workflows/`: CI, CodeQL, Docker, security, release candidate with integrated exact-subject SBOMs, and OpenSSF Scorecard workflows; action references observed in the workflows are pinned by full commit SHA.
- `Dockerfile`: digest-pinned Python 3.11 slim base plus checksum/version-pinned uv and a locked non-editable runtime-only sync; local daemon verification is blocked in this environment.
- `docker-compose.yml`: local report/dashboard services; image tag is mutable.
- `pyproject.toml` + `uv.lock`: lower-bounded consumer metadata plus a universal hash-bearing repository resolution for 118 non-root runtime/server/observability/backup/federation/build/tool packages, enforced with exact uv/cutoff policy; server includes boto3, observability pins OpenTelemetry API/SDK 1.44.0, backup pins cryptography 49.0.0, and federation pins joserfc 1.7.4 plus python3-saml 1.16.0.
- `apps/web/package-lock.json`: exact npm dependency versions for the web app; 155 non-root entries lack embedded `resolved`/`integrity` values and remain an explicit gap.

## Important inventory limitations

- The current worktree combines multiple architectural slices and execution documents rather than one isolated vertical slice.
- Presence in this inventory is not maturity evidence. PostgreSQL, Redis, object-storage, AI, evidence-graph, or industry files must not be described as production-ready without their relevant runtime and release gates.
