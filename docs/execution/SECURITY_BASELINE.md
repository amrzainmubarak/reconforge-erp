# Security Baseline

Measured through 2026-08-22 against the current local snapshot in `STATE.md`. This is automated baseline evidence, not an independent security assessment or compliance statement.

## E-841 ownership-change route amount ABAC control (2026-08-23)

- Ownership-change preparation authorizes exact gross exposure before
  persistence, including ownership delta and consideration without double
  counting derived effects.
- Focused route/domain/dependency tests pass 19/19 with one declared live
  PostgreSQL skip. Other financial routes and production IAM remain outside
  the evidence.

## E-840 PPA route amount ABAC control (2026-08-23)

- PPA preparation authorizes gross consideration plus NCI exposure as exact
  Decimal before persistence and does not double-count allocation detail.
- Focused route/domain tests pass 16/16. Other financial routes and production
  IAM effectiveness remain outside the evidence.

## E-839 deferred-tax route amount ABAC control (2026-08-23)

- Deferred-tax preparation authorizes gross absolute typed fair-value exposure
  as exact Decimal before persistence and does not double-count tax basis.
- Focused route/domain tests pass 15/15. Other financial routes and production
  IAM effectiveness remain outside the evidence.

## E-838 intercompany route amount ABAC control (2026-08-23)

- Intercompany preparation authorizes gross absolute typed Money exposure as
  exact Decimal before proposal persistence; reciprocal netting cannot bypass a
  materiality bound.
- Focused route/domain tests pass 15/15. Other financial routes and production
  IAM effectiveness remain outside the evidence.

## E-837 Finance Core route amount ABAC control (2026-08-23)

- PostgreSQL Finance Core entry creation parses every debit and credit as exact
  non-negative decimals and passes one gross debit effect into central policy
  before adapter access.
- Invalid or negative amounts fail closed with a safe API error; no float,
  implicit zero, or duplicated debit-plus-credit amount is used.
- Focused route/dependency tests pass 11 cases with one declared capability
  skip. Universal financial-route adoption remains unverified.

## E-836 route-level amount ABAC control (2026-08-23)

- Consolidation impairment preparation now passes the exact Decimal sum of
  typed carrying amounts to central policy before persistence.
- Domain conversion rejects malformed or cross-currency amounts before the
  authorization/persistence boundary; no float or implicit currency conversion
  is introduced.
- Focused route/policy/dependency tests pass 90/90. Universal financial-route
  adoption remains unverified.

## E-835 bounded amount ABAC control (2026-08-23)

- A bounded policy cannot authorize an action when the exact financial amount
  is missing; the engine returns `amount_missing_for_bounded_policy`.
- The implementation accepts only the existing finite `Decimal` context and
  does not coerce missing values to zero or infer them from untrusted fields.
- Policy regression tests pass 80/80. Universal route adoption and deployed
  IAM effectiveness remain outside this evidence.

## E-834 durable observation controls (2026-08-22)

- Recovery observations are persisted before an accepted lifecycle transition;
  rejected, pending, not-found, and unknown outcomes do not mutate the intent.
- SQLite and PostgreSQL reject direct `UPDATE`/`DELETE`; triggers validate the
  canonical JSON envelope, duplicated identity columns, nested observation
  digest, and persisted connector/idempotency binding.
- PostgreSQL revision 0090 enables forced tenant/workspace row-level security;
  the disposable matrix verified that a role with all table privilege flags
  disabled cannot bypass scope enforcement.
- Replay uses the observation digest as an idempotency identity. The matrix
  covered SQLite, PostgreSQL 16.14, and PostgreSQL 17.10 with synthetic data;
  no secrets, provider credentials, or external network calls were used.
- The full Python suite passed 2996 executed tests with 115 declared skips;
  Bandit and pip-audit are green. The local pip tool was upgraded to 26.2 to
  remove the previously reported PYSEC-2026-3721 finding in pip 26.1.2.

## E-833 provider outcome observation controls (2026-08-22)

