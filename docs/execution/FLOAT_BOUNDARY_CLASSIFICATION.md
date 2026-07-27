# Remaining Float Boundary Classification

Measured 2026-07-25 with:

```text
rg -n '\bfloat\b' reconforge
```

Current result: 73 source lines. This is a lexical audit, not proof by itself.
Every category below records whether the value can affect financial truth,
control decisions, deterministic identity, or only operational measurement.

## Category summary

| Category | Lines | Current disposition |
| --- | ---: | --- |
| Timing, memory, benchmark measurement | 21 | Allowed non-financial instrumentation; retain bounds and never use as a financial claim without benchmark evidence |
| Synthetic-only presentation | 9 | Allowed only inside marked synthetic Studio contracts; not an approval/control authority |
| Suggestion scores and versioned signatures | 7 | Non-financial scores remain compatible; signature v3 retains v2 exact financial enforcement and adds record-instance identity, while explicit v1/v2 retain historical replay |
| Generic serialization, metadata, and report typing | 13 | Compatibility/general-purpose boundary; audit call sites and remove unused `to_float` rather than mechanically changing JSON/timing values |
| Explicit financial float rejection guards | 7 | Required safety checks: binary float is rejected, not used in financial arithmetic; the new canonical policy detector accounts for the added line |
| Explicit legacy financial compatibility readers | 16 | Approved compatibility only: every financial-policy default is strict v2; historical readers and named legacy helpers require an explicit policy/version and production AST gates prohibit implicit reuse under ADR 0097 |
| **Total** | **73** | Lexical inventory closed for P0-005; the 16 lines are explicit compatibility/rejection annotations, not implicit current financial defaults |

## File ledger

