# Engineering assurance prerequisite repair — 2026-10-25

**Program acceptance: NOT ACCEPTED. Production qualification: OPEN.**

Entry source: `7af61cddb1fc96a3f5f348257c772206171572c1`, initially clean,
two local commits ahead of its remote enterprise branch. One checkout only at
`F:\reconforge-erp`; no main update, release or deployment. The earlier
"VICTORY CONFIRMED", certification and full-scope assertions are retained as
historical assertions, not verified acceptance of the present source.

The lead controls Git and shared records. Agent A independently authors HCM
regressions and reviews product fixes; B repairs finance/registry/XML and verifies
HCM on real PostgreSQL; C repairs browser integrity. File ownership is exclusive.
No timing here is a comparative performance benchmark.

## Defect and root-cause register

| ID | Reproduced defect | Repair and acceptance boundary |
| --- | --- | --- |
| A25-01 | Any personnel reader could withdraw another employee's request, including a forged actor body | Authenticated owner check,403, persisted state unchanged |
| A25-02 | Approval/cancellation saved request before a separate balance commit; trigger failure left partial state | One read/validate/write transaction; SQLite writer serialization and PG row locks; rollback and two-request concurrency oracles |
| A25-03 | Submitting an existing ID reset submitted/approved/cancelled requests | Conflict409 plus atomic insert-only repository operation; tested original state unchanged |
| A25-04 | Concurrent first-use session refresh UPDATE0 retained SQLite write lock and produced500 | Finalize owned refresh transactions even with zero affected rows; preserve caller-owned transactions; deterministic stale-read regression |
| A25-05 | Missing Finance Core manufactured PMI/PIS entry references and posting events | Refuse absent/malformed ledger result before source linking/audit; emit neutral linked events with observed status, never claim Draft was posted; API wiring, idempotency and cross-repository atomicity remain open |
| A25-06 | AI, statements, MPS and genealogy fabricated successful financial/operational data on initialization or server rejection | No synthetic fallback; validated authenticated reads, session invalidation, bilingual errors, advisory proposals; unavailable source-less writes |
| A25-07 | Runtime migration registry omitted real Alembic head0152 | Register151 revisions, preserve exact chain; native upgrade/downgrade/re-upgrade tests |
| A25-09 | Public HCM domain accepted fractional/bool counts; unpaid deduction could returnfloat | Strict integer guards before arithmetic;71 new count/type regressions; independent86-case final HCM rerun |
| A25-08 | Country XML parser accepted entity expansion/DTD input | Defused parser forbids DTD/entities/external declarations; safe error and valid-XML compatibility tests; no statutory certification |

Before/after observations are retained, including failed intermediate concurrency
and web runs. Narrow repair approval requires independent review and relevant
regressions; it does not close the global gates.

## Quality scorecard and open gates

| Gate / ISO25010 quality dimension | Measurable acceptance requirement | Current decision |
| --- | --- | --- |
| Q / functional suitability, compatibility | Real authorized source→operational effect→canonical GL→audit→report paths; independent monetary oracles; all mandatory current tests pass | OPEN: new API workflows still lack canonical wiring; current authorization-inventory tests fail |
| S / security, safety | Scoped authorization matrix, no exploitable launch-blocking high/critical findings, untrusted ingress controls | OPEN: broader HR object binding, module scope classification, scanner/dependency triage and external assessment absent |
| U / interaction capability | Actual critical EN/AR journeys, applicable full-process WCAG2.2 A/AA checks, defined task/recovery measures | OPEN: targeted component repairs only; no human study or full accessibility-conformance evidence |
| P / performance efficiency, reliability | Real workflows with financial oracles, raw repetitions, resource/SLO and restore evidence on exact source | OPEN: dictionary/loop workloads cannot establish posting throughput or process-crash recovery |
| I / flexibility and capability comparison | Product/edition/date-bound first-party evidence and equivalent executed comparisons | OPEN: existing comparative labels unverified; performance NOT COMPARABLE — INSUFFICIENT EVIDENCE |
| R / maintainability, release integrity | Current-source locked Python3.11/3.12 CI, full native/browser/security/container/package/restore gates and artifact hashes | OPEN: current coherent source-bound CI unavailable; missing migration schemas and environment prerequisites |

