# 0814: Context-independent quantities and FIFO cost allocation

Status: accepted for the bounded exact-arithmetic prerequisite, 2026-10-03.

## Observed failure

Both AR adapters normalized quantity12345 to12000 at Decimal precision2.
Both FIFO adapters allocated67 instead of66 for value199/quantity3/issue1.
An ambient arithmetic context therefore changed stored financial effects.

## Decision

Use Decimal only as an already validated exact coefficient container for AR.
Check a fixed-point expansion ceiling before formatting or ratio conversion;
canonical formatting does not normalize. Quantity multiplied by integer minor
price uses integer quotient/remainder and the existing HALF_UP line rule once.
FIFO partial cost uses integer HALF_EVEN with the existing representability
denials. Final consumption receives the entire remaining layer cost.
Stock quantities, cost input and display use bounded coefficient/scale arithmetic.
This does not select a currency rounding policy or change valuation strategy.

Preserve standalone SQLite AR strict-v2 grammar, including grouping, plus,
fractional shorthand, underscores and exact Decimal inputs. Preserve its long
local quantities, including tested5000-digit zero-price lines. PostgreSQL keeps
its existing80-character ingress and decimal shorthand; binary floats, custom
coercion, scientific text and ambiguous double-sign accounting input are
explicitly refused for new financial writes. Existing stock64-character ASCII
grammar, UOM0-6, currency0-8 and9e18 stored-unit limits remain unchanged.

One explicit additional limit bounds AR fixed-point expansion to1,000,000
characters, aligned to structured-document-ingress-v1. Compact Decimal extreme
exponents fail before expansion or financial mutation. A negative exponent
could previously expand beyond this bound; that behavior is deliberately
restricted. No schema, persisted reader or registry migration is needed.

## Evidence and limits

EXACT_TRADE_PRIMITIVES_2026-10-03.json binds the frozen227pass/0skip gate,
actual nonowner PostgreSQL16.14 through0098, SQLite, source equality, cleanup,
quality gates and original red probes. Hostile contexts enable every Decimal
trap and preserve flags. Actual two-layer FIFO issues0.66/1.83/0.51 exhaust
3.00 exactly; generated sequences are independently checked with Fraction.
Earlier grammar-tightening and fixture-order failures remain separate evidence.

Public aggregate transaction ownership is unchanged. These prerequisites do not
implement generated stock, AR, AP or payment effects in operational GL. PROD033
must separately capture retained AR monetary policy before historical major-unit
display. Rollback can restore the earlier code without migrating records, but
reintroduces context-sensitive arithmetic; inspect affected results explicitly.
