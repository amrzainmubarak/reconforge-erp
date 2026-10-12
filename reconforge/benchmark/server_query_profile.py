"""Read-only, redacted pg_stat_statements discovery on an owned synthetic server.

Requires operator-enabled preload/extension and I/O timing. Never install these
on a user's server automatically. Password/financial parameters and SQL text are
not returned. Counters include nested statements and must not be summed into a
wall duration; JIT counters are separate observed compilation costs.
"""
from __future__ import annotations

import hashlib
from typing import Any

QUERY = """SELECT queryid::text,query,calls,total_plan_time,total_exec_time,rows,
    shared_blks_hit,shared_blks_read,shared_blks_dirtied,shared_blks_written,
    temp_blks_read,temp_blks_written,shared_blk_read_time,shared_blk_write_time,
    wal_records,wal_fpi,wal_bytes::text,jit_functions,jit_generation_time,
    jit_inlining_time,jit_optimization_time,jit_emission_time,toplevel
    FROM pg_stat_statements WHERE userid=(SELECT oid FROM pg_roles WHERE rolname=%s)
    AND dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
    ORDER BY total_exec_time DESC,queryid LIMIT 200"""
FIELDS = ("query_id", "statement_sha256", "calls", "total_plan_ms", "total_exec_ms", "rows",
          "shared_blks_hit", "shared_blks_read", "shared_blks_dirtied", "shared_blks_written",
          "temp_blks_read", "temp_blks_written", "shared_blk_read_ms", "shared_blk_write_ms",
          "wal_records", "wal_fpi", "wal_bytes", "jit_functions", "jit_generation_ms",
          "jit_inlining_ms", "jit_optimization_ms", "jit_emission_ms", "toplevel")


def _family(query: str) -> str:
    """Return only predefined code labels, never SQL-derived identifiers/data."""
    normalized = " ".join(query.lower().split())
    for fragment, label in (
        ("from reconforge.finance_entry_line_dimensions", "financial_line_dimensions"),
        ("from reconforge.finance_entry_lines", "financial_entry_lines"),
        ("from reconforge.finance_entries", "financial_entries"),
        ("insert into reconforge.finance_posting_effects", "posting_effect_insert"),
        ("pg_advisory_xact_lock", "transaction_advisory_lock"),
    ):
        if fragment in normalized:
            return label
    return "other"


def query_profile(connection: Any, runtime_role: str) -> dict[str, Any]:
    """Scope numeric observations to the actual restricted business role."""
    output = []
    for source in connection.execute(QUERY, (runtime_role,)).fetchall():
        values = list(source)
        family = _family(str(values[1]))
        values[1] = hashlib.sha256(str(values[1]).encode()).hexdigest()
        output.append({**dict(zip(FIELDS, values, strict=True)), "code_family": family})
    return {"status": "complete", "row_ceiling": 200, "statements": output,
            "scope": "pg_stat_statements runtime-role top-level and nested numeric counters; SQL text hashed only",
            "planning_timing": "total_plan_ms requires pg_stat_statements.track_planning; zero does not prove zero planning",
            "privacy": "no SQL text, parameters, credentials, identity names or financial rows retained"}
