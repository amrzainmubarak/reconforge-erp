# AMLSim public synthetic sample

`tx.csv` is an unmodified copy of `sample/outputs/tx.csv` from IBM/AMLSim commit
`7338a4bcb1af9bcfea2201ad7daccfe2a4d569ca`, retrieved 2026-10-03.

Source: https://github.com/IBM/AMLSim/blob/7338a4bcb1af9bcfea2201ad7daccfe2a4d569ca/sample/outputs/tx.csv

SHA-256: `d119a5b009a99958a23054ba8b403a6f410cf79d62c60e3104240d927d821ce8`.
The upstream Apache-2.0 license is preserved verbatim in `LICENSE`, SHA-256
`c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`.
No upstream implementation or legacy dependency stack is incorporated.

Attribution requested by upstream: Toyotaro Suzumura and Hiroki Kanezashi,
AMLSim / Anti-Money Laundering Datasets, 2021, https://github.com/IBM/AMLSim/.

This synthetic sample has 45 records. Currency and calendar epoch are absent.
ReconForge assigns those explicitly in its workload profile and seeds four
reconciliation faults in derived records. Neither assignment nor seeded fault
is an original upstream assertion. This is not evidence of AML detection or a
customer deployment. ReconForge's own source retains its MIT license.