- Status lookup is separated from mutation; observations are frozen and
  digest-bound to the original idempotency key and raw response body.
- `pending`, `not_found`, and `unknown` cannot become acknowledgement or failed
  lifecycle states through the recovery executor.
- Legacy boolean responses remain accepted only through deterministic
  normalization; explicit outcomes are checked against the boolean and included
  in the response digest.
- Focused transport/domain tests pass 55/55 with synthetic responses and no
  credentials or external network calls.

## E-832 negative provider outcome controls (2026-08-22)

- A valid JSON envelope is not trusted as an effect: `accepted=false` is
  rejected before acknowledgement in original dispatch and status recovery.
- Error messages are fixed safe codes and never include provider body, payload,
  credential, or customer data.
- Existing compensation rejection and idempotency-key binding remain enforced;
  focused transport/domain tests pass 46/46.


## E-831 write-back recovery controls (2026-08-22)

- The runner uses generated disposable credentials, exact digest-pinned images,
  parameterized values, labelled cleanup, and a non-privileged application
  role with all elevated flags false.
- Append-only lifecycle triggers refuse direct UPDATE/DELETE; recovery is
  keyed by the original immutable identity, while compensation uses a distinct
  idempotency key and separated actor.
- Tenant scope is checked explicitly, the closed schema rejects six mutated
  evidence shapes, and the supply-chain validator consumes the runner, image
  constants, report, and CI artifact step.
- No live provider credentials, customer data, network egress, accounting
  posting, or settlement path is exercised. These controls are not a hostile
  DBA review, provider security assessment, or production assurance.

## Measured gates

| Gate | Result | Scope boundary |
| --- | --- | --- |
| `python -m bandit -q -r reconforge` | Current local exit 0, no findings | Notices cover the reviewed fixed-SQL `# nosec B608` sites: the new write-back migration concatenates only two module constants, while earlier backup/durable-job sites use allowlisted identifiers or immutable module-level columns and parameterize every data value. Suppressions remain manual-review points. |
| Hash-exported locked Python audit | The reviewed 128-package graph now resolves `pip 26.2`; the preceding `26.1.2` lock was rejected locally on 2026-08-22 for `PYSEC-2026-3721`. Isolated Python 3.11/3.12 runners exported all extras with hashes and pip-audit 2.10.1 reported zero known findings with no active exception. Older hosted Security/CI evidence remains historical and does not cover this workflow revision. | Advisory results are time-bounded; a fresh hosted Python 3.11/3.12 matrix is required, and reachability, provenance, malware, and license suitability are not proven; the SAML dependency warning remains monitored. |
| `npm.cmd --prefix apps/web audit --package-lock-only --audit-level=high` | Exit 0; 0 vulnerabilities reported | Covers the exact-version npm lock; all 211 current non-root entries have HTTPS registry resolution and embedded SRI |
| Gitleaks 8.30.1 full history | Exit 0; 602 commits and about 22.49 MB scanned after two exact historical fingerprints were recorded for synthetic test fixtures | Checksum-verified binary and default rules; exact fingerprints are limited to known non-secret test literals; detection is not proof that no secret existed or that external credentials are safe |
| Gitleaks 8.30.1 checked tree | Exit 0 across a clean 25.12 MB `git archive` checkout; the workspace scan is not evidence because generated environments caused a 6.30 GB/120-second timeout | Only generated/tool-owned paths are excluded; output is 100% redacted and every suppression is an exact commit/path/rule/line or path/rule/line fingerprint |
| Hardened Docker CLI and exact-image gate | E-822 local exit 0: two official-digest-pinned Python 3.11 Alpine stages, closed 216.25 KB context, 58,773,988-byte runtime image, UID/GID 10001, no uv/global pip/source/build manifests/docs; Doctor, validation, rules, and demo pass without networking on a read-only root. E-823/E-824 add exact Syft/Grype subject binding and fixed-only hash-bound VEX for three source-proven CPython fixes. | The current Grype evidence overrides the earlier favorable Docker Scout result for release gating and remains blocked on two CVE-2026-14456 matches in OpenSSL 3.5.7. One Windows/Docker Desktop host and time-bounded databases only; no hosted OCI reproducibility, independent reachability review, license legal review, signature/provenance, production volume ownership, or deployed hardening assurance. |

