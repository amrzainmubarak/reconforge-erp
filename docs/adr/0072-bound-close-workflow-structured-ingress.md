# ADR 0072: Bind close-workflow files to structured-document ingress

- Status: Accepted
- Date: 2026-07-26
- Decision owners: domain-integrity, platform-security

## Context

The local close checklist accepted JSON state and JSON/YAML templates through direct standard-library and PyYAML calls. Domain normalization rejected invalid task shapes and statuses after parsing, but those call sites did not inherit the byte, depth, node, collection, scalar, alias, duplicate-key, non-finite, merge, cycle, multiple-document, unsafe-tag, symlink, and UTF-8 controls established by ADR 0071. The CLI already exposed stable general parse errors that must remain compatible and must not disclose a selected local path or input value.

## Decision

1. Route `close_workflow._read_template` through `read_json_document` or `read_yaml_document`, selected only by the documented JSON/YAML suffix, and route `load_close_checklist` through `read_json_document`.
2. Preserve the existing public `Close checklist template could not be parsed.` and `Close checklist JSON could not be parsed.` compatibility messages while retaining the stable structured rejection code as the exception cause for local diagnosis.
3. Preserve valid JSON/YAML task normalization, the legacy `title` alias, statuses, generated checklist shape, and output writers. Reject duplicate or unsafe structure before task normalization rather than accepting last-key-wins behavior.
4. Mark FI-011 bounded only after dedicated size/depth/duplicate/non-finite/alias/tag/document-count/safe-error tests and the exact direct-PyYAML AST allowlist pass. Remove the close-workflow PyYAML entry instead of retaining stale partial wording.
5. Keep R-018 open: this slice does not authenticate a template author, prove operational correctness, scan for malware, harden legacy XLS internals, cover generated/report/restore/Studio readers, or secure a future upload/connector deployment.

## Consequences

Valid documented close checklist and template files remain compatible, while hostile or over-budget JSON/YAML now fails before domain normalization. JSON templates using undocumented non-JSON suffixes no longer pass implicitly; the supported CLI contract already names JSON/YAML templates. Generic compatibility errors intentionally hide both paths and structured rejection details from the CLI surface. FI-011 is bounded, but neither close-task content nor workflow status is an approval, audit opinion, statutory close, or authenticated source statement.

## Rollback

Revert the two reader migrations, FI-011 inventory/status and direct-parser allowlist changes, finance-controls evidence links, dedicated tests, and bounded wording together. Do not restore direct parser calls while retaining FI-011 bounded status. If a legitimate document exceeds the shared limits, review a versioned successor policy and compatibility fixtures rather than bypassing controls at the close-workflow call site.
