# ADR 0588: Current Docker runtime smoke remains warning-visible

## Status

Accepted — 2026-08-23

## Decision

Record a current Docker image build and runtime smoke as bounded deployment
evidence. The smoke runs `doctor`, sample-data validation, and control-pack
validation inside the image. Validation warnings from deliberately synthetic
sample data remain visible and do not become zero-valued success signals.

## Boundary

The run proves local image construction and basic command startup only. It does
not prove registry signing, hosted provenance, image scanning, multi-arch
parity, production configuration, HA/DR, or deployment readiness.

## Rollback

Remove the dated execution record and artifact digest; no runtime or schema
migration is involved.
