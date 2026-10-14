# CR1 original money read authority correction

Scope: application authorization in `postgres_customer_returns.py`. This checkpoint preserves migration126, the SQL `customer_return_authority(TEXT,TEXT,TEXT)` function, all source snapshots, plan digests, historical command responses, and posting/refund arithmetic. It adds no schema, permission, grant, endpoint, partial stock return, or monetary ceiling in PostgreSQL.

## Original counterexample

The independent native test at commit `d0ae7e00d9961c82f85a29159e7fa46f4d6f2509` created a governed KWD3 source: 0.001KG at unit price3,000,000 minor, invoice3,000 minor, original approved FIFO layer1,000 minor, consumed cost1 minor, and collected cash3,000 minor. The whole posted CR1 credit retained three return posting effects; seven original GL effects existed overall. A central maximum amount of KWD20 admitted twelve disclosures across four required read permissions: new preparation responses, current GET with embedded source/evidence, and historical preparation replay. The scoped list already refused its amount=None context and is not part of the reported gap.

The original red packet contains one failed native test, zero skips, suite duration86.819s. Its XML SHA256 is `003dfcee82ac1be69d56aa290aa09ee77e47f76f4632006520284ac629f932b9`. The independent original compatibility export is643,734 bytes with SHA256 `884e7d10d601dfae1a3be399f6348368235270066471b6cee9e5b612a9a09c3d`. These are retained originals; the application correction does not rewrite them.

## Resulting authorization contract

`customer_return_money_context` creates a private context copy. It takes the maximum of finite named monetary paths: original gross/net unit prices and source tax/total, invoice subtotal/tax/total, allocated cash, original FIFO allocation remaining/slice values, immutable consumptions, original COGS/revenue posting lines, retained return/refund scalars, and prepared posting lines. It excludes quantities, versions, discount percentages, timestamps, identifiers, and unrelated numeric metadata.

Every original quote, FIFO issue, native posting effect, and entry snapshot must retain the same captured currency code, precision, rounding policy, registry version, and registry digest as the original invoice. Integer values remain exact; booleans, strings, floats, missing values, negative amounts, oversized values, empty required populations, and incompatible policies refuse. A refund installment receives the entire original parent context for each outer permission, in addition to its own retained monetary scalars.

The current human row, active assignment/role/role-permission mappings, and original permission catalog name rows are SHARE locked before source or quantity waits. The permission catalog has no active field; this correction does not invent one. Current central authorization, scope checks, and mutation reauthentication remain in the shared owner. GET and refund balance use an unlocked preview, acquire current authority, SHARE lock the source plan, and repeat authorization before native closure/public projection. Original command replay repeats current authority around its source SHARE lock and returns its original response.

For captured bounded scopes, only nonempty captured levels require the corresponding effective durable grant. An existing workspace-only capture retains its existing empty-child fallback; the correction does not require three direct grants or create descendant expansion. An all-empty workspace/organization/legal-entity capture retains the explicit legacy global fallback, subject to the unchanged current human, permission, native hierarchy and central policy checks. Hidden or revoked applicable grants refuse. The standard synthetic CR1 fixture now seeds the three durable grants represented by its three bounded captured sets; production grants are unchanged.

## Development receipts

- Focused pure tests:51PASS, zero failures/errors/skips, pytest0.85s; XML `output/cr1-money-context-pure-v3.xml`.
- Ruff: all three affected Python files pass. Mypy: affected production module passes. Bandit: no finding in the affected production module.
- Isolated `-I` and `-I -O` original controls: both accept the captured red preparation response, derive3,000,000 minor at precision3, refuse boolean money, and retain the original canonical bytes. Captured input SHA256 `c8b93a277378b71f4ac20250412be215e42e69e7d8fa811aaa2f4e30d582648c`; original script/argv/stdout/stderr remain in `output/cr1-money-context-control-v1`.
- Historic schema working bytes remain SHA256 `54d8645c9ea393bfdad3eb7b62e1be878796770c9fe248026aa0d1a47949d402`.

Native green qualification is pending at this development checkpoint. Required acceptance includes the four real central cap cases/high-cap original controls, current permission and scope retirement, both authority/source wait orders, exact original source/command/native row preservation, legacy fallback and scoped inheritance controls. No migration147 is allocated by this correction and no SQL monetary ceiling is claimed.
