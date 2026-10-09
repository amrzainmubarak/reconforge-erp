# Classified financial statements and opening balances

This experimental PostgreSQL slice composes the existing verified business-date balance engine and immutable native posting kernel. It adds a reviewed classification map and a reviewed initial journal, then exposes trial balance, balance sheet, period income and cash movements in the Financial statements workspace.

Select the authorized tenant, workspace, organization and legal entity. The catalog reads real account, journal, period and functional-currency masters. Prepare an explicit account map; designate cash accounts deliberately. A different authorized human reviews the exact map digest. Maps and their review evidence remain immutable; corrections create another version. New opening preparation and review recheck current native account semantics against the reviewed map. A master change requires a new correctly reviewed map before that opening can be captured.

Prepare the initial opening using the first date of an open scoped fiscal period, the entity's functional-currency journal and exactly balanced asset, liability and equity lines. Opening requires an entity with no retained operational posting history. A different checker reviews the exact opening source and the native journal snapshot. A third human posts it. The same transaction writes the native GL effect, owner link, audit, outbox and exact command acknowledgement. Generic posting and reversal cannot detach an OB1 source from its owner. Corrections use a separately reviewed adjustment journal and retain the initial source.

Existing native maker/checker permissions apply: `finance_core.manage` prepares, `finance_core.validate` reviews, `finance_core.post` posts, and `finance_core.read` reads. Writes require current persisted permissions, canonical scope and recent human reauthentication; amount policies use exact decimal conversion of retained minor units. User IDs, rather than caller-provided aliases, bind phase evidence and retries.

Select a reviewed map, fiscal period and inclusive as-of date. Trial balance supplies verified opening, movement and closing values from currently recorded immutable effects. The balance sheet includes all closing asset/liability/equity balances plus the explicitly labelled accumulated unclosed income less expense. Period income uses only selected-period movement. Cash movements group each effect's designated cash lines and retain counterpart lines; internal cash transfers have zero total delta. Every contributing account must be mapped, and every displayed account can drill down to posting effects and source lines. Studio verifies each source contribution, period/date affinity, complete double-entry effects, trial-balance totals and classified statement/cash folds using exact integers before display. Unsupported off-balance account types are explicitly excluded from classification choices; an unmapped contributing account refuses a report. Downloaded API JSON retains money as strings and report/map/balance digests.

The as-of cutoff is business date, not the time at which a user originally knew about a posting. Later entries dated before the cutoff change a newly generated report. Maps preserve their captured account semantics. Reports do not infer tax, FX, fiscal-year close, statutory cash-flow sections or consolidation. The existing evidence limits remain 1000 effects and 10000 lines; exceeding them is an explicit refusal.

Migration `0112_pg_financial_reporting` preflights the reserved OB1 namespace, installs forced scoped RLS and invoker integrity guards, and preserves old history. Its installer is additive and supports reinstall. Empty downgrade is supported; populated map or opening history refuses downgrade and requires forward recovery. Backup/restore must retain the new maps, reviews, plans, links, commands, functions, policies and reverse native closure triggers.

For historical least-privilege native finance roles, new reverse integrity checks require conditional **SELECT only** on `reconforge.financial_opening_plans`. A role participating in this module also needs the explicitly granted map/review/link/command tables for its permitted phases. Preserve FORCE RLS and deny unnecessary INSERT/UPDATE/DELETE privileges; do not use a definer function to bypass entity isolation. Verify restored roles using actual nonowner/non-BYPASSRLS probes before accepting a recovery profile.

The configured PostgreSQL test module requires the existing real PostgreSQL fixture. Run it with fresh administrator and restricted application DSNs; configured acceptance requires every selected case to execute with zero skips. Default runs without that prerequisite report the same explicit prerequisite behavior as the existing native modules. Static, domain and React checks cannot substitute for the native integration gate or normal authenticated browser workflow.
# Durable enterprise statement captures

The existing `/statements` response and evidence budgets remain compatible.
For larger histories use **Captured enterprise statements** in Studio after
selecting a reviewed classification, fiscal period and cutoff date. The new
`POST /api/v1/financial-reporting/snapshots` accepts `command_id`, `map_id`,
`period_id` and `as_of_date`. It requires current `finance_core.read`, selected
tenant/workspace/organization/entity authority, a human identity and browser
CSRF for cookie-authenticated requests. It creates report evidence, with no
financial posting or approval effect.

The database captures the ordered IDs of all visible eligible native effects
automatically, then seals that membership before the capture INSERT returns.
The initially false seal changes to true only inside the database-owned capture
trigger; sealed membership cannot be reopened or extended, including before the
summary exists and through unrelated nested triggers. Trigger depth alone does
not establish that the automatic source capture is still running.
The application verifies native snapshots and audit/outbox in
100-effect batches, then folds exact amounts without retaining posting lists
in memory. A deferred SQL closure independently recomputes account totals,
statement equations, currency/period affinity, the retained classification and
the report audit event. A capture, all membership, summary, audit and outbox
commit together. Any failure rolls the entire capture back; retry its original
command unchanged. Reusing the command with another actor or request is refused.

`GET /snapshots/{snapshot_id}` returns the compact captured statements.
`GET /snapshots/{snapshot_id}/evidence?expected_digest=...&after=0&limit=20`
returns original native posting evidence and chained membership. `next_after`
is an ordinal keyset cursor. Pages bind the snapshot ID and report digest,
default to 20 effects, permit at most 200 effects, and stop at 4 MiB of canonical
evidence. All sources remain retained; a byte boundary reduces the page size
rather than omitting evidence. Individual native snapshots retain their existing
2 MiB budget. The UI shows one evidence page, verifies chain links with SHA-256,
folds account/statement summaries with BigInt, and supports Arabic/English,
keyboard operation, responsive tables and exact lost-acknowledgement retry.

Later or backdated postings appear only in a **new** capture. Existing snapshots
and pages remain unchanged, including after vacuum or a full native restore.
The stored transaction snapshot string is diagnostic metadata, never a source
selection filter or long-lived `xmin` identity. Fixed native effect IDs and the
membership evidence chain are the durable source definition.

The three new tables use FORCE RLS. Runtime roles need SELECT/INSERT on
`financial_report_captures`, `financial_report_members`, and
`financial_report_snapshots`, plus existing scoped native read/audit/outbox
permissions. The invoker capture trigger additionally needs the finite grant
`GRANT UPDATE(membership_sealed) ON reconforge.financial_report_captures TO <runtime_role>`.
Do not grant table-wide UPDATE for that transition. All financial provenance
stays immutable; the trigger admits only the automated false-to-true seal
transition while leaving every other capture column identical. It refuses any
later update, including a no-op seal assignment. Application INSERT into
membership is refused after capture birth, and membership/summary UPDATE or
DELETE always fails. The regression fixture retains PostgreSQL TEMP privilege
and proves that an unrelated nested temporary trigger cannot append a newly
committed native effect. Populated migration downgrade refuses evidence loss;
use forward repair or restore a verified pre-upgrade backup.

This path removes the operational 1000-effect/10000-line ceiling without raising
the legacy endpoint's limits. The reviewed chart remains capped at 1000 accounts
and summary JSON at 2 MiB. Large database aggregates can spill according to the
operator's PostgreSQL resource configuration. Capture is currently synchronous;
there is no claim of async worker execution, statutory cash-flow classification,
multi-currency conversion, consolidation or automatic period close.
