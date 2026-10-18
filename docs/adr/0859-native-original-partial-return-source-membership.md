# ADR 0859: native original partial-return source membership

Date: 2026-10-15. Status: accepted for the bounded internal source adapter.

M6 defines exact partial-return arithmetic and unapproved correction templates.
Those content digests cannot attest invoice, FIFO consumption, original journal
or receipt membership. M7 supplies the missing internal PostgreSQL source mapping
over the existing CR1 source; it creates no replacement ledger or inventory engine.

The composing owner supplies its already authorized, hierarchy-scoped ordinary
connection and original CR1 envelope. The mapper checks that envelope against
fresh native source rows, original issue claims, valuation/movement/line membership,
the original operational invoice link, reviewed posting effects and actual receipt
allocations. FIFO order comes from the reviewed issue allocations, rather than
sorting layer IDs. The original inbound valuation carries currency policy only;
original consumption and posted COGS remain the cost authority. Actual invoice
NUMERIC quantity is read as text alongside retained quantity text and compared
through exact scaled arithmetic.

Posted commercial installments and genuine standalone Stock collections are
classified through their own existing links and reviewed two-line cash effects.
Their amount, captured currency, dimensions and three-person actors must match
the original invoice. Different cash accounts within the selected population are
refused in this first scope. No caller-supplied collected total proves membership.

Private observation wrappers retain canonical decoded content and fresh copies.
They do not claim original PostgreSQL byte identity; separately retained exact
SQL row texts provide that custody. The shared bounded JSON decoder rejects
duplicate/nonfinite/fractional number tokens. First scope remains zero tax,
functional currency, untracked base UOM, one original tranche/entity/location,
32 consumptions and at most200 captured receipt allocations.

The mapper performs SELECT statements only and supplies no authorization,
transaction, scope setter, claim, approval, command or posting boundary. Its owner
must pin current human permissions and scope grants before source waits, then
revalidate membership under customer→invoice→stock and existing inventory/period
locks. Once native CR2 history exists, its initial captured collected total must
stay immutable; subsequent collections become ordered, independently pinned
history events. Rebuilding that source from today's SUM would change history.

The actual current catalog distinguishes SELECT-only observer statements from
ordinary application ACLs: observed tables allow DML and enforce FORCE RLS and
native guards. Three selected inventory hooks are SECURITY DEFINER, owned by an
existing elevated schema owner. An invoker called from a definer inherits that
effective context. No new grant, function replacement or migration is introduced.

Native prepare/review/post/cancel/refund, additive restoration history over the
same layers, reciprocal CR1/full-inverse exclusion, shared credit-adjusted AR,
period/current-authority admission and versioned API/Studio are required next.
Migration147 is not installed or claimed by this adapter. Existing full inverse
uniqueness and immutable source history remain intact.

Six actual native adapter cases on agent sourcef3b6fac8 pass with zero skips;
12 before/after captures retain72 financial/source tables with unchanged exact
row texts and NUMERIC witnesses. The qualified initial five-unit Stock fixture
is22500, distinct from the45000 ten-unit commercial fixture. The original62d
failure and environmental/catalog preflight failures remain separate negatives.
Root's integrated frozen source and hosted gates must be qualified separately.
Independent original-row arithmetic is a finite source/proposal check, not proof
that any partial return has changed stock, AR or the GL. Performance is deferred.
