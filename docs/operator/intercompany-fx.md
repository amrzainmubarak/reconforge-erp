# ICFX2 paired foreign trade

This version governs one paired trade source using two native functional-currency
books and a third explicit group adjustment legal entity. The source owns the
party-account receivable and payable movements. It is an experimental bounded
corporate management cycle; broader AP ownership and statutory qualification are
outside its contract.

The application uses the existing Finance Core journal, review, posting, exact
currency policy, native inverse and transactional outbox. SQLite returns an
explicit unavailable backend response. IC1 and FX1 retain their existing contracts.

## Capture and review

Select the organization/workspace and grant the complete seller, buyer and group
entity set. Seller and buyer functional currencies must differ. Select each native
journal and fiscal period separately. Freeze distinct native party, cash, trade,
realized/unrealized gain/loss account roles, and the explicit ten-role reporting
account map including CTA. Functional currencies come from immutable native entity
masters. Transaction and group reporting currencies are explicit.

Each rate contains the exact positive decimal string, source reference and UTC
effective timestamp on its operation date. Original transaction-to-functional
rates, settlement rates, and closing observations are separate reviewed captures.
Reporting translation captures group-to-functional rates by original contribution
date and closing date; canonical inverse conversion uses those exact rate
coefficients without constructing a rounded reciprocal rate.

The retained workspace binding pins one registry snapshot, including all four
currency policies. The supported policy is the existing `ROUND_HALF_UP`.
Rates are bounded to 12 integer and 12 fractional digits, precision 0–8. Native
line values are bounded to 4.5e18 minor units and journal turnover to 9e18.

## Whole-source phases and retry

Prepare, review every native entry, then publish the whole operation with three
different currently authorized humans and recent reauthentication. A manual
posting or inverse endpoint cannot detach one book from the owner. SQL independently
reconstructs the original functional carrying amounts, cumulative settlement
release, residual valuation, translation membership and group adjustment.

Each acknowledgement binds the original actor, exact command, scope, request,
source and digest. After a lost response retain the unchanged command ID and body.
Refresh the same source to inspect its current phase. A retry returns the original
phase acknowledgement; it never downgrades the displayed newer phase. Revoked
scope or permission denies a replay under current authority.

One pending operation is allowed. A source has at most 64 operations and 32 cash
settlements. Translation reads original effect contributions through a bounded
cursor, at most 512 lines. Source lists use a 50-row cursor. A posted final
elimination seals this source against additional settlement or valuation.

## Closing observation, inverse and native adjustment

Partial settlement releases the difference between historical conversion of
cumulative paid amounts. This preserves every original carrying minor unit when
the final installment is posted. A closing observation revalues the outstanding
transaction amount and posts the exact unrealized difference in each functional
book. Before a later cash installment, reverse the active observation through a
reviewed owner plan bound to its original native effects.

Native fiscal periods must be open for every new owner phase. The governed Master
Data fiscal-period status path records closing/reopening actors and reasons;
reopening requires a reason. Existing close-management approval and independent
reopen controls remain separate. A closed period preserves immutable history and
permits an exact already-committed acknowledgement replay under current authority.
This module does not introduce an alternate period or close engine.

Translation reads only this source's posted native GL effect snapshots. Monetary
party and cash balances use the captured closing reporting rates. Income/expense
contributions use their captured event-date reporting rates. CTA balances each
translated book explicitly, with its original effect IDs retained for drilldown.
The final group native journal reverses equal reviewed translated trade and
residual party balances. Unequal translated balances produce an ambiguity refusal.
The report distinguishes translated membership from actual native group effects.

## Synthetic independent result

USD10001 initially produces EUR12501 at 1.25 and GBP8001 at 0.8. USD3000 settlement
produces seller EUR3900 cash versus3750 carry (gain150), buyer GBP2340 cash versus2400
carry (gain60). Residual USD7001 is EUR9241 at1.32 versus8751 original carry (gain490)
and GBP5741 at0.82 versus5601 original carry (loss140). In the explicit USD report,
translated seller/buyer cash is2955/2854 and CTA equity is-531/+240. Native group
elimination is17002 debit and credit turnover. The final balanced management scope
retains net cash101, FX income563, FX expense171, result392 and CTA equity-291.
These are synthetic fixtures; actual acceptance refers to original native artifacts.

Run the independent no-ReconForge-import verifier against an exported complete
native cycle:

```text
python .github/scripts/verify_intercompany_fx_cycle_oracle.py original-cycle.json --output new-oracle-result.json
```

It uses exact `Fraction` arithmetic and verifies source/plan/snapshot/report seals,
three actor phases, native carrying and FX conservation, exact effect membership,
CTA and the actual native group adjustment. Output creation refuses overwrite.
Populated downgrade refuses to discard retained original history. Recovery uses a
verified native backup with the original schema, ACL, FORCE RLS, functions,
constraints, rows and command acknowledgements checked after restoration.

## Accounting context and qualification boundary

Functional, transaction and presentation currencies are separate accounting
concepts in the official [IAS21 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/).
The non-hyperinflationary closing versus transaction-date translation context is
described in the official [September2018 IFRIC update](https://www.ifrs.org/news-and-events/updates/ifric/2018/ifric-update-september-2018/).
An explicit translation adjustment and drilldown are also described in
[Dynamics financial consolidation reporting](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/generating-consolidated-financial-statements).
These sources inform the bounded management design. This implementation does not
qualify a statutory accounting framework, currency exchangeability assessment,
NCI, investment elimination, profit-in-stock, hyperinflation, USGAAP or country-tax
pack. Performance measurement remains deferred to the user.
