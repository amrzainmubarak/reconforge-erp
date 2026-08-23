# Quality Baseline

## E-845 hosted worker permission separation gate (2026-08-23)

Hosted deployment profiles now require an explicit runtime fact proving worker
discovery/execution permission separation. Community remains local-compatible.
Focused profile tests pass 9/9; Ruff, Mypy, and whitespace checks pass.
Full `python -m pytest -q` on the resulting tree exits 0 over 3,119 tests.

## E-844 reconciliation discovery/execution permission split (2026-08-23)

Workers can now use a dedicated least-privilege discovery permission while
retaining `match.run` for claim/execution; the legacy fallback remains explicit.
Focused tests pass 33/33 with one live-PostgreSQL skip; Ruff, Mypy, and
whitespace checks pass. Full `python -m pytest -q` on commit `7f44db68` exits 0
over the 3,119-test collection.

## E-843 reconciliation worker amount-policy propagation (2026-08-23)

The worker now receives the persisted exact exposure from run rule metadata and
passes it through tenant and pre-claim scoped policy checks. Focused API/worker/
policy tests pass 32/32 with one live-PostgreSQL skip; Ruff, Mypy, and
whitespace checks pass. Full `python -m pytest -q` also exits 0 over the
3,119-test collection. Discovery-lane universal coverage remains open.

## E-842 reconciliation submission amount ABAC (2026-08-23)

Reconciliation run submission now passes the gross absolute exact Decimal sum
of complete canonical input amounts before server authorization. Missing input
amounts remain `None` for bounded-policy fail-closed behavior. Focused API tests
pass 3/3; Ruff, Mypy, and whitespace checks pass. A full pre-slice regression
completed with exit code 0 over 3,119 collected tests.

## E-841 ownership-change route amount ABAC (2026-08-23)

Ownership-change preparation supplies exact gross exposure before persistence:
absolute ownership-delta effect plus consideration effect. Focused tests pass
19/19 with one live-PostgreSQL skip; Ruff, Mypy, and whitespace checks pass.
This is not universal adoption.

## E-840 PPA route amount ABAC (2026-08-23)

PPA preparation now supplies consideration plus NCI fair value as exact gross
Decimal exposure before persistence, without double-counting allocation items.
Focused route/domain tests pass 16/16; this is not universal adoption.

## E-839 deferred-tax route amount ABAC (2026-08-23)

Deferred-tax preparation now supplies gross absolute fair-value exposure as an
exact Decimal to server policy before persistence, without double-counting tax
basis. Focused route/domain tests pass 15/15; this is not universal adoption.

## E-838 intercompany route amount ABAC (2026-08-23)

Intercompany preparation now supplies gross absolute typed Money exposure as an
exact Decimal to server policy before persistence. Focused route/domain tests
pass 15/15; this is not universal route adoption.

## E-837 Finance Core route amount ABAC (2026-08-23)

The two PostgreSQL Finance Core entry branches now pass an exact gross debit
Decimal into server policy before adapter access and reject malformed/negative
amounts. Focused server-core/dependency tests pass 11 cases with one declared
capability skip. This is not universal route adoption.

## E-836 route-level amount ABAC (2026-08-23)

The PostgreSQL consolidation impairment prepare route now supplies the exact
Decimal total of typed carrying amounts to server policy evaluation before
persistence. Route/policy/dependency focused tests pass 90/90. This is one
high-risk route binding, not universal route adoption.

## E-835 bounded amount ABAC (2026-08-23)

The central policy engine now fails closed when an amount floor or ceiling is
configured without an exact finite Decimal amount. The focused policy suite
passes 80/80, with exact boundary behavior retained. This is a primitive-level
authorization improvement, not universal enterprise IAM evidence.

## E-834 durable recovery observation persistence (2026-08-22)

The recovery observation is now a versioned, digest-bound durable record with
SQLite migration 43 and PostgreSQL revision 0090. Focused connector/API,
migration, and repository tests pass 66/66; `mypy reconforge` passes across 526
source files. The SQLite/PostgreSQL 16.14/17.10 disposable matrix produced one
identical records digest and verified replay idempotency, append-only refusal,
scope isolation, and role restrictions. This is bounded synthetic quality on
one Docker host, not live-provider or production quality.

The post-fix full Python gate passes 2996/2996 executed tests with 115 declared
skips. Mypy, build, Bandit, Ruff, diff-check, and pip-audit are green; pip-audit
was rerun after upgrading the local tool from 26.1.2 to 26.2.

## E-833 provider status taxonomy (2026-08-22)

