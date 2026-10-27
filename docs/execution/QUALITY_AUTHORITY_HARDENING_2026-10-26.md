# Institutional hardening: quality authority and evidence integrity

Status: IN PROGRESS. RELEASE BLOCKED. Entry source81c5b57f; primary directory
F:/reconforge-erp, existing Draft PR143, no worktree/main mutation/deployment.

## Root-cause scope

The legacy NCR API records arbitrary lot/work-order strings and does not own
native stock. Its old quarantined assertion remains red; do not change the
response to invent an inventory effect. Native ME2 already owns quality holds
through its reviewed source/cost/posting lifecycle. A generic bridge is not
justified by an unbound string identifier. Full procurement/production cycle
remains BLOCKED.

The legacy self-disposition guard stores a mutable inspector username. The
implementation slice binds stable authenticated creator/reviewer IDs, fails
closed for unverified historical creator identity, and commits authority with
the business record atomically. Preserve original source rows and display labels.
Reserve PostgreSQL157 and SQLite60 if schema support is required.

ME2 Studio must not replace missing WIP/hold evidence with zero or leave stale
parent totals appearing confirmed after a child acknowledgement and failed
refresh. Preserve acknowledged child evidence and explicitly mark unverified
parent data until a successful source refresh.

## Ownership and verification

Engineering: quality backend and new schema helper/focused regressions.
Independent QA: original unchanged failing test and independent authority tests.
Product: existing ME2 page and tests. Principal: migration registries, release
contracts, CI recovery investigation, Git and execution evidence.

Required proofs: red/green rename and reused-alias cases; independent reviewer;
forged identity; legacy refusal; persistence across fresh reads; SQLite/PG
rollback; scope isolation; migration preservation and populated rollback refusal;
ME2 source-refresh failure/stale responses. No native test skip is a pass.

Latest entry hosted Security/Docker pass, standardweb pass; mandatory CI has
commercial-integrity and real browser/recovery failures. Original logs/artifacts
are retained under output/enterprise-program-20261026/continued-*. Diagnosis
and fixes require original-source evidence; do not weaken assertions.

## Implemented and independently reviewed checkpoint

SQLite60/PostgreSQL157 persist immutable canonical creator/reviewer authority
linked to existing audit events. Renamed creators remain unable to self-review;
reused aliases do not transfer ownership. Legacy records remain readable but
unbound review is403. NCR create/disposition in server mode now require explicit
organization/legal entity headers and current persisted human/permission/grant
pins; other legacy quality routes keep existing hierarchy requirements. Public
missing-NCR404code ncr_not_found is preserved. Scope is still workspace-NCR;
selected hierarchy metadata is not a claim of entity-owned stock.

Independent QA strict native+SQLite8pass0skip proves157emptyroundtrip/populated
refusal,60DDL/marker rollback, actor identity, immutable RLS authority, injected
post-write rollback/retry, and concurrent rework600+600 against1000 allowing
only one600 allocation. No canonical GL effect is produced by advisory NCRs.
The original quarantine assertion remains unchanged/red.

Root combined native/contracts39pass0skip in195.516s process; full frontend
1267/115files pass88.516s. Those whole-source digests changed solely because
the live navigation helper search locator was corrected during the run; these
are component results, not a frozen all-source release acceptance. Backend/UI
production bytes remained stable. Frozen successor results are retained separately.
Ruff passes, mypy899files passes, Bandit passes with existing warnings retained,
and production web build passes. ME2 focused25cases and before8failure oracle
are retained as quality-ui-*; explicit zero remains valid in Arabic and English.

Real hosted procurement browser failure stopped before business commands at a
closed navigation section. Twenty-three live specs (32 navigation steps) now use
a shared actual sidebar search and visible permitted destination; no financial
assertion is removed or API response mocked. The helper is required in source
publication. Real native browser/recovery execution remains a separate gate.

The commercial empty-downgrade/upgrade fixture lost the SELECT prerequisite on
the recreated enterprise_finance_bindings read directory. It restores only
that RLS-filtered SELECT and explicitly asserts no INSERT/UPDATE/DELETE. The
original native case passes39.95s with unchanged source snapshot; independent
review confirms the shared inverse guard dependency. This changes no runtime ACL.

Raw records: output/assurance-20261026/hardening-* and qa-quality-*;
output/enterprise-hardening-20261026/native-final.xml; before hosted logs and
artifact under output/enterprise-program-20261026/continued-*. No production
customer data, extra worktree, main merge or deployment.