No arbitrary score is assigned. ISO25010 is a reference model, with no certification
claim. The full normative subcharacteristics have not been licensed/read here;
the public ISO abstract alone does not establish them.

## Baseline, evidence and reproduction

Environment: Windows11 `10.0.26300`, Python3.14.6, Node26.3.0/npm11.16.0,
owned PostgreSQL16.15. Python3.14 is a local diagnostic environment, not a
substitute for the required locked3.11/3.12 matrix. Command records carry UTC
start, duration, exit, source fingerprint before/after and log hash. During
parallel edits a changed broad fingerprint is explicitly **not** a frozen-source
pass. The evidence manifest binds final affected files separately.

- Initial full-scope pytest diagnostic stopped at5 failures:289 passed,1 skip.
  The five failures are existing authorization-inventory/scope-classification
  gates; their counts/digests/allowlists were not weakened to make this green.
- Initial Ruff and Mypy886 passed. Bandit found11 low/6 medium findings,0 high;
  findings require triage and are not automatically confirmed exploits. The XML
  parser repair addresses the two observed XML warnings.
- Global installed-environment pip-audit reports findings; it is not a locked
  application dependency audit (installed local package is0.7.0). Initial invalid
  CLI flag invocation is retained, followed by the corrected invocation.
- Doctor, sample validation (0 errors/10 warnings), demo and package build pass
  at their recorded fingerprints. The initial package/build and scan runs overlap
  edits and do not qualify the final candidate.
- Online npm ci stalled without output and was explicitly interrupted; subsequent locked offline installation succeeds (160 packages), with network audit separately unqualified. Initial
  full web run encountered99 module-load failures while another Vitest process
  overlapped; that run is retained, not accepted. Final serialized verification
  is recorded in the machine-readable evidence index.
- Initial Playwright:21 launch failures,7 prerequisite skips; Chromium executable
  missing. Browser installation/retry status is retained separately. This is not
  a passed browser or accessibility gate.
- Docker build is environment-blocked by registry/CDN DNS; run could not obtain
  the image. GitHub read attempts hit TLS handshake timeouts; no remote green
  checks or publication are inferred.
- Real native migration tests:2 passed on owned16.15, covering0152 head and
  down/up recovery. All16 existing index definitions inspected in the catalog.
  HCM native adapter proof explicitly installs its schema outside Alembic;
  it proves restricted-role FORCE RLS, approval rollback, shared-balance
  concurrency and duplicate refusal, **not** a migrated production HCM API.

Final serialized web verification:1205 passed across111 files in101.33s;
TypeScript and build pass. These are component/build results, not human UX or
browser conformance. Final source `a91852a7b0e1f88bc77602a738556c059e8646a9` contains committed runtime
and test sources; only execution documentation follows. Broad safety cohort at
a91:123 passed/1 inherited live-PostgreSQL prerequisite skip; final changed HCM
scope:86 independent passes/0 skips plus real restricted-role native proof on
a918. These cohorts overlap and are not summed. Ruff and Mypy886 pass on a918.
Bandit finishes10 low/5 medium/0 high findings:15 open scanner findings, with no
claim that all are exploitable. Four intermediate warnings from fixed SQL clause
concatenation were resolved by explicit literal joins; independent16-case emitted
SQL byte parity is retained. No suppression was added for those queries.
The final Python/source receipts are listed in the manifest.
The online browser download failed (connection reset/CDN errors), so no subsequent
browser-pass claim is made. An intermediate full Ruff run found an import-order
error in the XML repair; the correction and successor lint result are retained.

Audit compatibility: future `milestone_gl_posted` and
`profit_in_stock_gl_posted` emissions from these helpers become
`milestone_gl_linked` and `profit_in_stock_gl_linked`, with observed
`finance_entry_status` metadata. Historical records are unchanged. Consumers
matching action names must accept the new names and must not interpret a
Draft link as an approved financial posting.

