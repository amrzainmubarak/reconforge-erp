# ADR 0254: API policy caching is explicit and mutation-invalidated

## Status

Accepted for the Phase 4 identity-policy slice.

## Decision

`create_api_app` accepts `policy_cache_enabled=False` by default. When enabled,
API permission dependencies use the bounded allowed-only cache for both all-of
and any-of permission contracts. The HTTP middleware invalidates the cache
after every non-safe request, including failed mutations, so cache freshness is
not an implicit authorization assumption.

## Safety boundary

Delegated and denied decisions are never stored. Existing deployments remain
uncached unless they explicitly opt in. The current invalidation scope is global
to the API instance; distributed invalidation and route-specific workspace
optimization remain future work.

## Rollback

Set `policy_cache_enabled=False` (the default) to restore uncached behavior;
the API contract and policy decision semantics remain unchanged.
