# Grouped matching 10K domain-diverse tier v1

This profile runs 2,500 independent partitions and exactly 10,000 synthetic
records through the public grouped strategy adapter and application service.
The six partition modes are:

- one-to-many
- many-to-one
- true many-to-many
- fee-aware portfolio netting
- FX-aware many-to-many (EUR to USD)
- portfolio partial settlement with deliberate unresolved ambiguity

Run it with:

```text
uv run --no-sync python -c "from reconforge.benchmark.grouped_matching_domain_scale import run_grouped_matching_domain_scale, verify_grouped_matching_domain_scale; result = run_grouped_matching_domain_scale(); verify_grouped_matching_domain_scale(result); print(result.to_manifest_text())"
```

The structural manifest digest excludes runtime and machine observations. The
verifier requires the declared 10K shape, exact mode counts, zero unmatched
partitions, expected partial ambiguity, zero adapter mismatches, zero
permutation mismatches, and non-empty decision/manifest digests.

This is one-host, one-process synthetic algorithm evidence. It is not a
throughput, distributed-capacity, soak, PostgreSQL-parity, provider, statutory
posting, or production-sizing claim. Carry-forward, sequence/window, and
reversal profiles remain separately bounded.
