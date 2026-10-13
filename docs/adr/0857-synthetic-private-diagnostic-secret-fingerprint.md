# ADR 0857: Preserve secret scanning of diagnostic security fixtures

Accepted — 2026-10-14.

The original full-history Gitleaks run 38475492554 reported one
`generic-api-key` finding in the deliberate dummy-password constant of
`tests/test_browser_diagnostic_writer.py`, historical commit
`21fcd925db15dd9925cac650c129ab63beba199e`, line 22. The constant is test data;
it was never an identity, external-service credential or database password.

Use a short neutral `dummy-pass` constant in the current test. Retain only
the exact scanner-reported historical fingerprint in `.gitleaksignore`.
Source, tests, current fixture values and all other historical commits remain
scanned by the unchanged default rules. No path exclusion, entropy threshold
change or disabled rule is introduced. The original redacted finding and
failed job remain in private execution custody.

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