Recovery status evidence is now explicit and non-mutating. The classifier
distinguishes accepted, rejected, pending, not-found, and unknown responses;
only accepted can create an acknowledgement. Frozen observations bind the
original key and raw/response/observation digests. The focused connector
transport/domain selector passes 55/55, including legacy response compatibility,
pending refusal, key mismatch, retries, TLS, and sandbox paths. This is bounded
synthetic quality, not live-provider or production quality.

## E-832 negative provider outcome guard (2026-08-22)

The original dispatch and idempotency-status recovery paths now refuse a
well-formed provider response with `accepted=false` before any lifecycle state
can advance. The intent remains `DISPATCHED` and has no acknowledgement; the
compensation rejection guard remains unchanged. The focused connector
transport/domain selector passes 46/46, including TLS, retry, digest, secret,
idempotency, recovery, and compensation contracts. This is local synthetic
transport quality, not provider or production quality.

## E-831 write-back recovery and compensation parity (2026-08-22)

The closed runner proves the six-version append-only lifecycle on a SQLite
reference and exact PostgreSQL 16.14/17.10 cells. Two spawned acceptance-before-
persistence crash windows recover through the original and distinct compensation
idempotency keys exactly once. Sixteen checks per PostgreSQL cell and thirteen
SQLite checks pass, including direct mutation refusal, tenant isolation,
non-privileged role flags, history parity, schema/source binding, cleanup, and
six negative evidence mutations. The focused report/supply-policy selector
passes 37/37. This is bounded synthetic single-host quality, not live-provider,
accounting, settlement, distributed HA, or production quality.

## E-830 synchronous receiver failover verification (2026-08-22)

One closed runner executes the same receiver fault sequence on exact
PostgreSQL 16.14/17.10 two-node topologies. Direct `SyncRep` observation,
fencing-before-promotion, response-loss replay, controller-paused re-seed,
synchronous rejoin, uncertain identity resolution, promoted-primary restart,
endpoint rediscovery, and SQLite parity pass. Every cell has 23 true checks,
two receipts/effects, non-privileged role flags, RPO 0 for its acknowledged
synthetic effect, and local RTO below 60 seconds. The schema and six negative
mutations refuse false, expanded, or drifted evidence. Five failed development
attempts produced no retained report and exposed verifier flaws that are now
bounded and regression-tested through the final full rerun. The focused
report/supply-policy selector passes 37 tests; Ruff, Mypy, Bandit, JSON/YAML,
closed policy, and whitespace gates pass. An initial full regression exposed
and rejected an invalid E-228 standalone backlog dependency; the corrected
15-test selector passed, followed by a fresh full run of 2,970 passed, 115
declared capability skips, and 23 existing warnings across 3,085 tests in
531.47 seconds. Full Ruff, 525-file Mypy, Bandit, supply policy, lock, isolated
Python 3.12 audit, JSON/YAML, build, package membership, and whitespace gates
pass. The 1,768-entry sdist contains all five E-830 evidence assets; the
runtime-only wheel remains 625 entries. Ambient pip-audit separately retains
the host pip vulnerability. Gitleaks 8.30.1 reports no findings across 663
commits / 25.28 MB or a clean 27.71 MB implementation archive; the exact
temporary artifacts were removed. This is bounded single-host topology
quality, not automatic or production HA quality.

## E-829 PostgreSQL receiver idempotency parity (2026-08-22)

The additive PostgreSQL backend shares the exact closed E-828 request,
response, conflict, and canonical-history logic. Constructor tests close DSN
and timeout boundaries; structural tests bind the unambiguous receiver/key lock
identity, digest-only schema, composite keys, foreign key, immutable triggers,
and lazy dependency failure. The live 16.14/17.10 matrix passes 17 checks per
cell under non-privileged roles, including eight-process contention,
crash-after-commit, direct mutation/malformed-input refusal, native backup,
independent restore, and exact cleanup. Both PostgreSQL histories equal the
SQLite canonical history. The retained report passes its closed schema,
canonical/source/policy/image binding, package/workflow contracts, and negative
mutations. The focused 33 tests pass. The final full regression collects 3,075
tests: 2,960 pass, 115 declared capability skips remain visible, and 23 existing
warnings remain visible in 716.62 seconds. Full-tree Ruff, Mypy across 525
source files, Bandit, closed policy, lock, isolated Python 3.12 audit,
JSON/YAML, build, package membership, and whitespace gates pass. The 1,763-entry
sdist and 625-entry wheel contain all intended E-829 assets. Ambient pip-audit
separately retains the host pip vulnerability rather than replacing the clean
locked audit. Gitleaks 8.30.1 reports no findings across 662 commits / 25.18 MB
or the clean 27.62 MB implementation archive. This is bounded single-host
synthetic conformance, not provider, distributed, accounting, HA/DR, or
production quality.

