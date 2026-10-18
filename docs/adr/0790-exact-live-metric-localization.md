# ADR 0790: Preserve exact metric text through localization

Date: 2026-10-03. Status: accepted. Scope: PROD-018.

## Context and decision

Live metrics expose exact `value_text`, but the React view converted it through
`Number` and rounded to six fractional digits. Values beyond 2^53 and fine-scale
amounts therefore changed on screen. Format the canonical decimal string with a
BigInt integer, text fraction and locale-derived digits, separators and sign.
Reject malformed decimal text; retain trailing zeroes and signed zero. This
introduces no runtime dependency or change to stored money or API contracts.

## Verification and rollback

English and Arabic literal oracles cover large integers, long fractions, negative
zero and component rendering independent of the approximate numeric field.
Four component regressions failed before the fix. Web verification: 120 tests
passed, typecheck/build passed, and standard browser suite 16 passed with six
explicit opt-in skips. Separate live hosted browser evidence covers cookie-backed
metrics. Rollback is a source revert, but must not silently restore rounded
financial display. Invalid server decimals are not accepted as zero.
