# Native fixed assets: operation and evidence

The experimental PostgreSQL fixed-assets module prepares, independently reviews and posts cash-funded acquisition, cumulative straight-line depreciation and disposal into the existing native GL. Source lifecycle, native financial effect, audit, outbox and command acknowledgement commit together. Use the configured PostgreSQL server profile and an authenticated human session; this module has no separate ledger or local SQLite asset backend.

## Before the first acquisition

Select the authorized tenant, workspace, organization and legal entity in **Fixed assets** (`/fixed-assets`). The catalog must contain an active functional currency, an appropriate journal, an open fiscal period and six distinct active accounts: asset, accumulated depreciation, depreciation expense, cash, disposal gain and disposal loss. Account semantics are validated against the captured native journal. Keep the entity's currency policy consistent with retained assets; original currency and precision remain part of historical evidence.

Assign three distinct persisted human users. `finance_core.manage` prepares, `finance_core.validate` reviews, `finance_core.post` posts and `finance_core.read` reads. Mutations require current scope/amount authority and recent human reauthentication under the configured step-up policy. Approval uses user IDs, not names or aliases. Permission removal and disabled users are rechecked; an earlier approval does not grant continuing authority.

## Studio workflow

1. Prepare an acquisition with asset number/name, acquisition and in-service dates, useful life in months, historical cost, salvage value, the six accounts, journal, open period and reason. Studio accepts exact major-unit text and converts it using the selected currency precision. Inspect the retained operation digest and balanced native lines. A prepared asset has no posted acquisition effect yet.
2. A second human opens the same retained acquisition, verifies its source and native lines, supplies a reason and reviews its exact digest. A third human independently posts it. Confirm the asset is active, the posting effect is present and historical cost agrees with the asset and cash GL lines.
3. For an active asset with no pending operation, prepare depreciation with a completed `YYYY-MM` service month, posting date, open period and reason. The second and third humans review and post this operation in turn. Inspect the new tranche, cumulative depreciation, completed months and carrying amount.
4. Prepare disposal with proceeds, posting date, open period and reason. Review and post with the same three-person separation. The native effect releases historical cost and recorded accumulated depreciation, recognizes cash proceeds and the exact residual gain or loss. A posted disposal closes the asset; subsequent depreciation or disposal is refused.

Every operation passes through Prepared, Reviewed and Posted. The operation history retains original snapshots and effect references. The latest 25 plans appear first; **Earlier history** loads preceding plans. Asset lists use 25-row keyset pages, with an API maximum of 100 assets per page. These page sizes do not authorize omission of retained financial history.

If a response is lost or malformed, retain the original command and use **Retry the same command**. Do not generate a new command to discover whether the first one committed. Retry must use the same actor, operation and exact request; the backend returns the retained acknowledgement and refuses changed reuse. Refresh current history separately because a retained acknowledgement describes its original phase, while the operation may subsequently have progressed.

## API contract

Use the server identity flow and the selected `X-ReconForge-Tenant`, `X-ReconForge-Workspace`, `X-ReconForge-Organization` and `X-ReconForge-Legal-Entity` headers. Cookie-authenticated mutations additionally require the current `X-ReconForge-CSRF` token. Scope IDs come from authorized masters and are not acquisition-body fields. The following paths are relative to `/api/v1/fixed-assets`:

| Request | Purpose and required payload |
| --- | --- |
| `POST /assets` | Prepare acquisition: `command_id`, `asset_number`, `name`, `journal_code`, `period_id`, `posting_date`, `in_service_date`, `cost_minor`, `salvage_minor`, `useful_life_months`, the six `*_account_code` fields, `reason`. |
| `POST /assets/{asset_id}/operations` | Prepare depreciation/disposal: `command_id`, `kind` (`depreciate` or `dispose`), `period_id`, `posting_date`, `reason`; depreciation uses `through_month` and zero `proceeds_minor`, disposal uses empty `through_month` and `proceeds_minor`. |
| `POST /plans/{plan_id}/review` | Second human: `command_id`, retained `expected_plan_digest`, `reason`. |
| `POST /plans/{plan_id}/post` | Third human: a separate `command_id`, the same retained `expected_plan_digest`, `reason`. |
| `GET /assets?after=...&limit=25` | Authorized asset register page; follow `next_after`. |
| `GET /assets/{asset_id}?before_sequence=...` | Asset state and a retained history page; follow `history_before`. |
| `GET /plans/{plan_id}` | A single retained operation. |
| `GET /plans/{plan_id}/evidence` | Verified original source, operation, native journal and financial/audit/outbox references. |

API monetary fields are canonical integer minor-unit **strings**, never JSON floating-point amounts. For example, a USD acquisition uses `"cost_minor":"10101"`, `"salvage_minor":"1001"`, `"useful_life_months":3`. An operation to depreciate January uses `"kind":"depreciate"`, `"through_month":"2026-01"`, `"posting_date":"2026-02-01"`, `"proceeds_minor":"0"`, together with a valid open `period_id`, a new `command_id` and a reason. Strict schemas reject unknown fields. Date/policy/account errors require correcting the proposed request; command conflict, lifecycle conflict or digest mismatch require inspecting current retained evidence.

## Exact depreciation and supported bounds

Cost is positive and at most `9000000000000000000` minor units; salvage and proceeds are nonnegative within the same bound. Salvage must be strictly below cost. Useful life is an integer from 1 to 1200 months. Six distinct account codes are required. The complete native debit turnover must also fit the minor-unit bound, including a disposal whose proceeds plus accumulated depreciation exceed its carrying value.

