# ADR 0832: exact Money/minor-unit conversion under caller Decimal precision

Date: 2026-10-08
Status: Accepted for the bounded Finance conversion repair

## Problem

Canonical Money quantization already selects adequate local precision, but
`to_minor_units` multiplies in the ambient Decimal context and
`from_minor_units` divides in it. Both Finance adapters also use ambient
`Decimal.scaleb` for persisted amount text. Precision 3 turns 1234567.89 USD
into 123000000 integer units and makes the reverse interpretation inexact.
This violates exactness without any invalid input. Boolean units are accepted
by `from_minor_units` although the canonical MinorMoney boundary rejects them.

## Decision

Encode Money units through the existing exact multiplication primitive and a
context-independent power-of-ten Decimal tuple. Decode integer units through
the shared `minor_units_to_decimal` helper: retain the integer coefficient and
attach the recorded negative scale directly, without division or `scaleb`.
Use that decoder for both Finance adapters' amount text. Reject boolean and
non-integer units consistently; validate recorded scale in the existing 0–8
range. Money still resolves and retains its registry/policy metadata; adapter
readback still uses persisted precision rather than today's registry.

## Validation and compatibility

The independent oracle builds exact amount text from integer digits. Tests
cover zero, signs, huge values, 0/2/3/4/8 currency precision, low precision,
ROUND_DOWN, enabled Inexact/Rounded traps, randomized integer round trips,
canonical policy lineage, Finance supported-range refusal and SQLite
save/independent review/reconnect readback. Existing Money, strict/legacy input,
Finance policy/API and consolidation contracts remain required gates. The
restricted-role PostgreSQL lifecycle is a separately recorded live gate.

Public method signatures, amount strings for valid historical values, policy
digests, API/CLI/schema contracts, SQLite version 55 and PostgreSQL head 0106
remain unchanged. Boolean units were invalid monetary input and now fail
explicitly. This does not repair historical rows already rounded by callers,
or migrate every remaining classified legacy financial reader.

## Rollback and scope

Revert the three runtime-file changes and their regression tests together.
No data migration or destructive operation is involved. The old conversion
defect would return, so revert only with an explicit documented disposition of
the exactness finding. This bounded repair establishes no legal-book posting,
external settlement, capacity, availability, compliance or production claim.
