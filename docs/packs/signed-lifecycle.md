# Signed control and industry pack lifecycle

The lifecycle boundary accepts a bounded JSON envelope only after exact publisher-key
verification. A package contains a strict manifest, declarative `pack.yml`-equivalent
metadata, declarative `rules.yml`-equivalent rules, dependency constraints, a supported
ReconForge version range, and synthetic golden rule identity. It has no entry point,
module path, script, binary, template execution, or network capability.

The state sequence is `submitted -> approved -> enabled -> disabled`. Submission and
approval require distinct actor identifiers. Installing a later approved version
disables the current one atomically. Rollback may reactivate only a previously approved,
disabled version; package rows and content digests are immutable. Every transition
records pack/version, action, actor, and content digest.

Before install, ReconForge rechecks platform compatibility, active dependency versions,
declarative rule conformance, supported operators, strict financial literals, unique
rule IDs, and the golden rule count/IDs. The store also re-verifies the signature under
the same trust-registry snapshot used during file admission.

Operational boundaries:

- publisher keys and approval actors are operator-managed inputs;
- the current registry is injected, not a production key-administration service;
- the SQLite store is local and does not claim HA or multi-node concurrency;
- upgrade means installing a complete new data-only version; no customer-data migration
  language or executable migration hook is accepted;
- built-in repository YAML packs are not retroactively described as signed third-party
  packages;
- signature verification proves possession of a trusted private key, not legal identity,
  quality, compliance, certification, or safety of business conclusions.