| File | Lines | Classification | Evidence / next action |
| --- | ---: | --- | --- |
| `benchmark/metrics.py` | 8 | Timing/rates/memory measurement | Runtime, report time, rates, approximate memory only; keep benchmark environment disclosure |
| `benchmark/reconciliation_execution.py` | 2 | Timing/memory measurement | Dataclass fields only; output is measured metadata, not decision input |
| `benchmark/runner.py` | 1 | Memory measurement | Process RSS conversion only |
| `api/routes/auth.py` | 4 | Security timing | Monotonic failure-window timestamps; float is appropriate clock representation |
| `infrastructure/redis.py` | 2 | Network timing | Socket timeout configuration only |
| `workers/outbox.py` | 1 | Worker timing | Poll interval only |
| `workers/postgres_reconciliation.py` | 3 | Worker timing | Poll interval configuration/coercion only; not matching arithmetic |
| `studio/demo_bridge.py` | 9 | Synthetic presentation | Marked synthetic contract validation and display scoring; no live financial mutation/approval |
| `mappings/inspector.py` | 2 | Suggestion score | Fuzzy mapping recommendation only; human selection remains required |
| `platform/matching.py` (confidence) | 1 | Suggestion score | Compatibility conversion for matcher-produced confidence only; it is not an amount or autonomous approval |
| `rules/models.py` | 1 | Rule confidence metadata | Confidence field, not rule amount comparison |
| `rules/results.py` | 1 | Rule confidence metadata | Output metadata only |
| `engines/signature.py` | 2 | Versioned signature compatibility | The two remaining lexical hits belong only to the explicit v1 generic serializer; current v2 rejects binary floating-point financial cells before missing handling and canonicalizes exact values |
| `io/writers.py` | 3 | Generic JSON compatibility | Standard JSON primitive/default typing; exact Decimal path is separate and tested |
| `platform/common.py` | 4 | Generic conversion/audit metadata | `to_float` is generic and currently has no production callers; schedule deprecation/removal, retain numeric audit-metadata compatibility until typed metadata exists |
| `reports/html.py` | 1 | Type compatibility | Summary union annotation; monetary values are Decimal |
| `reports/management_pack.py` | 4 | Non-financial ratio/type compatibility | Evidence coverage and union annotations; monetary aggregates use exact Decimal/currency policy |
| `platform/matching.py` (documentation) | 1 | Generic documentation | The word occurs only in a docstring stating that monetary policy parsing avoids binary arithmetic |
| `infrastructure/postgres_ledger.py` | 1 | Explicit rejection | Rejects bool/binary-float financial values |
| `infrastructure/postgres_reconciliation.py` | 2 | Explicit rejection | Rejects and explains binary-float reconciliation values |
| `platform/inventory_values.py` | 2 | Explicit rejection | Rejects float quantities/cost inputs |
| `platform/finance_core.py` | 1 | Explicit rejection | Rejects float financial inputs |
| `utils/money.py` (policy guard) | 1 | Explicit rejection | Current strict-financial-input-v2 detects Python/NumPy floating scalars before conversion |
| `utils/money.py` (compatibility annotations) | 9 | Explicit legacy compatibility / strict operators | `parse_amount`, currency parsing, and `Money` default to strict v2; multiplication/division reject binary floats. Named legacy scalar helpers and the explicit legacy policy remain migration readers, and AST gates prohibit their production use |
| `reconciliation/stock_gl.py` | 1 | Explicit compatibility type | The public policy type can represent legacy replay, but the default and current writers are strict v2; historical replay must pass legacy explicitly |
| `utils/yaml.py` | 1 | Versioned YAML tag identifier | The lexical hit is the standard YAML float-tag name; strict readers retain its source lexeme as text, while explicit legacy replay may request PyYAML compatibility |
| `variance.py` | 2 | Explicit compatibility alias/rejection comment | Defaults and schema-v3 output are strict; `LegacyThresholdInput` exists only for an explicitly selected historical policy |
| `anonymizer/mapping.py` | 1 | Explicit compatibility alias | Defaults and manifest-v2 output are strict; `LegacyAmountNoiseInput` requires explicit legacy policy selection |
| `generator/synthetic.py` | 1 | Explicit compatibility alias | Defaults, CLI/internal parsing, and manifest-v2 output are strict; `LegacyRateInput` requires explicit legacy policy selection |
| `studio/data.py` | 1 | Explicit compatibility alias | HTTP/application and service defaults are strict; `LegacyAmountFilterInput` requires explicit legacy policy selection |

## Closure rule

`P0-005` cannot be marked complete merely because most remaining lines are
non-financial. Closure requires:

1. versioned deprecation/removal or explicit approved compatibility policy for
   the 16 legacy financial-reader lines (**satisfied by ADR 0097: all 52 policy
   defaults are strict; historical readers and named helpers require explicit
   legacy selection and remain prohibited at production call sites**);
2. a financial-column assertion/version for reconciliation signatures
   (**satisfied by `reconciliation-signature-v3`; v1/v2 are explicit replay only**);
3. proof that no unclassified call site routes a binary float into amount,
   balance, cost, tolerance, materiality, valuation, or financial decision;
4. full supported-version and live-backend gates where those readers exist
   (**owned by P0-009 and the hosted release gates; no current default routes a
   binary float while those matrix runs remain pending**).

ADR 0097 completes the breaking-default migration. It retains explicit legacy
replay rather than deleting historical readers, adds a repository-wide default
gate, updates current direct artifacts to strict schemas, and publishes a
migration guide. The historical slice notes below describe the staged path and
are superseded only with respect to their former default-policy wording.

ADR 0051 completes the current scalar-helper call-site migration without
misstating the compatibility signatures as removed: `round_exact_money`,
`exact_money_difference`, and `within_exact_tolerance` are strict-v2, while
`round_money`, `money_difference`, and `within_tolerance` remain external
legacy-v1 readers. Production calls to the legacy scalar names are prohibited by
an executable AST inventory. The 17-line residual therefore remains until the
public constructor/operators and the explicitly listed ingress readers are
versioned or removed at an approved breaking-release boundary.