## Controls observed

- E-830's final local security gate adds the verifier to the full Bandit scan
  and exact PostgreSQL image constants to the closed supply-chain validator;
  both pass. The isolated CPython 3.12.13 audit reports zero findings and zero
  exceptions across 128 policy-owned packages. Ambient pip-audit separately
  reports host `pip 26.1.2` / `PYSEC-2026-3721` (fixed in 26.2) and is retained
  as a host-environment failure, not misreported as project success. Gitleaks
  8.30.1 reports no findings across all 663 commits and a clean implementation
  archive; the exact temporary files were verified and removed.
- E-830 runs exact digest-pinned PostgreSQL 16.14/17.10 images with generated
  disposable credentials, a runtime role whose superuser/create-database/
  create-role/replication/BYPASSRLS flags are false, parameterized receiver
  data, fixed progress labels, and exact resource labels. A partitioned COMMIT
  is classified uncertain only after direct `SyncRep` observation. Exact-ID
  fencing and container removal precede promotion, preventing the tested
  split-brain path. Writes remain controller-paused until a re-seeded standby is
  synchronous; restart endpoints are rediscovered rather than trusted stale.
  Normal failures clean automatically, and interrupted runs were removed only
  after label verification. This is not hostile-controller/DBA resistance,
  quorum fencing, external secret management, cross-host isolation, automated
  HA, provider security, or production assurance.
- E-829 adds an optional PostgreSQL receiver reference with no listener,
  payload-body storage, credential persistence, numeric financial amount, or
  autonomous authority. Data values are parameterized; connection/statement
  timeouts are bounded; transaction-scoped receiver/key locking and one
  receipt/effect transaction prevent same-database duplicate effects; database
  triggers refuse UPDATE/DELETE. Runtime-generated credentials are confined to
  disposable containers, and the application role has no superuser,
  create-database, create-role, replication, or BYPASSRLS flag. PostgreSQL
  16.14/17.10 contention, crash replay, malformed-input refusal, native restore,
  parity, and cleanup pass. This is not external authentication, malicious DBA
  resistance, cross-host consensus/failover, live-provider security, HA/DR, or
  production assurance.
- E-828 introduces no listener, payload persistence, credential store, or
  autonomous financial authority. Its receiver persists bounded identities and
  SHA-256 digests only; atomic receipt/effect inserts, an exact receiver/key
  primary key, validated replay response digests, and immutable-row triggers
  fail closed on replay retargeting or direct mutation. Spawned contention,
  crash replay, independent restore, negative schema cases, and verified temp
  cleanup pass. This is not live-provider authentication, distributed
  consensus, database failover, secret operations, or production assurance.
- E-827 closes the current two-version migration evidence gap with exact
  PostgreSQL 16.14/17.10 image digests owned by the closed supply-chain policy.
  One input-validated observation function performs both runs; unpinned images,
  malformed versions, unsafe container prefixes, version mismatches, history
  divergence, false checks, extra evidence fields, or incomplete cleanup fail
  closed. The report binds both runners, migration 0089, and policy sources.
  This remains same-host synthetic evidence, not image vulnerability assurance,
  provider security, rolling upgrade, HA/DR, or production assurance.
- E-826 exercises the adversarial migration path on digest-pinned PostgreSQL
  17.10. A drifted payload identity is refused without advancing Alembic,
  mutating history, or replacing the trigger. A SHA-256-bound native pre-drift
  dump restores and upgrades independently before the new trigger refuses
  drifted direct INSERT. The runner uses runtime-generated synthetic credentials,
  shell-free argument vectors, no retained payloads/secrets, and verified exact
  container cleanup. The isolated locked Python 3.12 audit passes with zero
  findings; the ambient host audit separately and correctly reports its
  installed vulnerable pip, so it is not used as product evidence. This is not
  live-provider, cross-host recovery, HA/DR, or production security assurance.
