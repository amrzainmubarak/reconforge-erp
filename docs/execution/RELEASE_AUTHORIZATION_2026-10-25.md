# Authorization repair evidence — 2026-10-25

Release decision remains **RELEASE BLOCKED**. This record qualifies bounded
authorization repairs; it does not certify the full product or release.
Entry branch: `amr/assurance-prerequisite-repair-20261025`, commit
`ff8a45cb0c2b3f9f6f7c657f65728b9c2dfb3b25`. Work uses the primary checkout only.
Preexisting edits were preserved by the lead before this work.

## Original failing assertions

The previous local diagnostic stopped at five failures. The retrieved GitHub
Python 3.11 and 3.12 logs for the entry SHA show **seven** authorization-inventory
failures. The lead retains that original output in
`output/release-blocker-20261025/github-ci-failures-entry.log`.

| Test | Original failed assertion | Root cause and correction |
| --- | --- | --- |
| `test_api_authorization_inventory_is_closed_and_digest_addressed` | 558 retained routes versus 492 | Unclassified enterprise additions contaminated a historical cohort. Preserve its original count/digest and assert the complete, exact new method/path/permission cohort separately. |
| `test_fixed_monetary_routes_preserve_all_620_retained_contracts` | 686 versus 620 | Same cohort-registration defect; the 620-route historical digest remains required. |
| `test_wave3_routes_require_exact_authority_and_preserve_all_accepted_route_contracts` | 495 versus 429 | Same defect; retain the original 429-route authority digest. |
| `test_wave4_source_routes_preserve_accepted_authority_and_require_exact_permissions` | 498 versus 432 | Same defect; retain the original 432-route authority digest. |
| `test_mutating_route_modules_declare_a_server_boundary_or_explicit_protocol_classification` | Twelve unreviewed mutating modules | Actual missing server scope integration. Each reviewed repository helper now enters the shared current-principal/current-header PostgreSQL transaction boundary; selected enterprise failures cannot fall back to SQLite. |
| `test_wave5_additions_preserve_every_accepted_wave4_route` | 525 versus 459 | Same cohort-registration defect; retain the original 459-route digest. |
| `test_each_mutating_route_handler_reaches_a_reviewed_server_boundary` | Unprotected handlers across the enterprise modules | Review and assert every handler's actual helper call, in addition to module classification. |

The present exact enterprise cohort has 90 contracts, including subsequently
integrated reads and financial lifecycle endpoints. Its expected permissions are
written independently of runtime enumeration. Unlisted additions remain visible
to the historical count/digest gates. Changing a permission or adding an
unclassified route is not silently excluded.

The original HEAD test source was also executed against the current route tree:
all seven original assertions reproduce, in
`output/release-blocker-20261025/agent-a/original-seven-reproduction.log`.
That mixed-source reproduction diagnoses the old inventory; it is not the entry
SHA runtime baseline. An earlier copy-only reproduction used an incorrect route
root and is retained as an unsuccessful setup observation, not evidence for its
server-boundary result.

## Additional verified security corrections

- A personnel capability no longer permits claiming any employee's entitlement
  by submitting a new request ID. Enterprise personal operations resolve the
  canonical `hc_employees.linked_user_id` using authenticated stable identity,
  workspace, and existing hierarchy RLS. Missing or foreign linkage fails 403.
- Community mode has an explicit immutable
  `hcm_employee_identities(workspace_id, employee_id, user_id)` mapping, registered
  in SQLite migration 58. Only a manager may provision it through the optional
  `employee_user_id` balance field, which accepts an existing active stable user
  ID. Existing links cannot be reassigned. Legacy unbound balances are preserved
  and personal access fails closed until a manager provisions the link.
- Request reads and unpaid-deduction calculations require the owner or additional
  current scoped management/review authority. The original owner-only withdrawal
  rule remains enforced. Request bodies cannot choose the authenticated actor.
- Canonical employees cannot approve or reject their own requests, including a
  legacy request whose stored owner string was forged. Both adapters enforce the
  canonical link in addition to the existing domain maker/checker rule.
- Current scope is resolved before opening the business connection. An ALL
  permission contract requires every permission; ANY preserves explicitly
  authorized read access. The production scope setter uses the same five bound
  transaction-local GUC statements for every connection, without fake-class
  special cases. Its test asserts all five names and all five values.
- Eight leave mutations append redacted business evidence through the existing
  local or PostgreSQL audit chain in the same transaction as the business writes.
  Metadata contains schema/workspace only, without raw leave reasons or wages.
  Trigger-injected balance or audit failures must roll back the complete effect.
