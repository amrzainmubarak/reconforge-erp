# ADR 0857: Preserve secret scanning of diagnostic security fixtures

Accepted — 2026-10-14.

The original full-history Gitleaks run 38475492554 reported one
`generic-api-key` finding in the deliberate dummy-password constant of
`tests/test_browser_diagnostic_writer.py`, historical commit
`21fcd925db15dd9925cac650c129ab63beba199e`, line 22. The constant is test data;
it was never an identity, external-service credential or database password.

Use a short neutral `dummy-pass` constant in the current test. Retain only
the two exact scanner-reported historical fingerprints in `.gitleaksignore`.
Source, tests, current fixture values and all other historical commits remain
scanned by the unchanged default rules. No path exclusion, entropy threshold
change or disabled rule is introduced. The original redacted finding and
failed job remain in private execution custody.

The independent original PR135 scan also reported the same immutable source
blob in `6eca23f47a082a438f32db80503569b814b431f2`, line22. Its original
redacted artifact11856565136 has ZIP SHA256
8ed843610e66809dec5ae0cdb48d75a438b87b6313dd3a264d43a21724657b19.
Both historical source blobs SHA2563074c0b0c2dbc3210a6f824f6458138449f1494d44e81a9a6a61bcfb5faafcbd
and exact line SHA2569bb02a07774d1535e467e2d26d1359396a94196607bd48c98a91dba4be1efdee
were independently read from Git. The frozen Wave5 registry and its complete
115246-byte ignore prefix stay byte-identical. A separately pinned supplement
admits exactly those two historical fingerprints as an exact suffix; it cannot
admit a current-tree fingerprint, new source path or unreviewed exception.

This decision does not authorize accepting real secrets. The independently
generated local PostgreSQL fixture whose synthetic password appeared in a
private diagnostic was invalidated and replaced; its original evidence file
was preserved without putting either credential into Git.

Verification requires the focused diagnostic writer/security cases and the
actual hosted history and current-tree scans on the new source. Until those
complete, the earlier failed secret-scanning job remains a failure. Revert
the neutral test constant and this exact historical fingerprint together if
the fixture is intentionally restored. No business, permission or database
contract changes.
