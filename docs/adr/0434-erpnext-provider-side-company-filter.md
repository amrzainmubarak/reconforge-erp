# ADR 0434: Bind ERPNext company scope in the provider query

- **Date:** 2026-08-07
- **Status:** accepted

## Context

The read-only ERPNext GL Entry adapter already rejected mixed-company pages,
but an unfiltered provider response could still transfer records outside the
requested company before the local guard ran. Frappe's REST listing contract
supports a JSON `filters` parameter and bounded `limit_page_length` alongside
`limit_start`.

## Decision

Extend the governed network executor with a closed, digest-bound tuple of
runtime query parameters. Keys are bounded identifiers, values are bounded
visible text, duplicate/colliding keys and non-canonical ordering fail closed,
and fixed operator-declared query text is preserved byte-for-byte. The ERPNext
adapter sends `filters=[["company","=",<expected_company>]]` whenever a
company scope is supplied and accepts an optional page length from 1 through
10,000. The existing response schema/company guard remains mandatory.

## Verification and boundary

Synthetic tests cover query ordering, duplicate/control rejection, fixed-query
preservation, URL construction, provider-side company filtering, page-length
limits, and request digest binding. This is a read-only provider contract; it
does not prove a live ERPNext tenant, provider authorization, completeness of
server-side filtering, or production isolation.

## Rollback

Remove the query-parameter argument, ERPNext filter/page-length options, tests,
documentation, and this ADR. Existing executor calls with no query parameters
retain their previous request digest and endpoint behavior.
