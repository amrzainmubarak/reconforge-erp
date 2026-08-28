# ADR 0595: Add an offline boundary to hardened container smoke

## Status

Accepted — 2026-08-23

## Decision

The required CI and release-candidate hardened image smoke runs with
`--network=none` in addition to a read-only root filesystem, dropped
capabilities, and `no-new-privileges`. `reconforge doctor` is an offline local
operator check and must not need ambient network access to start or validate
the synthetic sample boundary.

## Boundary

This catches hidden network dependencies in the documented local smoke. It
does not prove egress controls for other commands, host firewall policy,
service-to-service connectivity, or production network segmentation.

## Rollback

Remove the network isolation flag and this ADR. No runtime, schema, or data
migration is involved.