## E-828 receiver-side idempotency conformance (2026-08-22)

The additive receiver model is closed and digest-deterministic. Unit and
property tests cover malformed identities, permutation-stable request digests,
payload separation, exact sequential replay, key retargeting refusal, database
immutability, six-process contention, and crash-after-commit replay. The closed
runtime drill strengthens contention to eight spawned processes, validates an
independent backup/restore, binds source and report digests, and verifies exact
cleanup. The 85-test receiver/report/network/SDK/package selector, Ruff, and
Mypy pass. The full regression collected 3,058 tests: 2,943 passed, 115 declared
capability skips, and 23 existing warnings in 396.97 seconds. Ruff, Mypy across
524 source files, Bandit, policy/lock/isolated-audit gates, JSON/YAML parsing,
build, package membership, and whitespace checks pass. The 1,756-entry sdist
and 624-entry wheel contain the receiver assets. Ambient pip-audit separately
reports the host's pip vulnerability; the locked audit reports zero findings.
This is same-host SQLite correctness evidence, not distributed or provider
production quality.

## E-827 PostgreSQL migration matrix verification (2026-08-22)

The same strict observation function passes on digest-pinned PostgreSQL 16.14
and 17.10 in 24.178 seconds. Each cell passes all ten checks and cleanup; their
canonical valid and invalid histories are identical. The retained matrix passes
its closed Draft 2020-12 schema, canonical report digest, source/policy binding,
cross-cell parity, negative-schema cases, package manifest, and CI workflow
contracts. The final regression collected 3,042 tests: 2,927 passed and 115
declared capability skips, with 23 existing warnings in 410.54 seconds. Ruff,
Mypy across 523 source files, Bandit, JSON/YAML parsing, the closed policy
validator, `uv lock --check`, isolated Python 3.12 locked dependency audit,
build, package membership, and whitespace checks pass. The 1,749-entry sdist
contains the new matrix materials; the 623-entry wheel retains Alembic 0089.
Ambient `python -m pip_audit` separately reports host-installed `pip 26.1.2`
under `PYSEC-2026-3721`; the isolated locked audit reports zero findings.

## E-826 migration failure/recovery verification (2026-08-22)

The retained PostgreSQL 17.10 Docker drill passes all ten closed checks: native
pre-drift dump listing, drifted-history upgrade refusal, unchanged revision,
history and trigger after refusal, independent restore, successful 0089 upgrade,
unchanged valid history, enhanced direct-INSERT refusal, and exact-container
cleanup. Its Draft 2020-12 schema, canonical report digest, runner/migration
source binding, runtime identity tests, Ruff, and Bandit pass. Three earlier
runner attempts exposed missing synthetic `created_at`, tenant, and migration
path fixtures, failed without replacing the retained artifact, and cleaned their
disposable containers; they are retained as development findings rather than
converted into successful evidence. The final full suite collects 3,032 tests:
2,917 pass, 115 declared capability skips remain visible, and 23 existing
warnings remain visible. The focused E-825/E-826 selector passes 88 tests with
four declared live-service skips; the report/policy/parity selector passes
44/44. Ruff, Mypy across 523 files, Bandit, the closed supply-chain policy,
lock check, isolated locked audit, build, package-content checks, changed
JSON/YAML validation, and whitespace checks pass.

## E-825 write-back proposal identity verification (2026-08-22)

Focused domain, SQLite runtime, PostgreSQL contract, Alembic-chain, operations,
and authenticated API tests pass, including adversarial proposal-field drift,
direct INSERT state jumps, and fail-closed SQLite upgrade. A digest-pinned
PostgreSQL 17.10 runtime passes both live write-back histories under a
non-superuser/NOBYPASSRLS role, and a separate isolated database passes three
head upgrades around two deep downgrades. Ruff, Mypy, and whitespace gates
pass. A temporary-table regression proves the SQLite audit does not collide
with same-named main-database data. The full post-slice regression collects
3,027 tests and passes 2,912 with 115 declared capability skips; Bandit, the
closed supply-chain policy, lock check, and package build pass. Provider
behavior is not promoted by this local contract evidence.

## Current developer bootstrap verification (2026-08-22)

