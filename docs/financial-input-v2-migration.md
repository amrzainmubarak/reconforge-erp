# Financial input v2 migration

ReconForge now defaults every financial-input policy to
`strict-financial-input-v2`. Python and NumPy floating scalars are rejected
before conversion because their original decimal lexeme is already lost.

Use exact text, `Decimal`, integers, or minor units:

```python
from decimal import Decimal

from reconforge.config import ReconForgeConfig
from reconforge.utils.money import Money, parse_amount

amount = parse_amount("0.100000000000000005")
money = Money(Decimal("12.34"), "USD")
config = ReconForgeConfig(amount_tolerance="0.05")
```

The following now fails instead of warning and accepting an approximation:

```python
Money(0.1, "USD")
ReconForgeConfig(amount_tolerance=0.1)
```

For temporary replay of an identified historical contract only, select the
legacy reader explicitly:

```python
from reconforge.utils.money import LEGACY_FINANCIAL_INPUT_POLICY, parse_amount

legacy_amount = parse_amount(
    historical_value,
    input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
)
```

Do not use the legacy policy for new imports, rules, reconciliations, reports,
or generated artifacts. Historical schema readers continue to infer legacy
semantics only where the stored version requires them.

Default-generated manifests and reports now record the current strict policy.
If a consumer expected an unversioned/legacy direct-Python artifact, update it
to the current schema reader before upgrading. See ADR 0097 for the complete
boundary and rollback policy.
