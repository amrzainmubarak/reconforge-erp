# PostgreSQL quality direct-update boundary — 2026-10-28

Entry source `c44a71110dd63f3ef2372c0bc8d451f91d3424d7`. A synthetic
restricted-role test demonstrated that `update_ncr` accepted a direct
disposition without independent reviewer evidence. The change in ADR0881
checks a matching independent authority and audit digest before a new
disposition update, within the existing transaction. It preserves an identical
persisted disposition as a locked, read-only replay and denies reverting a
later state. The API binds the actor to its authenticated principal; the
repository itself accepts a caller-supplied actor and does not establish that
the caller is that actor. Arbitrary SQL, entity isolation and the quality to
stock/GL linkage remain outside this guard.

Final local synthetic PostgreSQL 16 test: 3 passed, 0 skipped, 29.509 s
including setup; ordinary role without superuser/BYPASSRLS and FORCE RLS.
The synthetic runner grants that role broad table privileges in the schema;
this test is not evidence for production least-privilege grants.
Evidence: `output/quality-entity-probe-9e8080c4e2d7/result.json` and its
pytest log. The two recorded file hashes match the tested source and test:
`087edc53ac4c7eedbda3f351a60d52c1de5985a23d9bbee81b57406145e39582`
and `8d83f748b6313dd64b8bab2ed5c6630a276b2462f260fe8895885f432606bb2b`.
The runner captured those hashes at start, not a before/after digest of the
whole tree. Tests cover denial, API disposition, full-field tampering, a UTC
to Africa/Cairo replay without an update, rejection of a modeled later state,
and rollback of reviewer/audit writes on injected failure.

The retained negative `output/quality-entity-probe-13de27e9028b/` used the
`quality_old_guard` pytest plugin to reconstruct a guard with replay and state
checks removed; it produced two failures and one pass. The plugin is at
`output/quality_old_guard.py` with SHA-256
`31933a71f49a09d732135175e807d2e658c1db5f8290bb3b6b504c296cf22c9f`.
It is a diagnostic mutation, not a byte-identical frozen prior-source run.
Earlier RED evidence and the separate entity-isolation probes remain preserved.
Local Ruff and mypy passed for the changed source; hosted final-source checks,
native upgrade/restore, and identity and entity boundaries remain separate.
