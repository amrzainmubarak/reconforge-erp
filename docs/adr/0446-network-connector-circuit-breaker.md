# ADR 0446: Add a bounded network-connector circuit breaker

## Context

The provider-neutral HTTPS connector already bounded individual retry loops,
but repeated exhausted transport/5xx failures could cause every subsequent
read to start another retry loop. That behavior increases provider load and
weakens graceful degradation during an outage.

## Decision

`NetworkConnectorExecutor` keeps an in-memory circuit per connector, exact
declared endpoint, and credential reference (or the public lane). After a
bounded number of exhausted retryable transport or 5xx responses, it fails
fast with `connector_circuit_open` for a bounded
operator-configured window. An expired window permits one normal read path;
successful responses clear the failure state. Permanent HTTP responses and
local response-policy violations do not open the circuit.

The default is three exhausted failures and a 30-second open window. Values
are bounded at construction. State is process-local and intentionally does
not claim distributed quota coordination or provider availability.

## Evidence and boundary

`tests/test_connector_network.py` proves retry exhaustion opens the circuit,
the next read performs no transport call, a read after the window succeeds and
clears state, circuit state is isolated by endpoint and credential reference,
and invalid bounds are refused. This is local synthetic resilience evidence
only; no live provider, multi-process coordination, credential-vault, or
production SLO is claimed.
