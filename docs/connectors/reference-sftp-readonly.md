# Reference SFTP read-only connector

`reference-sftp-readonly` is a synthetic, transport-injected SFTP integration
for proving the connector boundary before a real SSH provider is admitted.

The registration requires an exact credential-free `sftp://` egress URL, an
absolute traversal-free root, bounded file count/size, and a secret reference
resolved only at runtime. Reads are sorted deterministically, filtered by a
bounded cursor, and return content hashes plus request/response digests.

Only `.csv`, `.json`, and `.xml` files below the declared root are accepted.
The bundled implementation performs no socket or SSH operation; operators
must supply a separately reviewed transport adapter and provider conformance,
host-key, retry, failure-injection, and credential-rotation evidence before
calling it a live integration.
