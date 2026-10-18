# 0860 — Native partial corrections and chronological economics

Status: implemented experimental contract; final closure remains in the master matrix.

CR2 binds one original delivered/invoiced native stock tranche to immutable
original FIFO consumptions, original revenue/COGS effects and captured currency
policy. It uses the existing Finance Posting, Inventory and AR engines. A return
posts additive revenue/AR/refund-liability and inventory/COGS corrections; it never
labels a partial amount as the original sale's full inverse.

An immutable source history orders credits, later genuine collections, refunds
and governed corrections. Customer then invoice locks serialize its prefix caps.
The initial cash amount and later collection deltas remain actual cash; a credit
changes the collectible residual and can create a refundable liability. SQL
closure verifies native effect membership, exact amounts and original scope.

Each command retains its actor, exact request and original ACK. Retry admission
repeats current durable identity, monetary and hierarchy authority. Three distinct
humans prepare, review and post. Cancel retains unposted/voided evidence; posted
corrections require new reviewed inverses of the new owned effects.

Only the latest unreversed economic operation can be reversed. A layer-locked
immutable consumption count prevents reversing a return after later consumption,
including an older transaction that waited for the layer. This is a conservative
dependency rule: reversing that resale does not erase its consumption history.

Current IT1 adoption of restored layers uses a versioned cost capture containing
signed native corrections. Historical v1 verification remains intact; v2 checks
retained original membership and reuses that verifier after explicit equation
normalization. It does not demand that future consumption populations stay fixed.

The declared scope requires zero tax, functional currency and untracked original
base units. Quantities are scaled integers; proportional portions must represent
integral minor amounts exactly. Unsupported fractions, tax/FX original sources
or tracking contracts refuse explicitly and remain completion dependencies.

Revision147 checks original function bodies and execution metadata before shared
changes. Empty downgrade restores original functions; retained owner/history or
v2 transfer evidence refuses destructive downgrade. Populated rollback requires
the verified backup/restore procedure. Native, SQL, concurrency, browser and
populated-restore gates must pass on the final source before closure is claimed.
