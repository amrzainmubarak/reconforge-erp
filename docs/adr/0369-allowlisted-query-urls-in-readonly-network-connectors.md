# ADR 0369: Preserve operator-declared query strings in read-only network connectors

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: Public and vendor REST APIs commonly require fixed query
  parameters for filtering, pagination, or response format. The connector
  manifest previously rejected every query string and the pinned transport
  silently discarded one if a lower layer supplied it. That made the generic
  read-only connector unable to represent an exact public endpoint safely.
- **Decision**: Allow a query string only when it is part of the exact,
  operator-declared `egress_destinations` URL. Registration still requires an
  exact string match, credentials in the authority and fragments remain
  forbidden, and non-visible ASCII URL text is rejected. The transport sends
  the declared path and query verbatim, never appends cursor or caller input,
  never follows redirects, and continues to pin DNS resolution to public
  addresses. Network sources may explicitly declare `none` authentication for
  public endpoints; those registrations carry no credential reference and emit
  no authorization header. Credentialed sources continue to use
  secret-reference authentication, and query values must not contain secrets.
- **Rationale**: This supports real fixed-parameter public-data endpoints
  without widening the host/path allowlist or introducing runtime URL
  construction. The exact endpoint and manifest remain part of the request and
  evidence digests, preserving replay and audit visibility.
- **Verification**: Network tests cover exact query registration, visible-ASCII
  rejection, query preservation in the pinned request target, redirect refusal,
  DNS-public-address checks, bounded retry, and secret/cursor/response limits.
- **Boundary**: This is a read-only connector contract. It does not claim live
  provider availability, data freshness, authentication interoperability,
  write-back, or production operations.
- **Rollback**: Restore the query rejection and transport target behavior in
  one commit; no migration or persisted-data rollback is required.
