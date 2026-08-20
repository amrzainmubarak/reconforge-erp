# ADR 0255: Management trial-balance projection remains non-statutory

## Decision

ReconForge may project a verified, balanced consolidation worksheet into a deterministic management trial-balance artifact. The artifact preserves account type, exact reporting-currency amount, worksheet digest, and source references, and it creates no posting effect.

The artifact is explicitly not a statutory financial statement, legal-book close, tax filing, or assurance conclusion. Statutory presentation, accounting-policy judgments, and external source-system write-back remain separate work.

## Rationale

This closes a useful explainability surface for close review without silently turning a non-posting worksheet into a regulated reporting claim.
