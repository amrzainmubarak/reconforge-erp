"""Administrative cleanup for audit rows owned by a synthetic HTTP fixture."""

from typing import Any


def delete_owned_policy_audit(connection: Any, tenant_ids: tuple[str, ...]) -> None:
    """Join the caller's transaction; its rollback also restores the trigger."""
    assert connection.info.transaction_status.name == "INTRANS"
    assert tenant_ids and len(tenant_ids) == len(set(tenant_ids))
    assert all(tenant_ids)
    connection.execute("ALTER TABLE reconforge.domain_audit_events DISABLE TRIGGER domain_audit_events_immutable")
    connection.execute("DELETE FROM reconforge.domain_audit_events WHERE tenant_id = ANY(%s)", (list(tenant_ids),))
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.execute("ALTER TABLE reconforge.domain_audit_events ENABLE TRIGGER domain_audit_events_immutable")
    assert connection.execute(
        "SELECT count(*) FROM reconforge.domain_audit_events WHERE tenant_id = ANY(%s)", (list(tenant_ids),)
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgname='domain_audit_events_immutable' "
        "AND tgrelid='reconforge.domain_audit_events'::regclass"
    ).fetchone()[0] == "O"
