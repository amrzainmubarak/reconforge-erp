# Currency Policy Registry

ReconForge resolves every canonical `Money` value against an explicit,
versioned currency policy before parsing or rounding it. Unknown codes fail
closed; the engine does not invent a two-decimal policy.

The bundled offline snapshot is `reconforge/data/currency_registry.v1.json`.
Its codes and minor-unit values are derived from SIX's ISO 4217 Maintenance
Agency List One published on 2026-01-01. `ROUND_HALF_UP` is a ReconForge policy,
not a rule supplied by ISO 4217. List-One entries whose minor units are `N.A.`
are intentionally excluded because they do not provide the precision needed by
`Money`.

## Controlled update

An operator or embedding application can install a complete replacement from
a local file before processing financial data:

```python
from reconforge.utils.money import CurrencyRegistry

manifest = CurrencyRegistry.load_file(
    "approved/currency-registry.json",
    expected_digest="<sha256-from-approved-change-record>",
)
print(manifest.registry_version, manifest.digest)
```

The input must satisfy `docs/schemas/currency_registry.schema.json`. Loading is
bounded to 1 MB, rejects duplicate JSON keys/currency codes, validates the
embedded and/or caller-supplied SHA-256 digest, performs no network call, and publishes the new
snapshot atomically only after full validation. `CurrencyRegistry.register()`
remains an explicit process-local compatibility surface for a single custom
policy; persistent deployments should use an approved snapshot.

`Money.to_dict()` retains the legacy amount/currency shape.
`Money.to_canonical_dict()` additionally records minor units, rounding policy,
policy digest, and registry provenance. Existing `Money` values retain their
resolved policy if the process installs a later registry; arithmetic between
the same code under different policies fails rather than silently re-scaling.

CSV stock/GL compatibility still assigns USD only when a currency column/value
is absent. A present but unknown code becomes a visible `unknown_currency`
data-quality exception and is excluded from matching.
