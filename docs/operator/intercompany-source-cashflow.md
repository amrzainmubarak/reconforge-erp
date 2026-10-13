# Original paired-trade management cashflow

This additive read view covers one complete posted IC2 source and its native
group elimination. Its opening is the **source membership** before recognition,
not the legal entities' whole-book Cash balance. The caller must explicitly
retain that known zero origin, source digest and original recognition plan seal.
Unknown/nonzero openings, unfinished sources and uncovered Cash are refused.

Every seller/buyer Cash line is joined to its original native effect, snapshot,
account mapping, date, functional currency and three-person approved operation.
The original elimination supplies the reviewed historical date/rate map and
closing rate. Production delegates conversion to the existing canonical IC2
FX engine. Cash at its historical rate is classified as operating paired-trade
flow. Aggregate native Cash at the reviewed closing rate is the closing source
Cash membership. Their difference is the exchange effect on Cash, separate
from realized/unrealized income and CTA. No FX income total or report subtotal
is used as the input for that derivation.

The actual synthetic native fixture contains seller EUR Cash3900 and buyer GBP
Cash−2340. Historical reporting translation gives +3000/−3000 USD minor units;
closing translation gives +2955/−2854. Source operating net is0 and the exchange
effect/closing source Cash is101. The seven original effects contain18 native
lines. This does not establish bank movement or whole-company Cash101.

The caller has `intercompany_fx.read` and `finance_core.read`, current tenant,
workspace and organization authority, and the original three entity grants.
Existing IC2 authorization checks every emitted retained plan's current exact
amount scope. Requests select the organization without a single entity alias.
Both GET routes require all six opening query fields: `source_digest`,
`origin_plan_id`, `origin_plan_digest`, `seller_opening_minor`,
`buyer_opening_minor`, and `opening_basis` with the explicit value
`complete-native-source-origin-membership`. Neither amount has a default.

The view returns exact monetary strings. The original download retains native
JSON integer values for the independent CLI; consume those bytes with an exact
integer parser, preserve the response raw SHA/length, and do not reconstruct
the original from browser floating-point numbers. The native capture finishes
under the source SHARE lock before response headers. Streaming only encodes
captured primitives. The existing64MiB/1M-node artifact budget remains bounded;
Core2MiB posting and IC2 per-plan1MiB limits remain unchanged. A maximal source
does not imply every possible envelope fits: oversized evidence is refused
before download headers.

Run the standalone verifier with an externally retained original raw SHA:

```text
python -I .github/scripts/verify_intercompany_cashflow_oracle.py original.json --sha256 <original-sha256> --output fresh-proof.json
python -I -O .github/scripts/verify_intercompany_cashflow_oracle.py original.json --sha256 <original-sha256> --output another-fresh-proof.json
```

The stdlib-only verifier checks the raw anchor before parsing, original tenant
rows, source/plan/snapshot/registry seals, three-person phase and command ACK
membership, actual native lines/dimensions and original Cash business amounts.
`Fraction` derives historical flow, aggregate closing translation and the Cash
equation independently. Its fresh output uses exclusive creation. It does not
recompute the complete audit chain or assess legal qualification.

The golden fixture is a byte-exact authorized synthetic native export388945B,
SHA`00afc06b175e4fd3958624c058db8f28acd798b4d4a852cd7cc968de2fd2cb3b`.
The smaller native-shaped pure fixture is explicitly planned, not a database
execution claim. Original failed development receipts remain in the ignored
M3 output directory. Native and TestClient correctness evidence is distinct
from actual TLS/Studio execution, which is not yet claimed for this view.
The TestClient verifies eleven entire business/source/native tables and the
complete original source evidence unchanged; existing HTTP central-policy
evaluation audit events may append outside that original membership.

For reference, the IFRS Foundation's [IAS7 standard overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/)
describes operating/investing/financing classifications and cash reconciliation.
This engineering slice deliberately covers only reviewed paired-trade source
flows. It does not assert a complete statutory statement, IAS7 compliance,
investment/financing classification, cash equivalents or country qualification.
No database migration, ledger or FX engine is introduced. PostgreSQL is required;
SQLite returns an explicit unavailable response. Comparative performance remains
deferred for human measurement.