- Transaction admission also revalidates authority after waiting: SQLite reads
  the active user and current grants after acquiring its writer transaction;
  PostgreSQL uses the existing `hc_actor` admission to pin persisted user, role
  and hierarchy grants through commit. Additional HR read authority is pinned
  too. Deterministic real-DB tests pause an authenticated waiter, commit a real
  permission revocation, then require the resumed operation to fail with 403 and
  no business/audit effects. Synchronization seams do not replace policy or DB
  decisions.

These are additive schema/payload changes with intentional fail-closed behavior
for previously unbound personal records. No employee ownership is inferred from
historical caller-supplied requests. No existing data is deleted. Populated
recovery and full official migration acceptance are owned by the lead.

## Verification and limits

Local diagnostics use Windows, Python 3.14.6 and native PostgreSQL 16.15. The
owned cluster is `output/assurance-20261025/pg/data`, bound to loopback port 55439;
the original Windows PostgreSQL service is untouched. Native fixtures create
and remove only random test-owned databases and roles. They apply the official
Alembic chain, register canonical employees through the personnel service, and
exercise the ordinary role without superuser, BYPASSRLS, CREATEROLE or CREATEDB.

Native regressions cover canonical linkage, private reads, all 90 enterprise
route denials with unchanged operational tables and finance effects, real
permission revocation through access administration, session invalidation,
tenant/workspace denial, concurrent approvals/cancellations, atomic business and
audit failure, canonical self-review refusal, and hostile direct SQL under FORCE
RLS. Authentication and step-up use the real endpoints; no permission decision
is mocked. Intermediate test setup errors (missing step-up, incomplete lifecycle
revocation, missing foreign workspace fixtures, non-whole-second clock) are
retained as failed runs and corrected by satisfying the actual contracts.

Evidence is retained in `output/release-blocker-20261025/agent-a/`:

- `inventory-scope-final.log`: 61 passed, zero skipped; all inventory and shared
  scope tests, including every original failing test and exact GUC assertions.
- `independent-b-security.log`: Agent A independently ran 13 SQL-binding and
  fixed-asset failure-boundary regressions; 13 passed, zero skipped. Fixed SQL
  fragments contain no untrusted value interpolation; values remain bound. This
  does not substitute for the lead's native fixed-asset qualification.
- `independent-c-components.log`: Agent A independently ran the three repaired
  HCM/CRM/project component suites: 48 passed. The asynchronous helper was also
  reviewed for scope/session/locale response races; results and recovery actions
  now bind the exact current context. Component tests do not establish browser
  or accessibility conformance.
- `independent-c-native-scope-final.log`: Agent A independently verified the
  original revision-0063 intercompany artifact repository/API workspace fix:
  one passed, zero skipped (17.98 seconds). The initial positive proposal
  fixture was rejected with 422 because domain Money serialization carried
  fields forbidden by the API; the corrected fixture selects the four admitted
  input fields without relaxing validation. Own reads/proposals succeed and
  same-tenant sibling reads/persistence fail. The original table's FORCE RLS
  remains tenant-based; this result proves the application workspace boundary,
  without claiming a stricter raw-SQL workspace policy.
- `authorization-complete.json`, `.log`, `.xml`: superseded broad diagnostic,
  120 passed and one test defect; source changed during subsequent independent
  review. The failed assertion incorrectly compared the global business audit
  before two legitimate Bob operations against its state after those successes.
  The corrected regression snapshots all state immediately before denied
  reassignment and additionally preserves the original Alice request/balance.
- `revocation-audit-focused.log`: five passed, zero skipped (29 deselected),
  covering final native/local revoked waiters and real audit/balance rollback.
- `final-local-ownership.log`: corrected local ownership/rebinding and canonical
  self-review cohort: four passed (20 deselected).
- `authorization-final-stable.json`, `.log`, `.xml`: **34 passed, zero failed,
  zero skipped**, comprising 24 local and ten actual PostgreSQL cases, in
  131.58 seconds. All nine bound runtime/test/migration file hashes remained
  unchanged throughout. This supersedes the earlier mixed-source broad result.
- `final-quality.json`: focused Ruff, Mypy (four source files), Bandit (zero
  findings on the four affected source files), and diff whitespace checks. This
  scanner scope is distinct from Agent B's repository-wide disposition.

Agent B's independent final checks passed the two committed-revocation waiter
tests (25.57 seconds) and the two local/native audit-insert refusal tests
(96.27 seconds), with zero skips. B also reviewed the immutable local mapping,
stable identity validation, canonical self-review checks, transaction admission,
native grant locks, and corrected denied-operation audit oracle. Earlier B
scope14/native2 checks retain their original source scope; they are not summed.

Agent B independently reviews the security changes and reruns selected negative
cases. An implementation agent does not independently certify their own code.
The required supported Python 3.11/3.12 matrix, exact-commit CI, full native
migration/recovery, authenticated real browser workflows, dependency/container
security and remaining release gates are separate lead-owned acceptance work.
