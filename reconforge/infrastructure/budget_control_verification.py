"""Verify retained exact budget decisions, independent ledger and evidence links.

Restore calls do not require an interactive principal. They must run after all
budget, currency snapshot, audit and outbox rows are restored in one transaction.
"""

from __future__ import annotations

import json
from typing import Any

from reconforge.domain.budget_control import BudgetControlError, BudgetDefinition, conservation, digest


def _json(value: Any) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise BudgetControlError("Budget retained JSON has duplicate keys.")
            result[key] = item
        return result

    if not isinstance(value, str) or len(value.encode()) > 65_536:
        raise BudgetControlError("Budget retained JSON exceeds its closed contract.")
    try:
        result = json.loads(value, object_pairs_hook=unique, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (TypeError, ValueError) as exc:
        raise BudgetControlError("Budget retained JSON is invalid.") from exc
    if not isinstance(result, dict):
        raise BudgetControlError("Budget retained JSON must be an object.")
    return result


def _evidence(repo: Any, row: dict[str, Any], evidence: dict[str, Any], actor_id: str, request_digest: str, action: str) -> None:
    prefix, parameters = repo._where()
    audit_table = "reconforge.domain_audit_events" if repo.tenant_id is not None else "audit_events"
    outbox_table = "reconforge.outbox_events" if repo.tenant_id is not None else "outbox_events"
    bind = "%s" if repo.tenant_id is not None else "?"
    # Adapter table/column/predicate choices are closed constants; IDs bind.
    audit = repo.connection.execute(f"SELECT actor_user_id,object_type,object_id,action,metadata_json FROM {audit_table} WHERE {prefix.replace('?', bind)}id={bind}", (*parameters, evidence.get("audit_event_id"))).fetchone()  # nosec B608
    event_key = "event_id" if repo.tenant_id is not None else "id"
    payload_key = "payload" if repo.tenant_id is not None else "payload_json"
    # Adapter table/column/predicate choices are closed constants; IDs bind.
    outbox = repo.connection.execute(f"SELECT aggregate_type,aggregate_id,event_type,{payload_key} FROM {outbox_table} WHERE {prefix.replace('?', bind)}{event_key}={bind}", (*parameters, evidence.get("outbox_event_id"))).fetchone()  # nosec B608
    if audit is None or outbox is None:
        raise BudgetControlError("Budget audit or outbox evidence is missing.")
    metadata = audit["metadata_json"]
    metadata = _json(metadata) if isinstance(metadata, str) else metadata
    payload = outbox[payload_key]
    payload = _json(payload) if isinstance(payload, str) else payload
    if (audit["actor_user_id"], audit["object_type"], audit["object_id"], audit["action"]) != (actor_id, "budget_control", row["id"], action):
        raise BudgetControlError("Budget audit identity or effect does not match retained command.")
    if (outbox["aggregate_type"], outbox["aggregate_id"], outbox["event_type"]) != ("budget_control", row["id"], action):
        raise BudgetControlError("Budget outbox effect does not match retained command.")
    for item in (metadata, payload):
        if item.get("request_digest") != request_digest or any(item.get(key) != row[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
            raise BudgetControlError("Budget evidence scope or digest does not match retained command.")
    if payload.get("audit_event_id") != evidence.get("audit_event_id"):
        raise BudgetControlError("Budget outbox does not retain its exact audit reference.")


def verify_budget_envelope(repo: Any, row: dict[str, Any], *, pending_version: int | None = None) -> None:
    BudgetDefinition(**{key: row[key] for key in ("budget_code", "name", "period_id", "currency_code", "limit_minor")})
    if row["status"] not in {"Draft", "Submitted", "Approved"}:
        raise BudgetControlError("Budget retained lifecycle is invalid.")
    if ((row["status"] == "Draft" and (row["submitted_by"] is not None or row["approved_by"] is not None or row["row_version"] != 1))
        or (row["status"] == "Submitted" and (row["submitted_by"] is None or row["approved_by"] is not None or row["row_version"] != 2))
        or (row["status"] == "Approved" and (row["approved_by"] is None or row["submitted_by"] is None
            or row["approved_by"] in {row["created_by"], row["submitted_by"]} or row["row_version"] < 3))):
        raise BudgetControlError("Budget retained maker-checker lifecycle is invalid.")
    prefix, parameters = repo._where()
    # `prefix` is the repository's closed engine-specific tenant predicate.
    events = repo._execute(f"SELECT * FROM budget_commitment_events WHERE {prefix}budget_id=? ORDER BY budget_version", (*parameters, row["id"])).fetchall()  # nosec B608
    balances: dict[str, tuple[int, str]] = {}
    reserved = consumed = 0
    history: dict[int, tuple[int, int]] = {1: (0, 0), 2: (0, 0), 3: (0, 0)}
    for version, raw in enumerate(events, 4):
        event = dict(raw)
        amount = event["amount_minor"]
        commitment = event["commitment_id"]
        if event["budget_version"] != version or type(amount) is not int or amount <= 0:
            raise BudgetControlError("Budget commitment ledger sequence or money is invalid.")
        if event["operation"] == "Reserve":
            if commitment in balances:
                raise BudgetControlError("Budget commitment reservation is duplicated.")
            remaining = amount
            reserved += amount
        else:
            prior = balances.get(commitment)
            if prior is None or prior[1] != event["source_reference"] or amount > prior[0]:
                raise BudgetControlError("Budget commitment ledger overdraw or source mismatch.")
            remaining = prior[0] - amount
            reserved -= amount
            if event["operation"] == "Consume":
                consumed += amount
            elif event["operation"] != "Release":
                raise BudgetControlError("Budget commitment operation is invalid.")
        if remaining != event["remaining_minor"]:
            raise BudgetControlError("Budget retained commitment balance differs from its exact ledger.")
        balances[commitment] = (remaining, event["source_reference"])
        conservation(row["limit_minor"], reserved, consumed)
        history[version] = (reserved, consumed)
        _evidence(repo, row, event, event["actor_id"], event["request_digest"], "budget." + event["operation"].lower())
    if (reserved, consumed) != (row["reserved_minor"], row["consumed_minor"]) or (events and row["row_version"] != 3 + len(events)):
        raise BudgetControlError("Budget cached balance differs from its independent immutable ledger.")
    # `prefix` is the repository's closed engine-specific tenant predicate.
    commands = repo._execute(f"SELECT * FROM budget_commands WHERE {prefix}budget_id=?", (*parameters, row["id"])).fetchall()  # nosec B608
    seen: set[int] = set()
    for raw in commands:
        command = dict(raw)
        request = _json(command["request_json"])
        result = _json(command["result_json"])
        scope = {key: command[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
        if digest({"scope": scope, "actor_id": command["actor_id"], "request": request}) != command["request_digest"] or digest(result) != command["result_digest"]:
            raise BudgetControlError("Budget exact command or result digest is invalid.")
        raw_version: object = result.get("row_version")
        if type(raw_version) is not int or raw_version in seen or raw_version not in history or result.get("id") != row["id"] or scope != {key: row[key] for key in scope}:
            raise BudgetControlError("Budget command scope, version or identity is invalid.")
        command_version: int = raw_version
        seen.add(command_version)
        r, c = history[command_version]
        if any(result.get(key) != str(value) for key, value in (("limit_minor", row["limit_minor"]), ("reserved_minor", r), ("consumed_minor", c), ("available_minor", conservation(row["limit_minor"], r, c)))):
            raise BudgetControlError("Budget retained command balance differs from exact ledger replay.")
        operation = request.get("operation")
        action = "budget.created" if operation == "create" else "budget." + str(operation).lower()
        if command_version == 1:
            if command["actor_id"] != row["created_by"] or any(request.get(key) != row[key] for key in ("budget_code", "name", "period_id", "currency_code", "limit_minor")):
                raise BudgetControlError("Budget definition differs from retained preparation evidence.")
        elif command_version in {2, 3}:
            if command["actor_id"] != row["submitted_by" if command_version == 2 else "approved_by"] or request.get("expected_version") != command_version - 1:
                raise BudgetControlError("Budget lifecycle differs from retained human review evidence.")
        else:
            event = dict(events[command_version - 4])
            if any(request.get(key) != event[key] for key in ("operation", "amount_minor", "operation_date", "source_reference", "reason")) or request.get("expected_version") != command_version - 1:
                raise BudgetControlError("Budget commitment differs from retained exact command.")
        _evidence(repo, row, result.get("evidence", {}), command["actor_id"], command["request_digest"], action)
    expected = set(range(1, row["row_version"] + 1))
    if pending_version is not None:
        expected.discard(pending_version)
    if seen != expected:
        raise BudgetControlError("Budget immutable command history is incomplete.")


def verify_sqlite_budget_storage(connection: Any) -> None:
    from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
    from reconforge.infrastructure.sqlite_budget_control import SQLiteBudgetControlRepository

    repo = SQLiteBudgetControlRepository(connection)
    for raw in connection.execute("SELECT * FROM budget_envelopes"):
        row = dict(raw)
        FinancePolicyStore(connection).entry(row)
        verify_budget_envelope(repo, row)


def verify_postgres_budget_storage(connection: Any, tenant_id: str) -> None:
    from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
    from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository

    repo = PostgresBudgetControlRepository(connection, tenant_id)
    for raw in connection.execute("SELECT * FROM reconforge.budget_envelopes WHERE tenant_id=%s", (tenant_id,)):
        row = dict(raw)
        FinancePolicyStore(connection, tenant_id=tenant_id).entry(row)
        verify_budget_envelope(repo, row)
