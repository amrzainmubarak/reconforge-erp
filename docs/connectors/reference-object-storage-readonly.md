# Reference object-storage read-only connector

`reference-object-storage-readonly` is a synthetic, transport-injected
S3-compatible object reader. Registration binds one exact HTTPS endpoint, one
tenant, one relative traversal-free key prefix, a runtime secret reference,
and bounded object count/size.

The connector sorts keys deterministically, supports a bounded cursor, verifies
each SHA-256 against the returned bytes, requires the tenant metadata to match,
and emits request/response digests. It never lists or reads another tenant's
objects and has no write/delete/presign behavior.

The repository deliberately does not bundle a cloud SDK or make network calls
for this reference slice. A provider adapter must implement the transport
protocol and separately prove endpoint, IAM, encryption, retry, pagination,
failure-injection, and credential-rotation behavior before live use.