- E-825 binds every governed write-back version to the original proposal at
  repository and database INSERT boundaries. SQLite migration 42 and
  PostgreSQL Alembic 0089 refuse invalid predecessor/state histories and
  mutation-identity drift; API evidence exposes a stable proposal digest. The
  trigger and RLS path pass against digest-pinned PostgreSQL 17.10 under a
  non-superuser/NOBYPASSRLS role. Provider authentication, distributed receiver
  idempotency, hosted repetition, and production operating effectiveness remain open.
- GitHub Actions are referenced by full commit SHA in the six inspected workflows.
- Both Docker stages use the same policy-reviewed SHA-256-pinned base. A closed
  deny-by-default `.dockerignore` allowlist is validator-enforced, build tooling
  remains outside the runtime image, and the default identity is non-root.
- Universal `uv.lock` closes runtime, server, backup, observability, dev, docs, and DuckDB resolution; uv 0.11.32, its official archive hashes, and an absolute upload cutoff are policy-pinned. Normal CI, server CI, Docker, security, and candidate definitions use `--locked`.
- The closed supply-chain policy and exception registry require exact finding identity, repository issue, bounded owner/controls, two non-owner approvers, and at most 30 active days; there are no active exceptions. Scanner errors and report/exit disagreement fail closed.
- Weekly Dependabot definitions cover pip, npm, Docker, and GitHub Actions. Bot output still requires lock diff review, audits, tests, and human review.
- CodeQL, Bandit/pip-audit, release-integrated per-subject CycloneDX 1.7, Docker, and OpenSSF Scorecard workflow definitions exist.
- `docs/security/` contains architecture, threat model, API/data/deployment, local auth/RBAC, limitations, backup/restore, and questionnaire documents.
- Security Architecture v2 is a closed YAML registry for Community/Team/Regulated labels, data classes, trust boundaries, role-owned bounded/partial controls, concrete code/test evidence, and residual-risk linkage. Contract tests reject missing evidence, dangling references, unsupported mode promotion, and drift from normalized risk owners/ratings; this is repository design evidence, not deployed operating-effectiveness assurance.
- The closed module threat-model index has exact parity with all nine active runtime modules and links 20 classified assets, eight scoped actor types, eight shared threats, 33 module-specific cases, architecture controls/boundaries/owners, existing tests, residual risks where exact, assumptions, limitations, and explicit exclusions. Contract tests reject missing modules, stale interfaces/data classifications/tests, dangling references, and unsupported security promotion; this is design coverage, not threat-mitigation assurance.
- The scoped OWASP ASVS registry pins the official stable 5.0.0 release, its tagged commit and CSV digest, names all 17 chapters, and maps 55 selected requirements to repository evidence or explicit gaps: four implemented, 33 partial, 10 planned, and eight not applicable. The remaining 290 requirements are explicitly unassessed. Contracts enforce source identity, official chapter/count and selected ID/level parity, status totals, evidence paths, and claim boundaries; this is neither a full assessment nor an ASVS level, compliance, certification, penetration-test, or deployment assurance claim.
- The NIST SSDF registry pins final SP 800-218/SSDF 1.1 PDF/table identities, excludes the SSDF 1.2 Initial Public Draft, keeps final SP 800-218A as a separate AI-profile assessment, and maps all four groups, 19 practices, and 42 tasks. Twenty-eight tasks are partial and 14 planned; none is promoted to implemented-bounded or not-applicable. Every task has an architecture owner, gap, and action; partial tasks link existing files/tests, and a 90-day cadence plus event triggers governs review. This is repository evidence/gap mapping, not SSDF conformance or operating-process assurance.
- The SLSA provenance plan pins Approved v1.2 and its official tag/commit, keeps Build and Source tracks UNEVALUATED, and defines five release artifact identities, seven trust boundaries, in-toto Statement v1/SLSA provenance v1, signature expectations, strict independent verification with 12 safe failure codes, evidence-preserving rollback, and 12 implementation gates. The tag-only candidate plus exact build/SBOM identities, tests, and runbook make eight gates partial; four remain planned. This is repository implementation evidence, not an executed signature/attestation, trusted-builder assessment, retained hosted verifier result, SLSA level/property, or release-integrity claim.
- The candidate job has workflow-level deny-all permissions and grants only contents read plus OIDC, attestation, and package writes. It requires a clean exact version tag, GitHub-verified annotated-tag signature, `main` ancestry, full-SHA action pins, commit-time `SOURCE_DATE_EPOCH`, fail-closed sdist normalization, no-cache digest-addressed image build, exact artifact/SBOM metadata and digests, preserved provenance plus four subject-specific CycloneDX bundles, and repository/workflow/ref/revision/predicate/GitHub-hosted-runner verification before a 14-day review artifact. Local clean-HEAD source/wheel/sdist SBOMs are deterministic and official-schema valid; the image input is synthetic locally. No GitHub Release/PyPI publication step or long-lived signing secret exists.
- File/path validation, safe identifier quoting, RBAC/policy foundations, audit/outbox code, and local/no-mandatory-cloud defaults are present in source.
- P0-SEC-010 now makes the central policy primitive deny identity without an explicit permission and deny supplied tenant/workspace/entity/period resources outside immutable grants. Creator approve/review refusal defaults on. An exact nine-surface platform approval/review inventory uses one non-empty canonical actor comparator, including trusted-local workflow labels; arbitrary generic override text cannot authorize self-approval. Generated scope/ownership plus service integration tests pass. This is bounded local design evidence, not complete route/repository ABAC, amount/region/data-class policy, privileged-access workflow, or deployed control effectiveness.
- `tabular-file-ingress-v1` now rejects non-regular/symlinked, unsupported or content-mismatched CSV/XLS/XLSX before canonical pandas and direct DuckDB parsing; it enforces file/row/column/cell/field/archive/decompression limits and rejects unsafe XLSX paths, duplicates, encryption, active/embedded content, DTD/entities, external relationships, formulas, sparse over-limit columns, and aggregate over-limit worksheets. Stable error codes omit local paths and source values. A schema-validated inventory plus exact AST allowlist exposes remaining direct parsers.
- `structured-document-ingress-v1` bounds JSON/YAML bytes, nodes, depth, collection width, scalar size, and aliases; rejects duplicate keys, non-finite JSON/legacy YAML, YAML merges/cycles/multiple documents/unsafe or binary tags; routes FI-010 configuration/mapping/control, FI-011 close-workflow files, two FI-012 manifest readers, and FI-012 JSON redaction centrally; and exactly inventories the two central direct PyYAML parser locations. Close/manifests preserve generic public parse messages. Strict JSON redaction preserves fractional/exponent lexemes, legacy redaction keeps finite floats, and deterministic hostile JSON fails before fingerprint hashing or destination preparation.
- FI-012 CSV redaction now reuses `tabular-file-ingress-v1` before fingerprint/output work, rejects duplicate headers, preserves exact field strings for existing strict/legacy buckets, streams one row at a time, and publishes one target only after a same-directory temporary file closes successfully. The exact AST inventory records both `DictReader` call sites.
- FI-012 redistribution now freezes a bounded candidate/selected set before hashing: at most 20,000 traversed entries, 10,000 copied files, 64 MiB each, and 512 MiB aggregate. Generic redacted text is strict UTF-8 with a 1 MiB line ceiling; non-redacted bytes use bounded chunked temporary copies; output verification uses the same bounded traversal/fingerprint family. The complete pack is built and source-rechecked in a sibling staging directory. Handled generation, publish, and old-pack cleanup failures preserve or restore the prior destination; existing non-empty Windows replacement remains two-rename and not observer/crash atomic.
- FI-012 existing-output publication now writes a schema-v1 local transaction marker before the first rename and exposes explicit `client-pack-recover`. Recovery hashes hidden and visible content under the same bounded family, binds exact sibling basenames, accepts four closed states, and refuses missing/multiple/tampered markers, changed trees, reparse points, unknown siblings, or ambiguity. The SHA-256 marker is unkeyed self-consistency—not authentication—and simulated abrupt loss does not prove observer/crash atomicity or real host/filesystem durability.
- FI-009 plaintext database restore accepts only adjacent `backup.json` and `manifest.json`, not an archive, under `database-backup-json-ingress-v1`; optional Community and PostgreSQL paths add operator-keyed AES-256-GCM envelopes. PostgreSQL restore additionally requires the central operations permission, targets a newly created database, verifies the restored schema, and removes partial targets on tested failure paths. Legacy account/control imports use `database-legacy-import-json-ingress-v1`. The local controls do not prove managed key lifecycle, malware scanning, host-loss recovery, HA, or complete DR.
- FI-013 AP/AR idempotency responses use one producer/consumer contract with canonical object JSON, unique keys, integer-only number tokens, and 4 MiB/100,000-node/depth-32/25,000-item/262,144-character ceilings. Producer rejection occurs inside the existing transaction rollback boundary; corrupt replay rejects before a new AP/AR business row, audit event, or outbox event. This covers two former direct decoders; restored-row authenticity remains open.
- FI-013 SQLite/PostgreSQL audit metadata use one canonical bounded object contract with finite values and the same explicit resource ceilings. Verification validates metadata independently, preserves SQLite exact stored-text and PostgreSQL pre-JSONB canonical hash compatibility, list consumers fail closed, and SQLite export refuses corrupt audit metadata before file writes. Seven generic export/outbox/reconciliation/Redis/matching/worker direct decoders remain open.
- FI-013 PostgreSQL outbox payloads use one bounded canonical object contract across all six producer call sites, list/claim decoding, and publisher handoff. Corrupt claims roll back before publisher invocation; valid event identity, JSONB, lease, retry, and dead-letter behavior remains unchanged. E-073 also closes the master-data/evidence/reconciliation audit-producer omission found in E-072. Six generic export/reconciliation/Redis/matching/worker direct decoders remain open.
- FI-013 PostgreSQL reconciliation rule, input attributes, decision lineage, and exception evidence use four named finite-object profiles over one recursive schema. Attributes preserve the prior 100000-byte ceiling; the other fields use 4 MiB, and all enforce explicit graph budgets. Corrupt records fail before matcher/public use and JSONB rule fingerprint bytes remain canonical. Three generic export/Redis/matching direct decoders remain open.
- FI-013 SQLite matching rules use one 4 MiB finite-object profile with 100000-node/depth-32/25000-item/262144-character ceilings across both table writes, replay, and public readers. One encoding occurs before the transaction and preserves historical spaced sorted ASCII bytes and legacy missing-policy defaults; corrupt replay fails before a new effect. Two generic export/Redis direct decoders remain open.
- FI-013 tenant-scoped Redis sessions use one closed 16 KiB finite-object profile with 16-node/depth-2/four-field/256-character ceilings across producer and consumer. It requires bounded string IDs, a lowercase token SHA-256 digest, and explicit UTC expiry; producer rejection occurs before client access and corrupt reads preserve Redis state. Tenant key hashing, TTL, missing-key, and ID-match behavior remain compatible. E-077 subsequently closed the former generic-export direct decoder.
- FI-013 public SQLite export has an exact registry for audit metadata, legacy summary, two matching-rule fields, and matching lineage. All rows validate before filesystem mutation; nine unchanged format-v1 documents are staged and bound by an additive exact artifact manifest. Existing-tree replacement uses a bounded integrity marker/rollback and explicit fail-closed recovery; handled failure preserves prior bytes. No direct FI-013 stdlib decoder remains, while source authentication, authorization, malware, abrupt host/filesystem loss, observer intervals, audit/filesystem atomicity, and supported throughput remain open.
- External currency-registry files are explicitly selected, bounded to 1 MB, parsed as strict JSON with duplicate-key rejection, digest-checked when supplied, fully validated before atomic publication, and never fetched by runtime code.
- Variance thresholds reject negative, malformed, non-finite, and scientific-notation CLI text before artifact creation. Exact JSON output uses the standard encoder for structure/escaping and collision-checked private markers only for validated finite Decimal number lexemes; NaN and infinite output are rejected.
- Anonymizer shareable output requires a fresh/empty location outside the input tree, excludes reversible original mappings, and records policy/manifest/output SHA-256 digests plus an explicit non-guarantee privacy boundary. A private map requires an explicit non-existing path outside both trees; deterministic aliasing/noise and unclassified fields remain re-identification risks.

