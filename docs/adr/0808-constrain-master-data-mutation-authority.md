# 0808: Constrain shared master-data mutations under selected authority

Status: accepted for the bounded contract below, 2026-10-03.

## Problem and decision

Five authenticated HTTP reproductions showed that selected entity authority could
alter its enclosing organization, and selected organization/entity authority could
alter tenant-shared currency or workspace-shared fiscal-period rows. Existing
scope selection and resource readability did not establish authority to mutate
the broader object.

Central policy now rejects these requests with `403 master_data_authority_denied`.
Only internal resource/action constants enter the evaluator. Policy evidence and
cache identity bind canonical authority and action. New evaluations use
`central-policy-v2`; the unchanged historical v1 shape and digest still verify.
Unknown, malformed and tampered versions fail closed.

Migration0096 adds invoker mutation triggers on organizations, currencies and
fiscal periods. They cover INSERT/UPDATE/DELETE/upsert, preserve all five scope
GUCs and check aliases consistently. An actual experiment rejected restrictive
UPDATE RLS for this purpose because it hid legitimate FOR SHARE references.
Mutation triggers retain those locks and valid entity-scoped Finance writes.
Current Master Data and Finance installers include the same guards; historical
migration SQL constants remain frozen.

## Evidence and boundary

`MASTER_DATA_AUTHORITY_2026-10-03.json` binds source hashes, before-fix HTTP
failures, the reference-lock experiment and the final combined gate:196 passed,
zero skipped,71 deprecation warnings in221.35s. PostgreSQL16.14 populated Finance
dump/restore preserved15 table digests, policies and legacy values; restored
nonowner scope denials and a permitted write passed. The native migration-chain
drill and PostgreSQL16.14/17.10 matrix through0096 also passed with unchanged
sources and owned resource cleanup.

Workspace-only currency administration remains tenant-shared under the existing
global `master_data.manage` permission. This does not introduce permission-to-
resource grants, alter Community SQLite, or prevent an application credential
from selecting its trusted scope GUCs. No complete platform-isolation claim is
made. The separate ca82 whole-repository run is retained as failed because one
health test had a stale migration count; it is not counted as this acceptance.

## Operation and rollback

Deploy through Alembic0096 and verify current revision with server health. Select
an independently granted parent scope to administer shared parent data. Narrowed
selection must return403 rather than silently widening authority. Existing data
is not rewritten or assigned guessed provenance.

Downgrading0096 removes its guards and retains rows; it intentionally removes
this protection. Use a maintenance window and the verified backup/restore path
when reverting. Keep privileged migration ownership separate from the runtime
role. The later immutable posting and reconciliation-sealing gates remain open.