E-821 adds a read-only developer Doctor and a non-destructive, locked,
platform-specific bootstrap. On the current Windows host it detected and
preserved a foreign Linux `.venv`, created an ignored Python 3.12
`.venv-windows`, ran product Doctor, passed a repeated idempotent bootstrap, and
then reported `DEVENV-READY`. Its interpreter collected 2,981 tests and carried
the full suite to 100% with every executed test passing and capability skips
remaining explicit. This is local developer-environment evidence only; it does
not replace clean-host, hosted, macOS/Linux, proxy/private-index, air-gap,
installer, or production deployment verification.

## Current post-E-400 verification (2026-08-05)

The current head has a full local post-IAM gate: `uv run pytest -q --tb=short`
exits 0 in 318.9 seconds; Ruff, Mypy (447 source files), Bandit, pip-audit,
`python -m build --no-isolation`, and `git diff --check` also pass. Existing
warnings and declared optional-service skips remain visible. This current local
gate does not replace hosted Python/web/container execution, external-provider
contracts, independent HA/DR, or production-release evidence.

Measured through 2026-07-27 on the dirty snapshot in `BASELINE.md` and `STATE.md`.

| Gate | Initial baseline | Post-remediation result |
| --- | --- | --- |
| Ruff | Fail: 7 findings | Pass: locked Ruff 0.16.0, full-tree E-061 run in 2.27s before temporary cleanup |
| Mypy | Fail: 2 errors | Pass: locked Mypy 2.3.0, 0 issues in 210 source files, 3.17s E-061 run |
| Pytest | Fail: 626 passed, 10 skipped, 1 failed | Pass: locked supported Python 3.11.15, 1,274 collected, 1,264 passed, 10 skipped, 0 failed/errors, 235.317s JUnit / 237.337s wrapper in final E-078; SHA-256 `9f1c23fd881d1ded25cfa03d629bf3ff555512552f491f769ef9a3311c3d7a9b` |
| Git whitespace | Fail: 3 findings | Pass: 0 findings in the final E-061 verification; existing `.gitignore` line-ending warning only |
| Package build | Pass | Pass: final locked Python 3.11 `--no-isolation`, 474-entry sdist and 220-entry wheel. E-078 exporter/CLI runtime are in wheel/sdist; manifest schema and dedicated test are sdist-only; ADR 0093 is repository-only. Existing setuptools warnings remain |
| Web install/typecheck | Pass | Pass: `npm ci` installed 158 packages with zero reported vulnerabilities; typecheck passed |
| Web unit tests | Pass: 17/17 | Pass: 17/17 |
| Web production build | Pass | Pass: Vite 8.1.5 production build |
| Web E2E | Pass: 2/2 | Pass: 2/2 Playwright tests |

## Test-boundary notes

