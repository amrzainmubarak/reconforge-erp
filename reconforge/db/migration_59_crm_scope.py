"""Preserve unambiguous legacy quotation lines and bind new lines to workspace."""
from __future__ import annotations

import sqlite3

CRM_AUTHORITY_SQL = """
CREATE TABLE IF NOT EXISTS crm_quotation_authorities (
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    identity_contract TEXT NOT NULL CHECK(identity_contract='canonical-user-v1'),
    PRIMARY KEY(workspace_id,quote_id),
    FOREIGN KEY(workspace_id,quote_id) REFERENCES crm_quotations(workspace_id,quote_id)
);
CREATE TRIGGER IF NOT EXISTS crm_authority_no_update BEFORE UPDATE ON crm_quotation_authorities
BEGIN SELECT RAISE(ABORT,'Quotation authority is immutable'); END;
CREATE TRIGGER IF NOT EXISTS crm_authority_no_delete BEFORE DELETE ON crm_quotation_authorities
BEGIN SELECT RAISE(ABORT,'Quotation authority is immutable'); END;
"""

CRM_SCOPED_LINES_SQL = """
CREATE TABLE IF NOT EXISTS crm_quotation_lines (
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_minor INTEGER NOT NULL,
    discount_bps INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(workspace_id,quote_id,line_number),
    FOREIGN KEY(workspace_id,quote_id) REFERENCES crm_quotations(workspace_id,quote_id)
);
"""


def execute_crm_schema(connection: sqlite3.Connection, script: str) -> None:
    """Execute owned DDL without executescript's implicit transaction commit."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise sqlite3.DatabaseError("Incomplete CRM migration statement")


def upgrade_crm_lines(connection: sqlite3.Connection) -> None:
    """Never guess ownership for collided or orphaned historical lines."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(crm_quotation_lines)")}
    if not columns or "workspace_id" in columns:
        return
    connection.execute("SAVEPOINT crm_scope_upgrade")
    try:
        ambiguous = connection.execute("""
            SELECT l.quote_id FROM crm_quotation_lines l
            LEFT JOIN crm_quotations q ON q.quote_id=l.quote_id
            GROUP BY l.quote_id,l.line_number HAVING COUNT(q.workspace_id) != 1
            LIMIT 1
        """).fetchone()
        if ambiguous is not None:
            raise sqlite3.IntegrityError("Ambiguous legacy CRM lines require reviewed source recovery")
        connection.execute("ALTER TABLE crm_quotation_lines RENAME TO crm_quotation_lines_legacy59")
        connection.execute(CRM_SCOPED_LINES_SQL)
        connection.execute("""
            INSERT INTO crm_quotation_lines
            SELECT q.workspace_id,l.quote_id,l.line_number,l.item_id,l.description,
                   l.quantity,l.unit_price_minor,l.discount_bps
            FROM crm_quotation_lines_legacy59 l JOIN crm_quotations q ON q.quote_id=l.quote_id
        """)
        connection.execute("DROP TABLE crm_quotation_lines_legacy59")
        connection.execute("RELEASE crm_scope_upgrade")
    except BaseException:
        connection.execute("ROLLBACK TO crm_scope_upgrade")
        connection.execute("RELEASE crm_scope_upgrade")
        raise
