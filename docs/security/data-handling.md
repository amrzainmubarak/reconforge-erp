# Data Handling

Implemented:

- ReconForge reads local ERP exports and writes local reports, DB records, evidence metadata, and backups.
- Canonical CSV/XLS/XLSX reconciliation, mapping header, direct DuckDB, and built-in CSV adapter reads use the bounded `tabular-file-ingress-v1` preflight documented in [file-ingestion.md](file-ingestion.md).
- Sanitized DB exports exclude password hashes, salts, session token hashes, raw tokens, secrets, and environment variables.
- Generated tests and examples use synthetic or sample data.

Partially implemented:

- Evidence registry stores file paths, checksums, provenance, redaction status, and links.
- Backups can include sensitive local business data and local credential verifier material needed for restore.
- An optional operator-configured S3-compatible adapter can store tenant-keyed evidence objects with checksum and retention metadata. ReconForge does not provide or mandate a hosted storage service, and artifact scanning/download/restore integration remains incomplete.
- Legacy XLS internals, JSON/YAML/generated-artifact resource budgets, malware scanning/quarantine, source authenticity, HTTP uploads, and future connectors remain incomplete under R-018.

Roadmap:

- More configurable retention guidance.
- Additional field-level data minimization controls for DB reports.

Not supported:

- ReconForge-operated cloud storage, SaaS backup, telemetry, or hosted data processing.
- Guarantees that user-provided files are free of sensitive data.
