# Direct ERP Connector Roadmap

Status: roadmap design only. No real direct ERP connectors are implemented.

Required architecture before implementation:

- Read-only connector interface.
- Local credential and secret storage design.
- Connector audit logs.
- Rate-limit and retry policy.
- Explicit vendor-specific risk notes.
- Export-equivalent traceability for every imported row.

Boundaries:

- Existing ERP profiles are export-based profiles, not live connectors.
- No vendor endorsement or certification is implied.
- Direct connector work should wait until local security, backup, and deployment boundaries are stronger.
