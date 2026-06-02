# Reconciliation Methodology

ReconForge ERP is built around explainable matching. Every match has a level, confidence score, and reason.

## Stock vs GL Matching

Level 1 exact matching requires:

- Stock `source_document` equals GL `reference`
- Stock `work_order` equals GL `work_order`
- GL `amount` equals stock `total_cost`

Level 2 fuzzy-reference matching supports common ERP reference formatting differences:

- GL `reference` contains stock `source_document`, or the reverse
- Work order matches
- Amount is within `amount_tolerance`

Level 3 amount/date proximity matching is used when references are weak:

- Work order matches
- Amount is within `amount_tolerance`
- Stock and GL dates are within `date_tolerance_days`

Unmatched records are classified as exceptions:

- Stock without GL
- GL without stock
- Value difference
- Date difference
- Reference mismatch

## Work-Order Controls

ReconForge checks whether spare-parts and workshop records support the expected operational trail:

- Stores must receive parts before issuing them to a work order.
- Direct purchase-and-fit cases are flagged because they can bypass stores evidence.
- Old parts should be returned for categories where policy requires a returned core or worn item.
- Closed work orders should not receive late stock issues.
- Work orders with actual cost should have a posted or paid invoice unless they remain in WIP.
- Cancelled purchase orders should not be linked to stock movements.

## Audit Trail

Generated reports include report parameters, timestamp, company name, tolerance settings, and local processing notes. The matching logic is deterministic so users can reproduce the same result from the same inputs and config.