- A read-only GitHub audit on 2026-07-25 found no remote `engine-parity` job because its four-cell definition remains an uncommitted local workflow change. Draft PR #54 run `30073610042` at `45c6573` passed its general Python 3.11/3.12 and Docker jobs but failed server-boundary collection because referenced tests were absent. Local HEAD `bdf63de` adds those files but is one commit ahead of the remote branch; no rerun/fix claim is allowed.
- The Windows global pytest temporary directory produced an earlier real product failure after a local-base retry, became unreadable again during E-023, and denied fixture setup during E-035's first combined targeted run. Each identical affected suite and the final full suite passed with distinct repository-local `--basetemp` paths. During E-052, tracked root files `alembic.ini` and `CONTRIBUTING.md` disappeared between checks; the first full run therefore ended with two missing-file failures. They were restored through `apply_patch` from exact `HEAD` content, Git reported no remaining diff for either, the affected target passed, and the full 866-test rerun passed. The incident is retained as environment/worktree evidence, not hidden by a retry-until-pass claim.
- Ten skips are environment/optional-service guards, including live PostgreSQL, Redis, object storage, and optional integrations. A skip is not runtime evidence.
- The final E-052 run has eight warnings: one existing Starlette deprecation and seven uncaptured call-site-deduplicated legacy-financial-input warnings. E-052 adds no runtime warning. These warnings are migration evidence, not a passing quality claim.
- The final post-hardening E-053 full run has the same eight warnings and ten skips. Its dedicated basetemp was resolved and verified as an ordinary directory inside the repository before removal; Ruff and `git diff --check` then passed. An earlier post-suite Ruff command had inspected the intentionally extracted clean-HEAD research snapshot under `.codex-test-tmp` and reported two historical import-order findings there; after all verified research fixtures were removed, Ruff passed the actual worktree. No source file was changed to make either gate pass.
- The final E-054 run uses supported Python 3.11.15 and the exact all-extra `uv.lock` resolution. Python 3.12, hosted execution, and cross-platform lock installation remain unverified; one supported local profile does not replace those gates.
- E-054 retains ten skips and eight warnings: one Starlette/httpx transition warning plus seven legacy-financial-input migration warnings. Neither is hidden or counted as evidence for the skipped live-service paths.
- The first E-056 full invocation lost its tool-session handle after starting and later exited without a recoverable summary; it is not evidence. A separate fresh-basetemp run retained the session and JUnit result: 932 tests, 0 failures/errors, 10 skips, and eight existing warnings in 353.63s. The three malformed-value conversion regressions added after initial collection explain the increase from 929 to 932.
- E-056 retains the same one Starlette/httpx deprecation plus seven call-site-deduplicated legacy-financial-input warnings. Its 32-test structured-ingress/inventory target also passes on ambient Python 3.14.6; a second full 3.14 suite was not run and is not implied.
- E-057 adds ten FI-011 close-workflow structured-ingress cases. The retained Python 3.11 JUnit records 942 tests, zero failures/errors, ten skips, and 361.795s test time; the wrapper records 363.79s and the same eight warnings. Its 42-test structured/close/inventory boundary target passes on Python 3.11.15; no E-057 full Python 3.14 or Python 3.12 hosted run is implied.
- E-058 adds ten FI-012 generated-manifest structured-ingress cases. The retained Python 3.11 JUnit records 952 tests, zero failures/errors, ten skips, and 393.023s test time; the wrapper records 395.36s and the same eight warnings. Its 52-test structured/close/generated-manifest/inventory boundary target passes on Python 3.11.15; no E-058 full Python 3.14 or Python 3.12 hosted run is implied.
- E-059 adds one shared exact-float-lexeme contract and six FI-012 JSON-redaction integration cases. The retained Python 3.11 JUnit records 959 tests, zero failures/errors, ten skips, and 393.67s test time; the wrapper records 395.94s and the same eight warnings. Its 59-test combined boundary and 55-test focused compatibility targets pass on Python 3.11.15; the focused 55 also passes on ambient Python 3.14.6. No E-059 full Python 3.14 or Python 3.12 hosted run is implied.
- E-060 adds ten FI-012 CSV-redaction ingress, compatibility, streaming, and rollback cases. The retained Python 3.11 JUnit records 969 tests, zero failures/errors, ten skips, and 385.117s test time; the wrapper records 387.42s and the same eight warnings. Its 85-test combined boundary passes on Python 3.11.15; the 53-test focused target passes on Python 3.11.15 and ambient Python 3.14.6. No E-060 full Python 3.14 or Python 3.12 hosted run is implied.
- E-061 adds 17 FI-012 traversal, text/copy budget, race, output-verification, nested-demo compatibility, staging, and rollback contracts. The first full run exposed two real regressions—nested demo output was rejected and excluded raw records disappeared from the manifest—and ended with 972 passes, two failures, ten skips, and eight warnings. Frozen candidate/selected sets and a constrained nested-output policy fixed both; the affected 46-test target passed, and the retained final Python 3.11 JUnit records 986 tests, zero failures/errors, ten skips, and 371.62s test time. The wrapper records 373.85s and the same eight warnings. Its 102-test combined boundary and 80-test focused targets pass on Python 3.11.15; the focused 80 also passes on ambient Python 3.14.6. No E-061 full Python 3.14 or Python 3.12 hosted run is implied.
- E-062 adds 13 explicit client-pack publication recovery contracts covering all four accepted filesystem states, path-minimized marker integrity, marker/tree tamper, missing/multiple/unknown siblings, reparse refusal, fresh-output sibling refusal, successful cleanup, CLI output, and generator-unwinding staging preservation. One in-progress full run was deliberately invalidated and stopped after a review found the generator-finally gap; it is not evidence. The retained fixed-snapshot Python 3.11 JUnit records 999 tests, zero failures/errors, ten skips, and 362.142s test time; the wrapper records 364.98s and the same eight existing warnings. The final 83-test locked focused target records 23.124s. No real process kill, host/power/filesystem loss, full Python 3.14, or Python 3.12 hosted result is implied.
- E-063 adds 19 FI-009 backup/manifest ingress contracts covering duplicate keys, invalid UTF-8, non-finite values, size/depth budgets, closed documents, strict integer versions, registered tables, checksum/byte/schema agreement, generated-schema validation, TOCTOU mutation, reparse refusal, destination non-mutation, and direct-parser AST drift. The retained Python 3.11 JUnit records 1,018 tests, zero failures/errors, ten skips, 363.317s test time, and the same eight existing warnings; its SHA-256 is `613751c4e1af3bbd923ac564b0f7bcc64e04be81f063fe436b0b1f07a3bf7755`. The focused 28-test target also passes. No archive parser, importer coverage, real host loss, full Python 3.14, or Python 3.12 hosted result is implied.
- E-064 adds 25 FI-009 legacy-import contracts covering strict duplicate/non-finite/encoding behavior, byte/node/depth/collection/scalar budgets, reparse and TOCTOU refusal, ambiguous and previously silently-empty objects, direct-list/single-envelope/keyed-map compatibility, parsed-byte digest/size/profile evidence, published-schema parity, pre-mutation behavior, and direct-parser AST drift. The retained Python 3.11 JUnit records 1,043 tests, zero failures/errors, ten skips, 192.422s test time, and the same eight existing warnings; its SHA-256 is `5efa4166dc4a329a658a1aa24299e5651f01c4c1b8946a1b883f2d112ec49f5a`. The 76-test locked importer/governance target passes in 14.973s with SHA-256 `52b94da2234f96d64e5afcaa4dba23a27ab4621e570f433673b6ec3030142777`. No full semantic import validation, source authentication, centralized authorization, malware scan, real DR, full Python 3.14, or Python 3.12 hosted result is implied.
- E-072 adds eight dedicated audit-metadata contracts plus SQLite/PostgreSQL/export integration cases for canonical-byte compatibility, finite display-number compatibility, duplicates/non-finite/non-object/cycles, resource rejection before SQLite mutation, explicit list/verifier failure, PostgreSQL JSONB hash reconstruction, and pre-write export refusal. The retained locked Python 3.11 JUnit records 1,179 tests, 1,169 passes, zero failures/errors, ten skips, 210.46s, and the same eight warnings. Live PostgreSQL remained skipped and is not implied.
- E-073 adds thirteen PostgreSQL outbox producer/consumer/claim/AST contracts and closes the three PostgreSQL audit-writer call sites omitted from E-072. The focused JUnit records 103 tests, 99 passes, zero failures/errors, four service skips, 10.493s, and SHA-256 `06e009755b51dc9227391e6ce61434e90d50172fedecd09f7a32756a63e91dce`. The retained full Python 3.11 JUnit records 1,192 tests, 1,182 passes, zero failures/errors, ten skips, 332.375s, the same eight warnings, and SHA-256 `3cb0cb25e0e8c37d9740eafaa7e5d91d3f66c81f5b1ce0a5908aec33942021e1`. Live PostgreSQL and an external publisher remained unexercised and are not implied.
- E-074 adds 28 PostgreSQL reconciliation rule/attributes/lineage/evidence producer-consumer, schema, hostile/resource, pre-SQL/pre-hash, canonical-fingerprint, worker-before-matcher, and AST contracts. The focused JUnit records 130 tests, 129 passes, zero failures/errors, one live-PostgreSQL skip, 12.358s, and SHA-256 `58283a51e6591c54453c8bcad5e5439cc22267aa9642ab4f56e3d39d7b7bda40`. The retained full Python 3.11 JUnit records 1,220 tests, 1,210 passes, zero failures/errors, ten skips, 237.626s, the same eight warnings, and SHA-256 `b013b9fb49ff599c96152f2ef0fbb7ddb6fd862e66e3fe9610680106ae89695b`. Live PostgreSQL remained skipped and is not implied.
- E-075 adds 14 SQLite matching-rule producer/consumer, schema, hostile/resource, pre-transaction, replay-before-effect, public-reader, legacy-policy/text, and AST contracts. The focused JUnit records 115 tests, 115 passes, zero failures/errors/skips, 54.995s, and SHA-256 `b5f3856276aa441616334c427b28179b2fea7b45e5a381b60c23ef67f4d58c97`. The retained full Python 3.11 JUnit records 1,234 tests, 1,224 passes, zero failures/errors, ten service skips, 468.111s, the same eight warnings, and SHA-256 `b38e4d2bb460a698c9d2b179529eba41c539fb193c82ed480ae6c3ca9f5df2be`.
- E-076 adds 17 Redis session producer/consumer, closed-schema, hostile/resource, pre-client, non-mutation, tenant/TTL/compatibility, and AST contracts while extending the existing live-service test without adding a skip. The focused JUnit records 91 tests, 90 passes, one live-Redis skip, zero failures/errors, 18.428s, and SHA-256 `f637f523a153273813927412bbc926e233f50a0e13a2ffd451f3e4982b761766`. The retained full Python 3.11 JUnit records 1,251 tests, 1,241 passes, zero failures/errors, ten service skips, 206.395s, the same eight warnings, and SHA-256 `61ca3791e090ac747ee3d26c805ac36f760bb62aba6eeeef8a3ca54e5d5a8dc5`.
- E-077 adds 15 public-export profile/schema/hostile/resource/exact-field-inventory/shape/non-text/pre-publication/no-audit/AST contracts. The final exact-snapshot focused JUnit records 81 tests, 81 passes, zero skips/failures/errors, 38.192s test time, and SHA-256 `5fde0801c0a2bed1feb5e5cc3227cf55422ea07f04a2dcbb6d7fa3bbdc44cfe6`. The retained final Python 3.11 JUnit records 1,266 tests, 1,256 passes, zero failures/errors, ten service skips, 381.748s JUnit test time / 388.797s wrapper, and SHA-256 `3c406faa6312ea9c7d0165fd27c415b956a4810ffc08b43794e9ffb7b45afb3a`. The wrapper suppressed pytest console warning text, so E-077 does not assert an exact warning count; earlier eight-warning evidence remains historical only.
- E-078 adds eight publication contracts covering the exact manifest/schema, artifact tamper, successful stale-file removal, handled swap rollback, unexpected siblings, two crash phases, marker tamper, and path-minimized CLI recovery. The locked focused JUnit records 39 tests, 39 passes, zero skips/failures/errors, and SHA-256 `1e2c2abd7958f43fcbfd91978153191edf850022a307b8acffaa867d07626df2`. The retained full Python 3.11 JUnit records 1,274 tests, 1,264 passes, zero failures/errors, ten service skips, 235.317s JUnit / 237.337s wrapper, eight known warnings, and SHA-256 `9f1c23fd881d1ded25cfa03d629bf3ff555512552f491f769ef9a3311c3d7a9b`.
- No aggregate coverage or mutation score was measured. No coverage claim is allowed.

