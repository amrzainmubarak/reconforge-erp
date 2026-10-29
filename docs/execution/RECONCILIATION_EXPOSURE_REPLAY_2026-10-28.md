# Reconciliation exposure, authorization and replay investigation

Entry source `c44a71110dd63f3ef2372c0bc8d451f91d3424d7`; synthetic data.
`reconforge/api/routes/reconciliation.py::_policy_amount` performs `abs` and
addition under the caller's Decimal context. At precision 3 the exposure for
`1234.56` becomes `1.23E+3`; a reference `Fraction` retains `1234.56`.
Parenthesized input can round inside the existing parser before summation.
The route passes the derived value to the permission boundary. A test using an
artificial amount ceiling showed the difference can alter that simulated
decision; no production policy bypass or configured ceiling was established.

An isolated-context draft passed 54 focused cases with one PostgreSQL skip; an
independent reviewer checked 600 synthetic cases against `Fraction`. It is
retained as `output/erp-vision-20261028/draft-exposure-precision-legacy-retry.patch`
and is not applied. Existing `policy_amount` participates in the stored run
fingerprint: changing it can reject the retry of a previously rounded request.
Existing workers read the historical value; a supplied `input_hash` alone does
not prove a complete, unaltered input set. The existing scalar amount also does
not express a currency conversion policy for mixed-currency submissions.

A safe versioned transition needs a full canonical input comparison under the
run lock for a legacy retry, a fresh authorization using supported exact
exposure, no writes or inferred history on matching retries, and rejection of
changed, omitted, duplicate or additional records. New policy needs explicit
currency and version binding; claim and worker authorization must use the
appropriate immutable snapshot. Old checkpoints and results need their own
review rather than silently acquiring new semantics. Test restricted-role
PostgreSQL, concurrent mutation, failure/rollback, upgrade and populated
restore before claiming completion. These remain open, along with the separate
grouped FX precision and replay issue.
