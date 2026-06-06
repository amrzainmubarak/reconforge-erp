# Data Handling

Implemented:

- ReconForge reads local ERP exports and writes local reports, DB records, evidence metadata, and backups.
- Sanitized DB exports exclude password hashes, salts, session token hashes, raw tokens, secrets, and environment variables.
- Generated tests and examples use synthetic or sample data.

Partially implemented:

- Evidence registry stores file paths, checksums, provenance, redaction status, and links.
- Backups can include sensitive local business data and local credential verifier material needed for restore.

Roadmap:

- More configurable retention guidance.
- Additional field-level data minimization controls for DB reports.

Not supported:

- Cloud storage, SaaS backup, telemetry, or hosted data processing.
- Guarantees that user-provided files are free of sensitive data.
