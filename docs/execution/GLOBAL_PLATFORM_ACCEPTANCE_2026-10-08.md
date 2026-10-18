# Global operational sprint acceptance — 2026-10-08

Branch `amr/global-platform-execution-20261008`, based on clean `6c194e7c`.
Draft [PR124](https://github.com/amrzainmubarak/reconforge-erp/pull/124) is stacked
on the baseline-refresh branch; main remains `b61ea56b`. Three isolated agents
implemented the capabilities below, with one lead owning shared registration,
contracts, migrations, navigation and aggregate acceptance.

The complete local regression accepts runtime `9bcbeb07`: **4,455 passed,
492 explicit prerequisites skipped, zero failures**. Later application source
through `563ad127` is byte-identical in runtime, migrations and Studio. Changes
after the regression strengthen verification, refresh the pinned container
and regenerate current native Writeback evidence. The historical receipt test
now pins frozen0100, proves the exact0108 replacement, and runs its static
contracts without a PostgreSQL prerequisite. Its affected live group passed
**7/0skip**. Initial failures remain retained, with their own source identities.

## Implemented operational paths

| Path | Real persisted behavior | Principal boundaries |
| --- | --- | --- |
| `/budget-control` | Draft, submit, independent approval, reserve, consume and release through existing budget repositories; exact BigInt/minor-unit interpretation and retained events | Current canonical scope, distinct checker, conserved balances and frozen scoped retry commands; no automatic purchase/AP/GL posting |
| `/inventory-receipts` | Authenticated prepare/read/review/commit/full-unused-inverse; atomic movement, FIFO valuation, GL, source/review/link/command and evidence | PostgreSQL public interface; untracked Stock/Consumable base-UOM internal FIFO; distinct humans, current masters, original-actor mutation retry; original history retained |
| `/jobs` | Bounded redacted keyset inspection, governed queued cancel and paused/failed requeue, version-aware retry and immutable transitions | `ops.read`/admin-seeded `jobs.manage`, current persisted scope, human step-up, active-lease fencing; one retained effect under concurrent retry |

The interfaces use existing organization/workspace/identity/authorization,
financial, evidence and job engines. SQLite56/PG0107 add job permission/index
contracts; forward PG0108 aligns receipt admission and serializes the initially
absent currency binding. Frozen0100 is unchanged. Central authorization covers
301 registered routes with digest
`28b8b7cf9caf56f79d576b88cb6a97ce12ba6f50d35a79c4b4e87cd53a14ce4e`.

## Gates and observed effects

| Gate | Result and evidence |
| --- | --- |
| Full locked Python regression | 4,455 pass/492 explicit skip; 1,215s on clean9bcbeb07; `python-final.json/xml/log` |
| Live PostgreSQL17.10 | 58 finance/master/security/budget cases,25 receipt cases,8 operations cases,7 affected migration cases; each group zero skips, non-superuser/non-BYPASSRLS runtime role, head0108 |
| Native job authority/concurrency/recovery | Six simultaneous cancel commands retain one transition; current-scope/revoked-grant/human-step-up/lease/requeue/downgrade/native-restore checks pass with zero skips |
| Web components | 243 pass; later affected journal keyboard group5 pass; typecheck and normal production build pass |
| Real normal-Studio HTTPS budget browser | One explicit Chromium case passes: lost acknowledgement retry, balance8,500/reserved0/consumed1,500 atv6,3 immutable events, foreign-scope/CSRF refusal, EN/AR,390px,keyboard,axe0,reload |
| Real normal-Studio receipt/jobs browser | Two explicit Chromium cases,0skip/0flaky; two independently reviewed committed plans, two original/inverse GL effects, FIFO quantity/value0, six job transitions and exact cancelled/queued states; EN/AR RTL,390px,keyboard,axe0,reload |
| Populated native financial restore | Custom-format dump/restore; all186table row hashes,141functions,191triggers,1,473constraints,208RLS policies,538indexes,727relations/ACLs,4,085columns/schemaACL equal; current checker verifies original/inverse effects;21financial forced-RLS tables; restricted direct immutable-link mutation refused23514; foreign/unscoped reads0 |
| Static/security/supply chain | Whole Ruff, mypy616sourcefiles, Bandit, locked Python/npm audits and tracked/history Gitleaks pass; audits reported zero known findings in the tested branch locks |
| Distribution | Wheel/sdist build passes on563ad127; current secure Docker build passes onaa81176d,850.406s; hardened doctor passes with networknone/read-only/cap-drop/no-new-privileges/nonroot10001; root Docker image ID `sha256:04295c8f4cfbdf42f98ace07d5379fc3c407c0174200dd3a74e61acff41883c4`, distinct configuration digest recorded below |
| Fresh native Writeback evidence | Four actual existing matrix runners on PostgreSQL16.14/17.10: identity29.829s,failover75.953s,idempotency19.985s,recovery25.687s; all backend checks and owned cleanup pass; application migration matrices reach0108; affected contracts50pass/0skip on563ad127; historical October3 reports unchanged |
| CLI/recovery/benchmark | Doctor/validate/demo and local reliability/quorum simulation pass. Local10K matching:30.9422s,44.17MiB tracemalloc peak,5,000matches/candidates,0exceptions; concurrent gate activity recorded; no capacity extrapolation |

Raw reports are retained under `output/gfo-sprint-20261008/`.
[Machine index](GLOBAL_PLATFORM_ACCEPTANCE_2026-10-08.json) binds commands,
source identities, report and log SHA-256 values, prerequisites and limits.
The native combined report is `final-combined-native-restore/report.json`;
source and built Studio remained unchanged and owned resources were removed.
CHECK fingerprints use PostgreSQL's own reparse into empty temporary LIKE
tables to canonicalize associative AND emitted by native dump/restore; no guard,
operator or validation state is discarded.

`distribution-artifact-index.json` verifies the five delivered runtime members
against the built wheel and the four current native reports against sdist.
Experimental development artifacts are `dist/reconforge_erp-0.7.1-py3-none-any.whl`
(SHA256 `4ed7102daae34ae76ae96eee92766a50fe2421701909914f830bb704ae9f2a85`)
and `dist/reconforge_erp-0.7.1.tar.gz`
(SHA256 `24bbc53225d97bfd35bdc82bab75eb44e9dbedcdb299ae4f677c3732eaf69d37`).
They have not been uploaded or published as a stable release.
The wheel also installs offline with no dependency resolution into an owned
target. From an outside-repository working directory, five imported runtime
origins resolve to that installed target and its CLI doctor exits zero.
`wheel-install-acceptance/report.json` records argv/origins/logs; this gate uses
the existing locked Python3.12.13 dependency environment. The clean pinned
container build/installed runtime is independently verified.

## Hosted acceptance

On runtime9bcbeb07, CI37724214213 passed both Python versions, four engine-parity
jobs, web, object storage, PG HA/DR, Docker parity, and eight of nine server shards.
Only inventory-payables failed the obsolete frozen0100/current-installer equality
test (28other selected cases passed). The aggregate failed closed. Docker,
Security and CodeQL workflows passed that exact head.

The repaired source d59bc4d0 passed
[CI37727480462](https://github.com/amrzainmubarak/reconforge-erp/actions/runs/37727480462):
both Python versions, all four engine-parity profiles, web, object storage,
PostgreSQL HA/DR, Docker parity, all nine server shards and the required aggregate.
Python3.12 recorded4459passes/489explicit prerequisites. Docker, PR Security and
CodeQL workflows passed that head. The PR Security workflow intentionally omits
the exact-image scan; manual37728310528 executed it and rejected the41day-old
OpenVEX under the unchanged30day policy. Fresh local scan of initial image71d
then found6unsuppressedHigh in Python3.12.14,zlib and libuuid. ADR0840 pins both
stages to Python3.12.15/Alpine3.24, retains signed OpenSSL3.5.9 and adds signed
checksum-bound zlib1.3.2-r1; the base contains libuuid2.42.3-r1. Actual packaged
runtime and the closed policy pass, without adding CVE exceptions.

On exact security sourceaa81176d,
[manual Security37731225415](https://github.com/amrzainmubarak/reconforge-erp/actions/runs/37731225415)
passed all5jobs. Configuration digest
`sha256:8a753119aeb6dcb9e59276272662f0c014276783e82361377bea9dc85708b9ba`
binds the accepted hosted image; raw Syft/Grype outputs and the locally
byte-identical validator result are retained. Fresh findings are **0Critical,
0High,9Medium,1Negligible,0Unknown**; zero active exceptions and zero VEX
suppressed/applied matches. Pinned Syft1.51.0/Grype0.117.0 use valid database
v6.1.10 built2026-10-07; the30day VEX and120hour DB limits remain enforced.
License metadata coverage65/68 (95.58%) is inventory, not legal assessment.

The independently built root image also passes the unchanged closed validator,
with the same findings count and zero exceptions. Its configuration digest is
`sha256:79e40997a4db989e096eb43d4441c67cffea209aa84b7be8079d9f3ff0d2e6e8`,
local manifest digest
`sha256:cd66af13453c04dea655a774ca625b476d792d9afb077e9b511b05141b786fb0`.
These differ from its Docker index ID and from the hosted image; each has its
own raw scan/report bindings. Root evidence is
`hosted-final/root-container-review/acceptance-index.json`.

CI37731227022 onaa81176d correctly failed four retained Writeback tests that
compared historical policy bytes to the refreshed policy. Genuine fresh native
runs produced new October8 reports; October3 reports remain bound to their Git
base, while current reports must match the complete current policy. The closed
identity schema adds only current target0108. No runner, financial source,
migration or security guard was relaxed. All50affected contracts pass on563ad127;
its full [CI37733619873](https://github.com/amrzainmubarak/reconforge-erp/actions/runs/37733619873)
passes all20required jobs on563ad127: both Python versions, four engine-parity
profiles, web, object storage, PostgreSQL HA/DR, Docker parity, all nine server
shards and the aggregate. Docker37733619909, Security37733619919 and
CodeQL37733619856 also pass that exact head. Current raw logs/counts are bound
in the machine index. Python3.11: 4463 passed, 489 skipped, 10 warnings in 805.32s (0:13:25); Python3.12: 4463 passed, 489 skipped, 26 warnings in 900.15s (0:15:00).
Final execution-documentation commits change no tested
application, migration, Studio, container or verification implementation.

The PR checkout executes merge commit
`bd2eb19bbac0edcae4d2831a7aface459158504d`, whose complete Git tree
`ed08e11cf7068a5310912d80b39b04349eb244d9` equals head563ad127 exactly.
Its parents are the baseline-refresh PR base6c194e7c and sprint head563ad127;
neither names the unchanged main branch. Raw checkout/API/tree binding is
`hosted-final/source-563ad127-hosted-tree-binding.json`.

## Operating limits and rollback

Module maturity stays experimental. This is synthetic single-node operational
acceptance, with no production deployment, external customer acceptance or
certification. This sprint does not complete sales/procurement/AR/AP/treasury/
assets/tax/FX/intercompany end-to-end integration, cross-host HA/DR or declared
banking capacity. The matching benchmark is unrelated to receipt/job throughput.
The9Medium/1Negligible image findings remain recorded for triage; this is not a
zero-vulnerability claim. Python/npm package-lock audits and container scans
cover different subjects. Main has not received these branch changes.

Stop operator traffic and take a verified backup before rollback. PG0108 refuses
downgrade with retained receipt plans;0107 refuses loss of custom permission
grants. Preserve accepted DB revisions while rolling back application exposure,
or restore an independently verified pre-upgrade backup. Never remove posted
inventory/GL/audit history to force downgrade. Main has not been merged or deployed.
Container rollback requires a freshly accepted exact image under the unchanged
policy; initial image71d with6High is not an approved security fallback.
