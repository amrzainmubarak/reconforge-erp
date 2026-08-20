# ADR 0444: Verify the nested retail-settlement decision digest

## Context

The retail POS-to-processor control already emitted an outer artifact digest,
but its report reader only checked that envelope. A caller could therefore
change a serialized decision, recompute the outer digest, and bypass the
report's own canonical decision identity. The source records are intentionally
not persisted by this local export control, so this slice cannot recompute a
provider settlement from live inputs; it can and must verify the serialized
run contract that was emitted.

## Decision

Keep the existing schema and report format, and add a nested verifier that:

- rebuilds the decision digest from the exact serialized algorithm, tolerance,
  input digests, and decisions;
- requires canonical decision ordering and the declared status-count map; and
- runs after outer artifact verification in the report reader.

The producer uses the same canonical helper, preventing producer/reader drift.
No network, provider, posting, persistence, or write-back behavior is added.

## Evidence and boundary

`tests/test_retail_settlement.py` proves the existing report contract still
passes and that a changed monetary decision is rejected even after the outer
artifact digest is recomputed. This is serialized artifact-integrity evidence,
not source authenticity, a cryptographic signature, live settlement finality,
or a statutory/production claim.