## Release consequence

The applicable local Python and web quality gates are now green, but the worktree must not be called release-ready. Same-machine artifact parity, deterministic clean-HEAD package/source SBOMs, one supported local locked profile, E-822's bounded non-root/no-network/read-only-root Docker CLI, and E-824's time-bounded fixed-only VEX evidence are local proof only. The exact image still has two release-blocking OpenSSL High matches. Recurring/signed image vulnerability and license inventory, Docker/OCI reproducibility, live server services, hosted Python 3.11/3.12 execution, clean-tree hosted artifacts, signatures/provenance, immutable publication, and broader rollback drills remain outside this proof.

## E-658 current regression note (2026-08-10)

After the spawned-process PostgreSQL scheduler gate, the full local
`uv run --no-sync pytest -q --tb=short -ra` invocation reached 100% and exited
0 with the repository's declared optional-service/platform skips and existing
financial-input/Starlette warnings. Full-tree Ruff, Mypy (517 source files),
Bandit, pip-audit, package build, and `git diff --check` also exited 0. The
focused live PostgreSQL gate passed in three repetitions against the local
PostgreSQL 16 service. This remains local evidence only; hosted execution,
cross-host fairness, queue HA/DR, and release approval remain open.

The follow-on E-659 crash/checkpoint gate also passed three local repetitions;
its abrupt worker exit, generation-2 takeover, exact effect set, and lease
event ordering are recorded separately and do not widen the quality baseline
into distributed HA/DR or production recovery assurance.

