# ADR0874 — Preserve primary Studio source publication closure

Date: 2026-10-26. Status: implemented packaging correction; release remains blocked.

The real f3cfbad9 sdist omitted the browser harness HTML/TSX and screenshot-manifest
MJS because the e2e export pattern admitted only TS. The mandatory archive verifier
also retained149 revisions/head0150 while the official chain has155/head0156.

Admit only the required e2e source extensions (TS, TSX, HTML, MJS); keep node_modules,
dist and generated outputs outside the source archive. Add a closed STUDIO_REQUIRED
set to the existing committed-member/required-member/byte-parity verification.
Preserve all path/link/device/duplicate/safe-extraction and retained financial proof
checks. Bind migration defaults to the current exact count/head, with an independent
registry test that rejects future drift.

Three original contract failures and actual omitted archive members are retained.
Twenty focused publication/CI tests and independent QA pass. The rebuilt artifact
must still pass the actual complete publication inspector; unit tests alone do not
qualify the archive. No runtime logic or financial contract is changed. Reverting
this correction reopens reproducibility gaps and is not a qualified release rollback.
