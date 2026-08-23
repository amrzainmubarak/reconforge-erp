# ADR 0590: Record Docker Scout local image scan without overclaiming

## Status

Accepted — 2026-08-23

## Decision

Use Docker Scout against the explicit `local://reconforge:current` reference
for a reproducible local package vulnerability check. Record the image digest,
tool version, package count, severity result, and command. Do not silently fall
back to a registry image.

## Boundary

The result is local scanner evidence only. It does not replace hosted scanning,
registry provenance/signatures, malware analysis, license review, or production
runtime assurance.

## Rollback

Remove the dated scan note and ADR; no runtime or schema migration is involved.
