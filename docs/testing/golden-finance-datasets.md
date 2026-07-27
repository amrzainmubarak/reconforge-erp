# Golden Finance Dataset Registry

`tests/golden/finance_registry.v1.json` is the versioned, synthetic-only source
of truth for bounded stock/GL golden cases. Its schema is
`docs/schemas/golden_finance_dataset_registry.schema.json`.

Each case records:

- an immutable case ID and semantic version;
- input schema and exact matching configuration;
- repository-relative input files with byte counts and SHA-256 digests;
- expected counts, ordered summary, signature v3, and selected financial-input,
  record-identity, and matching-ambiguity policies;
- a digest of expected output, a digest of the complete case, and a digest of
  the complete registry.

Run the gate with:

```bash
python -m pytest tests/test_golden_finance_datasets.py
```

Registry version 1.1.0 contains three cases, including bounded dense USD/JPY
equal-cost components under `unresolved-equal-cost-v1` plus a unique EUR pair.
The test validates the JSON Schema and all digest layers, rejects paths escaping
the repository, verifies exact file bytes, and compares Pandas plus DuckDB full
scan and forced partition output to the registry. A missing optional DuckDB
dependency is a disclosed skip, not parity evidence.

## Update policy

1. Use synthetic data only. Never add client, production, credential, or
   reversible private-mapping data.
2. Do not edit a frozen case in place to make a regression pass. Add a new case
   ID/version and increment the registry version. Retain the old case unless its
   continued presence is unsafe or legally prohibited.
3. A signature/policy/schema change requires its governing ADR and compatibility
   reader before expected outputs change. Record why the old digest changed.
4. Review input and expected-output diffs independently. Recalculate file,
   expected, case, and registry digests only after the new outputs have been
   explained and approved in review.
5. Run Pandas and DuckDB full/partitioned gates plus the full test suite. Record
   exact Python/Pandas/DuckDB versions; one environment does not prove the
   supported-version matrix.
6. Keep cases small and diagnostic. Performance datasets and benchmark results
   belong in the benchmark registry and must not be inferred from these cases.

The registry proves repeatable behavior for its named bytes, configuration,
policies, signature version, engines, and disclosed dependency versions. It is
not evidence of accounting correctness for an unrepresented use case, external
certification, production volume, or live service behavior.

`reconciliation-signature-v3` remains a decision/exception digest, not a full
configuration digest. The registry's expected/case/registry digest layers bind
the ambiguity policy to the expected signature. A future standalone rules-and-
decisions digest requires an explicitly versioned signature migration.
