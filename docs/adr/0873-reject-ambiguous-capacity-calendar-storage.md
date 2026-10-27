# ADR0873 — Reject ambiguous capacity restrictions before scheduling

Date: 2026-10-26. Status: implemented bounded safety repair.

The PostgreSQL calendar reader replaced unexpected persisted JSON types with empty
blackout or weekday sets. That could discard restrictions. Python also accepts
compact and week-date spellings through date.fromisoformat, while scheduling uses
exact string membership; a compact blackout or requested date could bypass the
same canonical day written as YYYY-MM-DD.

Require stored blackout restrictions to be date-string arrays and weekdays to be
arrays of exact integers0..6 (booleans and fractional numbers are refused). Invalid
persisted values raise capacity_persisted_data_invalid before reservation writes.
Both the domain calendar and scheduled-date input require parse.isoformat() to equal
the supplied text. API validation refuses noncanonical dates before persistence;
no hidden normalization or source rewriting is performed.

Canonical existing values, empty arrays, driver-decoded arrays and supported JSON
text remain valid. This is a validation tightening for a demonstrated restriction
bypass. Existing noncanonical/corrupt calendars require explicit operator correction
from their original source; do not restore the silent-empty fallback as rollback.
No schema change or implicit data migration is introduced. Parser byte/depth budgets
remain incomplete and are explicitly PARTIAL in the ingestion inventory.

Evidence retains27 malformed-data red cases and the real compact-date booking
bypass, then focused domain/API and native corrupt-JSONB refusal successors under
output/assurance-20261026/engineering-capacity-* and qa-program-capacity-*.
Native tests require unchanged reservation rows after refusal. Full ERP cycle and
performance acceptance are not inferred from these finite safety cases.
