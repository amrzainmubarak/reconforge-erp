# ADR 0258: Write-back intent API is proposal-only

## Decision

Expose `POST /api/v1/connectors/writeback/intents` as an authenticated local route for persisting a digest-bound proposal. It requires the dedicated `connectors.writeback.propose` permission and binds `requested_by` to the authenticated user. Identical requests replay idempotently through the append-only repository.

The route never dispatches a provider call, accepts no payload body beyond the closed intent contract, and returns an explicit `network_dispatch=disabled` marker. Approval, provider acknowledgement, compensation, and live integrations remain separate gates.