ADR 0052 adds the corresponding current `Money` paths: `from_exact`,
`multiply_exact`, and `divide_exact`. Existing constructor and dunder defaults
remain legacy-v1 but successful binary-float construction now warns. All three
production constructor sites spell their selected policy and an AST regression
prevents implicit default reuse. This narrows current-code exposure without
pretending the public compatibility annotations have disappeared.

ADR 0053 applies the same staged boundary to the read-only Studio minimum-
amount filter. HTTP remains bounded exact text and the application selects
strict v2; direct Python callers retain a named legacy alias/default and warn on
finite float. The lexical line remains classified until that compatibility
window closes.

ADR 0054 versions the durable anonymizer boundary. The CLI selects strict v2;
direct service calls retain the named legacy alias/default; manifest v2 records
the selected policy in its digest; schema-v1 verification implies legacy. The
single lexical float line remains only for that compatibility type.

ADR 0055 versions the durable variance boundary. The CLI selects strict v2;
direct service calls retain the named legacy alias/default; report schema v3
and threshold-policy v2 include the selected parser policy in the digest;
unversioned/v1 and schema-v2 reports imply legacy. The only executable lexical
float line is the compatibility alias; the other occurrence documents rejected
binary-float inference.

ADR 0056 versions the durable synthetic-generator boundary. The CLI and
internal exact calculations select strict v2; direct service calls retain the
named legacy alias/default; manifest v2 includes policy in both digests; schema
v1 implies legacy. Equivalent canonical inputs retain identical CSV bytes, and
the single lexical float line remains only for the compatibility alias.

ADR 0057 migrates current configuration loading without breaking historical
unquoted decimals. CLI, benchmark, and Studio select strict v2; a SafeLoader-
derived reader returns YAML floating-scalar lexemes as text before Pydantic
validation; default configuration output quotes tolerance text; and AST blocks
implicit production selection. Direct `ReconForgeConfig` and `load_config`
defaults remain warning legacy-v1 compatibility paths. The remaining lexical
YAML occurrence is the shared tag identifier, not financial arithmetic.

ADR 0058 reuses that shared reader for declarative control packs. Current
CLI/demo/explain/control-matrix paths select strict v2, numeric rule literals
are validated as finite under the selected policy, and schema-v2 rule results
record parser/pack/input/decision provenance. Direct Python rule defaults and
the unversioned result writer remain explicit legacy compatibility contracts.
This changes no lexical compatibility count because the only YAML occurrence
is shared and the two rule `float` annotations remain non-financial confidence.

ADR 0059 applies the staged policy at the local review/period boundary. Current
CLI/demo callers read exception CSV fields as text before Decimal validation;
direct Python callers retain explicit legacy defaults. Review workbooks expose
the policy without moving the compatibility sheet, while period-comparison v2
records the policy, recognized input-byte fingerprints, and separate decision/
artifact digests. Strict fingerprints distinguish invalid or missing amounts
from valid zero. This changes no lexical `float` count: it removes pandas'
implicit binary inference from current callers rather than adding or deleting a
typed float annotation.

ADR 0060 applies the policy to client-pack amount redaction. Current CLI/demo
callers preserve JSON decimal lexemes before exact bucket selection and write a
schema-v2 manifest with source/output fingerprints and policy/content/artifact
digests; direct Python generation retains warning legacy-v1 and the historical
unversioned manifest. The existing `client_pack.py` code contains no lexical
`float` annotation, so this removes implicit JSON decoder exposure without
changing the classified count.

ADR 0061 applies the policy to evidence-binder risk ingress. Current CLI/demo
callers read recognized exception, matched, and rule CSV fields as text before
integer-score validation and write schema-v3 indexes with selected-input
fingerprints plus content/artifact digests. Direct Python collection/generation
retains schema-v2 legacy behavior. The binder contains no lexical `float`
annotation, so this removes pandas' implicit inference from current decisions
without changing the classified count.