## Gaps and residual risk

- The new dependency/secret workflow and pre-registry release gates have not executed on a hosted runner; local definitions and tests are not branch-protection or operating-effectiveness evidence.
- The current npm lock fixes versions and all 211 non-root registry records
  carry HTTPS resolution and SRI. This closes the former recorded integrity
  metadata gap but does not prove package provenance, safety, reachability, or
  license suitability.
- File ingestion remains partial: FI-005/FI-006/FI-007 generated evidence/review/report/Studio CSV/JSON, FI-008/FI-009/FI-014/FI-015/FI-016 paths, and AP/AR/audit/PostgreSQL-outbox/PostgreSQL-reconciliation/SQLite-matching/public-export/Redis-session FI-013 contracts are bounded; exact AST allowlists close current direct tabular/JSON/YAML parser calls. Legacy XLS has only OLE-signature/file-size checks; client-pack and database-export replacement now have bounded explicit recovery but retain observer/pre-marker/host-loss limits. Legacy DB/review-state semantics remain permissive. Authorship, actor authorization, task correctness, disclosure approval, and provenance are not authenticated; malware scanning, quarantine, HTTP upload, and future connector controls remain absent under R-018.
- PostgreSQL and Redis service images use mutable major tags in CI; local live-service tests were skipped.
- Checksum-verified local secret scans and the bounded E-822 container smoke
  profile pass, but the E-824 exact-image release gate remains blocked by two
  OpenSSL High matches. Bounded backup encryption plus an application
  restore-permission boundary have local evidence. No current runtime evidence
  exists for DAST, broad fuzzing, container/IaC vulnerability scanning,
  signature/provenance verification, identity-provisioned restore operation,
  KMS/key rotation, HA/host-loss DR, air-gap installation, or penetration
  testing. Static release contracts are not cryptographic execution.
