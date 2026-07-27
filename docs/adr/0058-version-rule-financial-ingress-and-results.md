# ADR 0058: Version Rule Financial Ingress and Result Evidence

- Status: Accepted
- Date: 2026-07-25
- Scope: declarative control-pack YAML, rule evaluation, current CLI/demo output, and historical result compatibility

## Context

Control-pack YAML used `yaml.safe_load` directly. An unquoted financial rule
literal such as `0.100000000000000005` therefore crossed binary floating point
before comparison and became `0.1`. Direct rule APIs and the unversioned
`{"results": [...]}` artifact are established compatibility surfaces, so
silently changing their default or rewriting historical output would be unsafe.

Rule-result rows also identified the rule and source row but did not bind the
selected financial-input policy, pack version/content, input CSV bytes, or a
deterministic decision digest. A checksum can detect inconsistency; it cannot
prove who authored a pack or whether a source system is authentic.

## Decision

1. Move the SafeLoader-derived exact-scalar reader introduced by ADR 0057 to a
   shared YAML utility. Both configuration and control-pack loading use it;
   arbitrary Python tags remain rejected.
2. Give `load_rule_pack`, `evaluate_condition`, `evaluate_rule`,
   `execute_rule_pack`, and compatibility `run_rule_pack` an explicit named
   financial-input policy. Direct Python defaults remain warning
   `legacy-financial-input-v1`; current CLI rule validation/list/run/explain,
   demo, and control-matrix paths select `strict-financial-input-v2`.
3. Validate literal numeric comparison values and tolerance/threshold fields as
   finite Decimal-compatible inputs under the selected policy. Preserve their
   public source-shaped `Condition.value` representation and use Decimal only
   at the comparison boundary.
4. Add an AST regression that forbids implicit production policy selection for
   all migrated rule/control-matrix calls.
5. Preserve `run_rule_pack`'s list result and `write_rule_results`' historical
   unversioned v1 JSON/CSV writer. Add `RulePackExecution` and
   `write_rule_execution` for current schema-v2 artifacts.
6. Bind v2 to the financial-input policy, normalized executable `pack.yml` and
   `rules.yml` content digest, sorted SHA-256/byte fingerprints of every local
   input CSV, and results. The deterministic `decision_digest` excludes only
   `triggered_at`; `artifact_digest` covers the complete payload including
   timestamps.
7. Provide a reader for historical v1 and verified v2 plus optional rechecking
   against current local pack/input bytes. Label v1 `legacy-unverified`; never
   imply that v1 contained missing provenance.
8. State in every v2 artifact that these are local content digests, not a
   signature, audit opinion, compliance certification, or proof of
   source-system authenticity. Pack signing/approval, semantic pack migrations,
   and full Reconciliation-as-Code remain separate planned work.

## Consequences

- Under strict v2, the exact rule literal `0.100000000000000005` remains above
  source amount `0.100000000000000004`, so `greater_than` does not trigger.
  Explicit legacy v1 retains its historical rounded `0.1` boundary, warning,
  and triggered result.
- Current CLI/demo outputs are schema-v2 and self-consistent under both digests.
  Repeated equivalent decisions have the same decision digest even though
  timestamps and artifact digest can differ.
- Existing library callers keep their default behavior and may continue writing
  the old artifact. The v1 reader does not manufacture policy, pack, or input
  provenance.
- Input hashes include all sorted `*.csv` files because related-file rule
  operators can inspect any CSV in the input directory. They expose only base
  names, byte counts, and hashes—not local absolute paths or row contents.

## Rollback

Retain v1 reading/writing and the explicit legacy policy throughout its
compatibility window. Do not route current application callers back through an
implicit default, remove policy from v2, or relabel historical v1. Any future
writer must version its schema and preserve v1/v2 readers, exact-rule behavior,
digest verification, and the explicit non-signature trust boundary.
