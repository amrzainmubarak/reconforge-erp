# Grouped-matching bounded mutation campaign v1

Date: 2026-08-02 (Africa/Cairo)

Campaign: `grouped-matching-mutation/synthetic-v1`

Three request-level mutants were executed against the public grouped-matching
application/strategy boundary:

| Mutant | Expected guard |
| --- | --- |
| left amount + $0.01 | decision digest changes |
| left amount - $0.01 | decision digest changes |
| disable partial settlement | decision digest changes |

Result: 3/3 mutants killed, 0 survivors, kill ratio `1`. The campaign is a
targeted financial sentinel; it is not a source-code mutation tool score.
Inputs are synthetic and bounded. PostgreSQL runtime parity, fuzzing, and
mutation coverage outside these three grouped-matching changes remain open.
