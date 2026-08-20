# Ownership-change adjustment v1

Date: 2026-08-02 (Africa/Cairo)

The bounded pure-domain contract `ownership-change-adjustment-v1` calculates a
non-posting, policy-bound three-line proposal from exact Decimal ownership and
source monetary inputs. The NCI effect is rounded by the declared currency
policy; its rounding delta is retained, and the parent-equity line balances the
rounded NCI and signed consideration effects exactly.

The focused suite contains eight tests covering balance, digest replay,
rounding visibility, currency rejection, maker-checker separation, and payload
tamper detection. It is not statutory accounting validation, a journal-posting
test, goodwill/purchase-price allocation, or a production consolidation claim.