## E-660 write-back crash-window note (2026-08-10)

The focused write-back network suite now includes a real spawned-process
failure injection after synthetic provider acceptance and before acknowledgement
persistence. Recovery observes the durable `DISPATCHED` state, performs one
status lookup, and persists the bound acknowledgement without a second POST.
Ruff passes for the changed test. This is one-host SQLite plus injected-provider
evidence; vendor interoperability, distributed idempotency, HA/DR, and
production write-back remain outside the local quality baseline.

## E-661 Redis reconnect note (2026-08-10)

The Redis foundation gate passes 13/13 against the disposable local
`redis:7-alpine` service when `RECONFORGE_TEST_REDIS_URL` is set. It includes a
real pool disconnect followed by successful read recovery and unit failure
injection proving that only reads reconnect once; ambiguous mutations are not
replayed. Sentinel/Cluster failover, cross-host durability, and production
availability remain outside this local baseline.

## E-662 MinIO retention note (2026-08-10)

The real boto3-backed object-store drill passed all five invariants against the
local digest-pinned MinIO image and retained a credential-free report whose
canonical digest is recorded in `EVIDENCE.md`. The current-report contract now
checks three dated reports. Replication, KMS, cross-site durability, object
store HA/DR, and production availability remain outside this baseline.

## E-663 CLI compatibility note (2026-08-10)

