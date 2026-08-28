# ADR 0536: Canonicalize client-pack publication path identities

- Status: Accepted
- Date: 2026-08-22
- Scope: E-822 client-pack transactional publication compatibility

## Context

Client-pack publication enumerates hidden staging, rollback, and transaction
marker siblings from a resolved output parent, then compares them with the
expected paths before any rename. When a caller supplied a relative output
path, `mkdtemp` returned a relative staging path while sibling enumeration
returned absolute paths. The same directory therefore compared unequal and a
fresh `reconforge demo run --output output/demo` failed closed as an ambiguous
recovery state. Existing tests used absolute temporary paths and missed the
CLI contract.

## Decision

Convert only the expected publication sibling identities to lexical absolute
paths before set comparison. Keep all sibling names, bounded enumeration,
marker validation, tree digests, rename order, ambiguity refusal, and returned
caller-facing artifact paths unchanged. Add a regression that publishes from
relative source/output paths and requires complete temporary-sibling cleanup.

## Security and correctness

The normalization uses `Path.absolute()` for identity comparison and does not
resolve or authorize an untrusted link. Existing reparse/symlink validation and
fail-closed marker checks remain in force. No malformed, unknown, or extra
sibling becomes accepted.

## Compatibility

Previously valid absolute paths are unchanged. Relative CLI/service paths now
perform the documented publication instead of failing on an identity mismatch.
Artifact bytes, schemas, digests, financial-input policy, and recovery states do
not change.

## Rollback

Revert only if publication comparison is replaced by another representation
that proves relative and absolute spellings of the same expected sibling are
identical while retaining the unknown-sibling refusal and regression test.