- Signed provenance pipeline execution, protected archives, trusted-builder/source-control assessment, independent verification, revocation drill, training, environment/endpoint assurance, vulnerability response/root-cause operation, and the SP 800-218A AI community profile remain open; the SSDF/SLSA registries expose rather than satisfy these outcomes.
- Deterministic local package/source SBOM files and synthetic image-normalizer fixtures are not proof of a hosted image scan, signed attestation, complete inventory, vulnerability/license assurance, or published release SBOM.
- The worktree is too broad for a focused security review and includes authentication, tenant, DB, evidence, and worker changes together.

Allowed wording: "Security checks and threat-model documentation exist; deployment security and release verification remain operator/reviewer responsibilities." Do not use `secure`, `compliant`, `certified`, `bank-grade`, or `enterprise-ready` as unqualified claims.
# E-175 service-account security delta

- Machine identities are separated from human users, roles, passwords, and browser sessions.
- Four migration-0037 tables use forced RLS. PostgreSQL triggers enforce permission and TTL ceilings, immutable credential identity, monotonic account versions, same-account rotation, and append-only events.
- Raw credentials are returned once by the operator CLI and only SHA-256 digests persist. Disable revokes all active credentials atomically.
- Residual boundary: workload identity federation, WebAuthn recovery/attestation governance and broad authenticator interoperability, hosted identity operation, independent assessment, and production operation remain unverified; current service-principal, password-step-up, emergency-review, and WebAuthn evidence is synthetic and bounded.
