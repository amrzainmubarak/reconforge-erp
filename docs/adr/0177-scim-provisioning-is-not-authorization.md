# ADR 0177: SCIM provisioning is not ReconForge authorization

- Status: accepted
- Date: 2026-07-28
- Task: P3-ENT-002 / E-172

## Context

SCIM 2.0 represents Users and Groups, but RFC 7643 deliberately leaves the
authorization meaning of group membership to the service provider. Treating
an external group label as a ReconForge role would let an identity provider
silently grant financial or administrative authority and would violate the
platform's deny-by-default and local-governance requirements.

## Decision

ReconForge uses the RFC 7643 User and Group schema URNs and a provider-neutral
application boundary. Provisioning resources are scoped by tenant and by a
configured provisioning domain. `externalId` is idempotent only inside that
pair. Client-supplied `id`, `meta`, passwords, roles, permissions, and unknown
attributes are rejected at the write boundary.

SCIM Groups are lifecycle containers only. They never map implicitly to
ReconForge roles or permissions. A future explicit, locally approved mapping
may reference a provisioned group, but it must be separately authorized,
versioned, audited, and tested for segregation of duties.

DELETE semantics will deactivate users and revoke their sessions rather than
erase identity or audit evidence. Protocol adapters must authenticate a
bounded credential, require the tenant and provisioning domain from trusted
server configuration, use version/ETag checks for mutation, and return SCIM
error schemas without internal details.

## Consequences

- Compromised or misconfigured upstream group assignment cannot directly
  create ReconForge authority.
- The same external identifier may exist in different provisioning domains
  without correlation or collision.
- Persistence, bearer-token custody, filters, PATCH/ETag, discovery endpoints,
  and full HTTP conformance remain subsequent E-172 slices and are not claimed
  by this application-boundary decision.

## Standards basis

- RFC 7643, SCIM Core Schema, sections 3, 4.1, and 4.2.
- RFC 7644, SCIM Protocol, sections 3, 3.5.2, 3.12, and 3.14.
