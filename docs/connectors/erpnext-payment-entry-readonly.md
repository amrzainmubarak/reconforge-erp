# ERPNext Payment Entry read-only source

ReconForge includes a bounded ERPNext `Payment Entry` read adapter over the
governed HTTPS executor. It uses token credentials resolved only at request
time, offset pagination through `limit_start`, an exact resource path, an
optional provider-side company filter plus local response guard, and exact
Decimal text for paid/received amounts.

The adapter is read-only. It does not create or submit Payment Entries, infer
account mappings, settle a bank item, or authorize an accounting posting. The
registration and synthetic transport tests are a provider contract boundary;
an operator must add a real ERPNext sandbox and provider-version conformance
fixtures before calling it a live integration.