Depreciation uses completed **calendar service months**, including the month containing the in-service date; it does not prorate service days. `through_month` is explicit. Posting must occur on or after the first day of the following month, and accounting dates cannot regress. The business posting date is the clock used for this entitlement check: this endpoint does not automatically schedule depreciation from the machine's current date.

For cost `C`, salvage `S`, useful life `L` and eligible completed months `m` capped at `L`, the cumulative entitlement is `floor((2*(C-S)*m + L)/(2*L))`, equivalent to exact positive ROUND_HALF_UP. The next tranche is this entitlement less already posted depreciation. It must advance completed months and produce a positive amount; independently rounded monthly instalments must not be added instead. For `C=10101`, `S=1001`, `L=3`, the first month is `3033`, and a subsequent catch-up through month three is `6067`, totaling exactly `9100`. Disposal for `1500` then releases carrying value `1001` and records gain `499`.

Currency code and precision are retained from the legal entity's functional-currency registry, with supported precision 0 through 8. Original native snapshots keep that historical policy. Acquisition must precede or equal the in-service date. Operations require a posted acquisition and an undisposed asset. Only one unposted operation may reserve an asset's next lifecycle position.

This scope supports cash-funded acquisition and ledger cash recognition of disposal proceeds. It does not calculate tax or FX, capitalize AP invoices, prorate days, implement other depreciation methods, impairment, transfers, reclassification or cancellation of asset proposals. Disposal does not instruct an external bank transfer. Generic native posting/reversal must not be used to detach an asset-owned entry from its original source; an asset correction capability needs its own governed lifecycle.

## Evidence access, verification and download

Reading evidence requires current `finance_core.read` for the selected hierarchy **and both** the retained operation's complete native debit turnover and the source asset's historical cost, using its original currency precision. Asset detail/history authorizes every emitted plan's turnover as well as source cost. A small permitted depreciation amount does not imply permission to disclose a larger acquisition basis; a low carrying amount does not imply permission to read larger disposal turnover. A denied page is refused rather than silently dropping restricted plans. `GET /plans/{plan_id}` authorizes that plan's turnover; the evidence endpoint adds the source-cost authorization.

Select a retained operation and press **Verify source and ledger evidence**. Before displaying a verified result, the server executes native source closure and verifies any posted effect against the retained entry, snapshot and validation digest. Studio independently uses WebCrypto SHA-256 over the exact UTF-8 canonical JSON strings:

| Canonical string | Expected seal |
| --- | --- |
| `canonical_asset_json` | `asset_definition.asset_digest` |
| `canonical_plan_json` | `plan.plan_digest` |
| `canonical_snapshot_json` | `plan.validation_digest` |

Studio also checks selected scope/phase, effect identity, balanced exact BigInt totals and distinct human phase provenance. A proof before posting explicitly has no native effect. Each canonical string is capped at 65536 characters in the Studio verifier; retain exact strings when verifying offline, including integer lexemes above JavaScript's safe-integer range. Hash their UTF-8 bytes directly rather than parsing and reserializing them with floating-point JSON numbers. SHA-256 seals show content agreement; they are not a signature or a legal certification.

**Download verified evidence** becomes available after browser verification. The JSON contains the original canonical strings, three digests, phase actor IDs, audit/outbox references and the native posting effect. Record the downloaded file's own SHA-256 separately when transporting it. The read and download create no new journal, ledger or persisted asset transaction.

## Verification, recovery and measured scope

Use isolated synthetic environments for acceptance. Native financial gates require real PostgreSQL with a restricted nonowner/non-BYPASSRLS application role, current migrations and zero skipped selected cases. The actual HTTPS Studio journey and populated restore gate are reproducible with:

```text
python .github/scripts/verify_erp_expansion_browser.py --scenario fixed-assets --verify-native-restore --output output/fixed-assets-acceptance
```

Retain the report, source/built-web fingerprints, browser JSON/downloads, exact integer balance oracle, populated backup hash, relation/function/policy/trigger inventories and cleanup result. Domain or component tests alone do not establish a working native browser cycle or recovery.

Migration `0122_pg_fixed_assets` and native event-dispatch support are additive. Empty downgrade is allowed where guarded migrations permit it; populated asset plans, links, commands or financial evidence refuse destructive downgrade. For rollback, stop business writes, retain the failed-upgrade evidence, and restore a verified pre-upgrade backup into an isolated database with compatible source. Verify roles/FORCE RLS, original asset definitions and all five owner tables, native financial effects, identity/master scope, audit/outbox, retained command acknowledgements and independent GL balances before switching service traffic. A dump that restores without these populated checks is insufficient. Restore of a captured backup establishes only the measured backup boundary; this slice does not establish multi-region failover or an RPO/RTO guarantee.

The dimensional snapshot benchmark measures a warmed 1000-line journal **read**, alternating the original reader and batched reader on the same scoped fixture with raw latency/CPU/Python-allocation/query counts and identical independent totals/digest. Its observed query reduction from 1002 to 2 does not establish acquisition/depreciation/disposal throughput or end-to-end posting throughput. Native posting benchmarks must separately retain the matched source, pinned database image/durability settings, seed, worker count, raw cycle latencies, independent financial oracle and resource samples. Published scope and limitations remain attached to each evidence packet; no competitor, production-capacity or full ERP performance claim follows from the snapshot observation.
