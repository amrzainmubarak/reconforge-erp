# Evidence-bound AP payment links

Status: accepted for the bounded `PROD-010` settlement-control slice.

Date: 2026-10-04

An approved supplier invoice and a posted Finance effect previously had no
retained, transactionally governed relationship. A caller could describe an AP
payment without proving that the exact financial entry, its independent review,
and the invoice state transition belonged to one operation.

This slice makes a settlement an immutable allocation link rather than another
posting mechanism. One link binds one approved supplier invoice to one reviewed
and posted `Manual` Finance effect in the same workspace, organization, legal
entity, and currency. The effect must have source identifier equal to its entry
identifier, a non-reversal two-line snapshot, an AP debit and a cash credit of
the same positive minor-unit amount, and external reference
`AP-PAYMENT:<supplier-invoice-id>`. No implicit currency conversion, floating
point amount, account substitution, or inferred posting date is accepted.

The Finance preparer, Finance reviewer, and Finance poster must be distinct.
The invoice creator and approver cannot post or settle that invoice. A
settlement command carries the current invoice version and an idempotency key.
Its retained request digest and response are immutable; reuse with a changed
actor or payload is refused. An audit event and transactional outbox event are
admitted before the link.

SQLite migration 54 and PostgreSQL revision `0105_pg_payables_payment_link`
each make the database, rather than an application follow-up, advance the
invoice. The link insert locks and checks the current invoice version in
PostgreSQL, and the trigger performs exactly one derived transition. Partial
allocations leave the invoice `Approved`; only exact cumulative allocation makes
it `Paid`. A unique invoice/version pair, an immutable link table, and trigger
checks prevent direct link insertion without the matching transition or direct
invoice payment-state mutation without evidence. Backup admission and restore
replay the ordered link history and re-verify its evidence graph.

Both directions of PostgreSQL revision 0105 first admit only a superuser or a
role with `BYPASSRLS`. Permission seeding and retained-evidence downgrade checks
otherwise risk observing an empty forced-RLS view. The migration-role acceptance
test proves refusal before link-table DDL, permission seeding, revision movement,
or destructive downgrade inspection.

The PostgreSQL adapter obtains the persisted amount from the reviewed effect
before amount-bounded authorization, so an API caller cannot choose the amount
used for policy evaluation. For an exact retained command replay, it instead
uses the immutable retained receipt amount; this preserves retry behavior after
a full allocation has moved the invoice to `Paid`. Both local and server APIs
expose only the closed payment-link projection.

This decision does not create automatic inventory, goods-received-not-invoiced,
invoice-to-GL, bank instruction, foreign-exchange, tax, intercompany, return,
void, or reversal behavior. Those require their own source/effect contracts and
recovery evidence. PostgreSQL live acceptance requires separately configured
administrator and nonowner application DSNs; absent services are explicit test
prerequisites rather than evidence of a live deployment.