Raw local records: `output/assurance-20261025/` and
`output/engineering-assurance-20261025-agent-b/`. The retained capsule and
[manifest](ASSURANCE_2026-10-25.json) supply portable logs, hashes, reproduction
scripts, final source binding and command-level results. Global test totals are
not added across overlapping cohorts.

Reproduce targeted regressions with:

```powershell
python -m pytest tests/test_hcm_leave_authorization_regression.py tests/test_api_hcm_leave.py tests/test_hcm_leave.py tests/test_api_auth.py
python -m pytest tests/test_enterprise_finance_posting_required.py tests/test_country_sa_xml_security.py tests/test_postgres_operations.py
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run
```

Native migration tests require a disposable owned PostgreSQL admin/app fixture;
never point them at production. The capsule contains the adapter reproduction
script and its exact scoped role/database setup.

## Remaining release requirements

1. Register/review the13 HCM/CRM/capacity/BOM PostgreSQL tables absent from
   Alembic; prove deployment, grants, workspace boundaries and populated restore.
2. Connect actual project/intercompany API commands to canonical Finance Core
   under an atomic/idempotent business contract with explicit currency policy.
3. Resolve the actual authorization-inventory and server-scope failures; bind HR
   employee identities, source record access and business audit events.
4. Replace/clearly withdraw local-only HCM/CRM/project success workflows; qualify
   real authenticated browser journeys. The four repaired pages remain bounded
   experimental reads/advice, with unavailable source-less generation.
5. Run locked dependency/security/container and full current-source native/HTTP/
   browser/347-table populated recovery/CI gates. Real-user UX, independently
   controlled performance, SLOs, legal/statutory validation and external security
   assessment remain unproven. No external result is invented.

Claims about deadlock freedom, worker-crash recovery, zero penny leakage or
market differentiation are withdrawn as release conclusions where their cited
test only implements a standalone model or simulation. Earlier successful
source-bound historical evidence keeps its original scope.

Official reference pages checked on2026-10-25: [ISO25010:2023](https://www.iso.org/standard/78176.html),
[OWASP ASVS5.0.0](https://asvs.owasp.org/), [API Security2023](https://api-security.owasp.org/),
[NIST SSDF1.1 final](https://csrc.nist.gov/pubs/sp/800/218/final),
[SLSA1.2 approved](https://slsa.dev/spec/v1.2/), [WCAG2.2](https://www.w3.org/TR/WCAG22/),
and [Core Web Vitals](https://web.dev/articles/vitals). These guide open acceptance
criteria; they confer no assessed conformance or certification. No field Web
Vitals or competitor performance measurements were collected.

The owned PostgreSQL cluster was stopped after verifying its exact data directory;
the original Windows PostgreSQL service was untouched and recovery files remain.
The initial pg_ctl wrapper timeout is retained as a negative setup observation,
even though later native connections and tests succeeded.

## Draft publication and newly observed dependency alerts

[Draft PR143](https://github.com/amrzainmubarak/reconforge-erp/pull/143) was
created successfully after the initial TLS failures. The
[delivery snapshot](ASSURANCE_DELIVERY_2026-10-25.json) binds the successful
publication command and default-branch dependency metadata. Subsequent live PR/CI
reads hit TLS timeouts; no merge, production release or CI acceptance is claimed.

GitHub reports69 open default-branch alerts at source
`9fe77d7f8f68ece527b055208b14afc9d10e2b7b`:6 critical,30 high,25 medium,8 low.
These are alerts, not independently confirmed exploits or a claim that all apply
to every deployment. Critical entries name Pillow (locked12.3.0) and certifi
(locked2026.7.22); these lockversions are unchanged in this repair. Controlled
dependency refresh, authoritative advisory review and locked supported-profile
verification are P0 before launch. No risk waiver. These alerts are separate
from the15 remaining Bandit findings and are not summed into one vulnerability
count. The failed live snapshot/parser attempt produced no source or PR update;
the successful creation receipt remains the publication evidence.
