# ADR0853: Reviewed public digest scanning and explicit evidence completion

Status: accepted for this draft integration,2026-10-10.

Evidence head2ca3b975 passed all16 native PostgreSQL shards and both package
closures, but failed one asynchronous FX component assertion and full-history
Gitleaks. Both original failures and their dependency skips are retained.

The260Gitleaks findings are64hex public source-file SHA256 values in two immutable
0b package reports, independently checked against111original Git blobs.
Retain default scanner rules and the closed generated-directory exclusion set.
Add only the520exact historical/current fingerprints, guarded by an independently
pinned review registry, full-report bytes and exact member/line/value hashes.
Reject substituted values at an ignored path/line, registry drift and extra or
missing fingerprints before scanning. This is false-positive classification,
not a credential-pattern waiver. Archive closure executes those guards under
isolated normal and optimized Python; actual full-history/tree scanners remain
separate mandatory security gates. No secrets or scanner binaries are added.

FX component tests must await the actual three-seal verification promise inside
React act. Hold the last real digest to prove busy/no success/no download before
completion; corrupt its byte to prove refusal. Preserve original financial and
authorization assertions. No runtime change, sleeps, retries, skip or timeout
extension is required.

Publish one repaired source and rerun complete hosted acceptance. Previous passing
subsets do not accept that source. Rollback removes the precise reviewed ignores
and their guard together, which restores the original scanner failure on retained
public reports; retain the reports and cryptographic financial proof throughout.
