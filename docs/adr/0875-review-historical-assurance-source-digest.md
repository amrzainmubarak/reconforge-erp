# ADR 0875: Admit one historical assurance source digest fingerprint

Accepted — 2026-10-26.

The hosted full-history secret scan identified one `generic-api-key` finding
in historical commit `4ce24156522c416e36c63131bc25c65fba98eeac`,
`docs/execution/ASSURANCE_2026-10-25.json`, line 80. The value belongs to
the `web_files_sha256` member and records a public source-file digest. The
original redacted finding remains retained; its classification is supported
by independent Git-blob and checkout-byte reconstruction, not by its label alone.

The report identifies source commit
`a91852a7b0e1f88bc77602a738556c059e8646a9`. Its referenced component's
original Git blob contains 9,530 LF bytes. Expanding each LF to the original
Windows checkout's CRLF representation produces 9,603 bytes whose SHA-256
exactly equals the scanner-flagged report value. The same source Git blob
exists at the finding commit and the report's entry commit. The LF Git-blob
digest and the CRLF checkout digest differ; neither is described as the other.

Add only the exact scanner-reported historical fingerprint and its current-tree
path/rule/line fingerprint to `.gitleaksignore`. The actual current-tree scan
also reports this same immutable evidence value. Admit that current fingerprint
only while the complete report and exact source-digest line match their reviewed
bytes. No path exclusion, regex allowlist, disabled rule, additional commit or
exception for a different local branch is added. The report and source stay unchanged.

The separately hash-pinned
[proof registry](../security/gitleaks-assurance-source-digest-20261025.v1.json)
records the original report blob, newline-inclusive line hash, JSON member,
source commit/path, LF blob hash, CRLF checkout hash, byte counts and explicit
transformation. The validator accepts only its exact two-fingerprint suffix after
the existing 115,541-byte ignore file. That complete earlier file and all
Wave5/diagnostic registries retain their original bytes and validation.
No Git installation or historical objects are required for archive-time policy
validation: immutable review metadata and complete ignore bytes are pinned.

The checked-out report is byte-for-byte the historical Git report after LF to
CRLF expansion. Cross-platform validation admits only the two independently
reviewed whole-report hashes (complete LF or complete CRLF representation),
the matching newline-inclusive line hash, and the exact JSON member/source/value.
It does not normalize arbitrary input or accept mixed newlines. Changed values,
keys, unrelated report content or bytes fail policy validation before scanning.

Regression tests refuse any unreviewed current-tree or extra fingerprint, altered commit
or line, changed prefix/comment/newlines, and changed proof key, source hash,
source commit or newline transformation. The actual hosted history and current
tree scans must pass on the successor commit before the secret-scanning gate
can close. A local scan of unrelated, non-ancestor branches is separate evidence
and is not grounds to broaden this exception.

Rollback removes these exact supplemental fingerprints, their registry/validator
admission and corresponding tests together; earlier ignore prefixes remain
unchanged. A real credential finding still requires incident handling and
rotation where applicable. This decision makes no release-acceptance claim.