The full local suite first exposed one narrow-TTY error-message folding failure
in the ownership-change CLI. The shared safe error printer now uses
`soft_wrap=True`; the focused regression and complete local pytest rerun exit 0.
This changes only CLI presentation and preserves fail-closed validation, with
hosted, provider, HA/DR, and production evidence still outside the baseline.

## E-664 PostgreSQL session-fault note (2026-08-10)

The live durable-job gate now covers an independent PostgreSQL backend
termination after a committed checkpoint, not only abrupt worker exit. Three
local PostgreSQL 16.14 repetitions prove generation-2 takeover, exact effect
set, ordered lease events, and zero residue. Host/site independence, automatic
failover, queue HA, RPO/RTO, and production scheduling remain outside this
baseline.

## E-665 canonical output-order note (2026-08-10)

The stock/GL reconciliation path now canonicalizes result-frame ordering by
stable identity while preserving source row/position as lineage metadata. The
focused hardening/input-policy/property suites pass, including an explicit
permutation regression for matched, unmatched, invalid, and aggregate
exception outputs. This is local artifact determinism only; hosted parity,
provider, posting, HA/DR, and production evidence remain outside the baseline.

## E-666 PostgreSQL HA/DR refresh note (2026-08-10)

The current-tree repeated PostgreSQL HA/DR verifier passed three fresh Docker
17.10 primary/synchronous-standby cycles on Docker Engine 29.6.2. Every run
had zero acknowledged transaction loss, final sequence 4, cleanup success,
failover RTO 11.117–11.321 seconds, and failback RTO 0.931–1.082 seconds. The
schema- and digest-bound report is retained in `docs/execution/` and packaged.
This refresh remains one-host/manual-controller evidence; quorum/witness,
automatic failover, host/site loss, production SLOs, and hosted E-461 backup
evidence remain outside the baseline.

## E-667 strict management-pack ingress note (2026-08-10)

Management-pack amount, risk, WIP, and close-completion helpers now select the
strict exact financial-input policy explicitly. The focused report and ingress
tests reject binary-float financial values and preserve malformed optional
values as unquantified. This narrows one compatibility omission only; other
named legacy callers and hosted/production evidence remain outside the local
quality baseline.

## E-668 local operator and Studio web validation note (2026-08-10)

The current tree passes doctor, sample-data validation, and a fresh demo run;
the sample fixture retains ten intentional warnings and zero errors. Web
typecheck, 13 Vitest files/70 tests, production build, and Playwright's 16
passed accessibility/UI checks pass, with five declared live-browser/HTTPS
skips. Demo output recovery remains fail-closed for ambiguous existing
directories; hosted deployment and production evidence remain outside this
baseline.

## E-670 Python 3.12 dependency gate note (2026-08-10)

The seven modules named by the historical CI import failures pass in an
isolated Python 3.12 environment after the locked all-extra installation:
48 passed, one declared live-PostgreSQL skip, and no collection errors. This
confirms the local dependency contract; hosted CI and native PostgreSQL backup
  evidence remain external.

## E-672 local PostgreSQL failure triage note (2026-08-10)

Local Docker PostgreSQL metrics and Alembic upgrade/downgrade tests pass 11/11.
The native backup path remains explicitly skipped because Windows has no
`pg_config`/`pg_dump`/`pg_restore` toolchain; hosted Linux E-461 is therefore
still an open release gate.

## E-673 local PostgreSQL server-boundary matrix note (2026-08-10)

The disposable PostgreSQL 16 matrix reached Alembic head with a
non-privileged RLS role and passed selected core, sector API, and durable-job
backpressure/10K suites. The database was removed afterward. Native backup
tooling and hosted/independent recovery evidence remain outside this baseline.

## E-671 Python 3.12 full regression note (2026-08-10)

The isolated locked all-extra Python 3.12 run reaches 100% and exits 0; the
current collection contains 2,877 tests. Capability skips and existing
framework/legacy-input warnings remain explicit. Hosted CI, native PostgreSQL
backup, independent HA/DR, live providers, and release approval remain outside
the local baseline.

## E-674 PostgreSQL repeated soak note (2026-08-10)

The bounded repeated PostgreSQL profile completes three isolated tenant-lane
iterations with stable effect digests, zero duplicate effects, and zero active
queue residue. This is one disposable host and synthetic workload evidence;
distributed soak, queue HA, capacity, RPO/RTO, and production scheduling remain
outside the quality baseline.

The post-slice isolated Python 3.12 all-extra regression, Ruff, Mypy, Bandit,
package build, and whitespace checks pass; the complete-history Gitleaks scan
also remains clean.
