# ADR 0368: Keep the reliability API in one importable package namespace

## Status

Accepted — 2026-08-05

## Context

ReconForge had both `reconforge/reliability.py` and the package directory
`reconforge/reliability/`. Source-tree imports could resolve the package, while
an installed non-editable distribution could resolve the module file first and
make `reconforge.reliability.ha_dr` unavailable. The HA/DR quorum verification
script therefore failed only after installation.

## Decision

Retain the existing public `reconforge.reliability` API in
`reconforge/reliability/__init__.py` and remove the duplicate module file. The
package directory is the sole owner of the namespace, including `ha_dr`.
Add a regression contract that the duplicate file is absent and that the
quorum script runs through the package import path.

## Consequences and limits

This removes an ambiguous distribution surface without changing the public
symbol names. A fresh non-editable Python 3.12 environment must be used for
installed-package verification; existing environments can retain stale orphan
files until recreated. This fixes importability only and does not turn the
quorum simulation into deployed HA/DR evidence.

## Rollback

Restore the removed module only with a versioned compatibility design that does
not coexist with the package directory; otherwise revert this ADR and its
regression test as one change.
