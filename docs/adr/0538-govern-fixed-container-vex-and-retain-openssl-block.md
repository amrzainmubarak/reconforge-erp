# ADR 0538: Govern fixed container VEX and retain the OpenSSL release block

- Status: Accepted
- Date: 2026-08-22
- Scope: E-824 exact-image High-finding remediation

## Context

The E-823 gate reported five High matches in the exact Python 3.11.16 Alpine
runtime. Grype sourced all five from NVD CPE matching. Three matches named
CPython vulnerabilities even though the official CPython 3.11.16 source tag
contains their security backports:

- CVE-2026-3644: 3.11 backport commit
  `dae4b1a21f8df4570e30986affd61bbe4ade4cef` and the official 3.11.16
  release security record;
- CVE-2026-4224: 3.11 backport commit
  `642865ddf4b232da1f3b1f7abcfa3254c4bfe785` and the official 3.11.16
  release security record; and
- CVE-2026-7210: 3.11 backport commit
  `cbaecf9f16da611a646d507c1cbca265c588fc56`, followed by bundled Expat
  2.8.3 and then the signed `v3.11.16` tag.

The two remaining matches identify CVE-2026-14456 in Alpine `libcrypto3` and
`libssl3` 3.5.7-r0. OpenSSL's advisory states that 3.5.0 through 3.5.7 are in
the affected range and 3.5.8 is the repair. The current Alpine 3.23 and 3.24
repositories still offer 3.5.7-r0. A no-QUIC reachability argument was
investigated but is not equivalent to installing the upstream repair and has
not received independent human security approval.

## Decision

Adopt a source-controlled OpenVEX 0.2 document for **fixed status only**. Bind
its exact SHA-256, path, context, allowed status, and 30-day review ceiling in
the closed supply-chain policy. Grype applies the document to the native Syft
inventory. The repository validator independently checks that:

- the reviewed document hash, identity, timestamps, fields, and status are
  exact;
- every VEX product PURL exists in the exact image inventory;
- only a High finding can enter the governed ignored set;
- each ignored match has one exact Grype VEX `fixed` rule and a matching
  vulnerability/product decision; and
- every unsuppressed matching VEX decision, Critical suppression, stale
  review, unknown field, aliasing path, or subject drift fails closed.

Counts continue to include governed fixed matches. Evidence distinguishes
`vex_status: fixed` from active exceptions and records the VEX document ID,
hash, author, age, reviewed statements, and applied findings. VEX does not
reduce or reclassify scanner severity.

Do not add CVE-2026-14456 to VEX. Do not create a temporary exception. The two
OpenSSL findings remain release blockers until a rebuilt supported image
contains the upstream-fixed library or an independently approved, policy-added
disposition is supplied. Registry authentication and publication therefore
remain unreachable.

## Candidate evidence

Using Syft 1.51.0 native JSON and the same Grype 0.117.0 database:

| Official base candidate | Exact observed runtime | Critical / High | Decision |
| --- | --- | ---: | --- |
| `python:3.11-alpine` | Python 3.11.16, OpenSSL 3.5.7 | 0 / 7 in the untrimmed base; five remain in the ReconForge runtime | retain supported runtime; govern only the three demonstrably fixed CPython matches |
| `python:3.12-alpine` | Python 3.12.14, OpenSSL 3.5.7 | 0 / 5 | no security improvement and changes the container runtime |
| `python:3.13-alpine` | Python 3.13.15, OpenSSL 3.5.7 | 0 / 2 | outside the declared tested support matrix and still blocked by OpenSSL |
| `python:3.11-slim-bookworm` | Python 3.11.16, OpenSSL 3.0.20 | 10 / 38 in the untrimmed base | reject; materially larger current scanner surface |

The Alpine 3.23 and 3.24 package policies both reported 3.5.7-r0 as installed
and latest. This comparison is time-bounded local evidence, not a permanent
ranking of distributions.

## Security and correctness

This decision corrects scanner metadata with source/tag evidence; it does not
assert that an affected but unreachable component is safe. The gate still
returns blocked exit 1 for the two OpenSSL matches. Critical findings remain
non-exceptable, and the existing exception registry remains separate from VEX.

No financial amount, currency, matching decision, posting, evidence graph,
tenant boundary, database schema, API, CLI, or customer-data path changes.

## Compatibility

The container runtime bytes and supported Python 3.11/3.12 application matrix
remain unchanged. Container security evidence advances from schema v1 to v2
by adding explicit VEX identity and per-finding disposition fields. Historical
v1 evidence remains historical; consumers of the current checked evidence must
validate the v2 schema.

## Rollback

Reverting a fixed VEX statement restores the corresponding scanner match as a
release blocker. Removing the VEX mechanism is safe only if the rebuilt image
no longer produces any governed match or an equivalent independently verified
mechanism preserves exact product/advisory binding, review age, retained
evidence, and fail-closed behavior. Never roll back by broad ignore rule,
severity reduction, `--only-fixed`, or unreviewed `not_affected` status.
