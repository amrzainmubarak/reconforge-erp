# ADR 0057: Version Configuration Financial-Input Policy

- Status: Accepted
- Date: 2026-07-25
- Scope: YAML amount-tolerance ingress, current application selection, and default-config writing

## Context

`ReconForgeConfig.amount_tolerance` is stored as `Decimal`, but the historical
YAML path called `safe_load` before validation. An unquoted value such as `2.0`
therefore became a Python binary floating-point value before the versioned
financial parser saw it. Keeping the loader permanently on legacy-v1 would
preserve compatibility but could not prove exact current ingress. Switching the
existing loader directly to strict-v2 would reject common checked-in and user
configs even though their source lexemes were exact text.

The CLI, benchmark runner, and server-rendered Studio are current application
paths. Direct Python construction and `load_config` are public compatibility
surfaces and cannot change defaults silently before a breaking-release boundary.

## Decision

1. Add an explicit `financial_input_policy` to `load_config`. Its direct Python
   default remains warning `legacy-financial-input-v1`; unsupported policies
   fail before path access and do not echo the submitted identifier.
2. Under `strict-financial-input-v2`, parse through a private subclass of
   `yaml.SafeLoader` whose standard YAML floating-scalar constructor returns the
   original scalar text. Pydantic then validates the preserved lexeme through
   the strict amount parser. Integers, quoted decimals, and historical unquoted
   decimals remain supported; non-finite and malformed values fail closed.
3. Pass the selected policy to the existing field validator through Pydantic
   validation context. Direct `ReconForgeConfig(...)` construction retains the
   historical legacy-v1 behavior and warning contract.
4. Make all current production callers—six CLI commands, the benchmark runner,
   and Studio reconciliation loading—select strict-v2 explicitly. Extend the
   production AST perimeter so a future `load_config` call cannot omit policy.
5. Make the checked-in default configuration quote `amount_tolerance`; retain
   `write_default_config` JSON-mode serialization, which emits the Decimal as
   quoted YAML text. Equivalent canonical configuration values and downstream
   matching semantics remain unchanged.
6. Do not introduce a configuration document schema, signature, or digest in
   this bounded slice. Existing reconciliation evidence continues to disclose
   its execution financial-input policy, but that is not a claim that the YAML
   file itself is signed or independently provenance-bound.

## Consequences

- Current application configuration no longer passes a decimal YAML lexeme
  through binary floating point. A regression proves that
  `0.100000000000000005` remains exactly that Decimal under strict-v2, while the
  explicit legacy reader retains its historical `0.1` result and warning.
- Existing unquoted `2.0` files continue to work under current callers. New
  generated/example configs use quoted exact text, improving interoperability
  with readers that do not implement ReconForge's strict loader.
- Arbitrary Python YAML tags remain rejected because the customized loader is
  a `SafeLoader` subclass; YAML parser errors are wrapped without evaluating
  payloads.
- One lexical `float` occurrence remains in the shared YAML helper only as the
  standard YAML tag name intercepted to preserve text. ADR 0058 moved this
  helper out of `config.py` so rule packs can reuse the same safe boundary.
  Direct config/model compatibility defaults remain an explicit P0-005 item.

## Rollback

Keep the explicit legacy reader while its compatibility window is supported.
Do not route current application callers back through it or replace the safe
loader with a permissive YAML loader. A future configuration artifact schema
may supersede this boundary, but it must preserve unquoted historical reads,
strict exact-text behavior, safe-tag rejection, and a documented rollback path.
