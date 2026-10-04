"""SQLite migration for evidence-bound supplier-invoice settlement links."""


SQLITE_PAYABLES_PAYMENT_LINK_SQL = """
CREATE TABLE ap_payment_links (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    supplier_invoice_id TEXT NOT NULL REFERENCES ap_supplier_invoices(id) ON DELETE RESTRICT,
    finance_effect_id TEXT NOT NULL UNIQUE REFERENCES finance_posting_effects(id) ON DELETE RESTRICT,
    finance_entry_id TEXT NOT NULL UNIQUE REFERENCES ledger_entries(id) ON DELETE RESTRICT,
    ap_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    cash_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
    currency_code TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    finance_validation_digest TEXT NOT NULL
        CHECK(length(finance_validation_digest)=64 AND finance_validation_digest NOT GLOB '*[^0-9a-f]*'),
    finance_posted_actor_id TEXT NOT NULL,
    settlement_actor_id TEXT NOT NULL,
    invoice_version_before INTEGER NOT NULL CHECK(invoice_version_before > 0),
    audit_event_id TEXT NOT NULL REFERENCES audit_events(id) ON DELETE RESTRICT,
    outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(supplier_invoice_id, finance_effect_id),
    UNIQUE(supplier_invoice_id, invoice_version_before),
    CHECK(ap_account_id <> cash_account_id)
);

CREATE TABLE ap_payment_link_commands (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
    settlement_actor_id TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK(length(request_digest)=64 AND request_digest NOT GLOB '*[^0-9a-f]*'),
    result_json TEXT NOT NULL CHECK(json_valid(result_json) AND length(CAST(result_json AS BLOB)) <= 2097152),
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, command_id)
);

CREATE INDEX idx_ap_payment_links_invoice
ON ap_payment_links(supplier_invoice_id, payment_date, id);

CREATE INDEX idx_ap_payment_links_effect
ON ap_payment_links(finance_effect_id);

CREATE TRIGGER ap_payment_link_immutable_update BEFORE UPDATE ON ap_payment_links
BEGIN SELECT RAISE(ABORT, 'supplier payment links are immutable'); END;

CREATE TRIGGER ap_payment_link_immutable_delete BEFORE DELETE ON ap_payment_links
BEGIN SELECT RAISE(ABORT, 'supplier payment links cannot be deleted'); END;

CREATE TRIGGER ap_payment_link_command_immutable_update BEFORE UPDATE ON ap_payment_link_commands
BEGIN SELECT RAISE(ABORT, 'supplier payment commands are immutable'); END;

CREATE TRIGGER ap_payment_link_command_immutable_delete BEFORE DELETE ON ap_payment_link_commands
BEGIN SELECT RAISE(ABORT, 'supplier payment commands cannot be deleted'); END;

CREATE TRIGGER ap_payment_link_source_guard BEFORE INSERT ON ap_payment_links
WHEN NEW.amount_minor <= 0
 OR NOT EXISTS(
    SELECT 1
    FROM ap_supplier_invoices invoice
    JOIN finance_posting_effects effect ON effect.id=NEW.finance_effect_id
    JOIN ledger_entries entry ON entry.id=effect.entry_id
    WHERE invoice.id=NEW.supplier_invoice_id
      AND invoice.status='Approved'
      AND invoice.workspace_id=NEW.workspace_id
      AND invoice.organization_id=NEW.organization_id
      AND invoice.legal_entity_id=NEW.legal_entity_id
      AND invoice.row_version=NEW.invoice_version_before
      AND effect.entry_id=NEW.finance_entry_id
      AND effect.source_kind='Manual'
      AND effect.source_id=effect.entry_id
      AND effect.reverses_effect_id IS NULL
      AND effect.workspace_id=NEW.workspace_id
      AND effect.organization_id=NEW.organization_id
      AND effect.legal_entity_id=NEW.legal_entity_id
      AND effect.currency_code=invoice.currency_code
      AND effect.currency_code=NEW.currency_code
      AND effect.validation_digest=NEW.finance_validation_digest
      AND effect.posted_actor_id=NEW.finance_posted_actor_id
      AND NEW.settlement_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.created_by),invoice.created_by)
      AND NEW.settlement_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.approved_by),invoice.approved_by)
      AND NEW.finance_posted_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.created_by),invoice.created_by)
      AND NEW.finance_posted_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.approved_by),invoice.approved_by)
      AND NEW.payment_date=json_extract(effect.snapshot_json,'$.entry.posting_date')
      AND json_extract(effect.snapshot_json,'$.entry.id')=effect.entry_id
      AND json_extract(effect.snapshot_json,'$.entry.external_reference')='AP-PAYMENT:' || invoice.id
      AND json_extract(effect.snapshot_json,'$.entry.currency_code')=invoice.currency_code
      AND entry.validator_actor_id IS NOT NULL
      AND json_extract(effect.snapshot_json,'$.entry.preparer_actor_id')<>entry.validator_actor_id
      AND json_extract(effect.snapshot_json,'$.entry.preparer_actor_id')<>effect.posted_actor_id
      AND entry.validator_actor_id<>effect.posted_actor_id
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines'))=2
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines') AS line
           WHERE json_extract(line.value,'$.account_id')=NEW.ap_account_id
             AND json_extract(line.value,'$.debit_minor')=NEW.amount_minor
             AND json_extract(line.value,'$.credit_minor')=0)=1
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines') AS line
           WHERE json_extract(line.value,'$.account_id')=NEW.cash_account_id
             AND json_extract(line.value,'$.debit_minor')=0
             AND json_extract(line.value,'$.credit_minor')=NEW.amount_minor)=1
      AND NEW.amount_minor + COALESCE((SELECT SUM(amount_minor) FROM ap_payment_links
                                       WHERE supplier_invoice_id=invoice.id),0) <= invoice.total_minor
      AND EXISTS(SELECT 1 FROM audit_events audit
                 WHERE audit.id=NEW.audit_event_id AND audit.object_type='ap_payment_link'
                   AND audit.object_id=NEW.id AND audit.action='ap_payment_linked'
                   AND (audit.actor_user_id=NEW.settlement_actor_id OR audit.actor_label=NEW.settlement_actor_id)
                   AND json_extract(audit.metadata_json,'$.supplier_invoice_id')=invoice.id
                   AND json_extract(audit.metadata_json,'$.finance_effect_id')=effect.id
                   AND json_extract(audit.metadata_json,'$.finance_entry_id')=effect.entry_id
                   AND json_extract(audit.metadata_json,'$.amount_minor')=NEW.amount_minor
                   AND json_extract(audit.metadata_json,'$.currency_code')=NEW.currency_code
                   AND json_extract(audit.metadata_json,'$.invoice_version_before')=NEW.invoice_version_before)
      AND EXISTS(SELECT 1 FROM outbox_events outbox
                 WHERE outbox.id=NEW.outbox_event_id AND outbox.event_type='ap.payment_linked'
                   AND outbox.aggregate_type='ap_payment_link' AND outbox.aggregate_id=NEW.id
                   AND json_extract(outbox.payload_json,'$.payment_link_id')=NEW.id
                   AND json_extract(outbox.payload_json,'$.supplier_invoice_id')=invoice.id
                   AND json_extract(outbox.payload_json,'$.finance_effect_id')=effect.id)
 )
BEGIN SELECT RAISE(ABORT, 'supplier payment link requires an exact approved AP/cash financial effect and evidence'); END;

CREATE TRIGGER ap_payment_link_command_guard BEFORE INSERT ON ap_payment_link_commands
WHEN NOT EXISTS(
    SELECT 1 FROM ap_payment_links link
    JOIN ap_supplier_invoices invoice ON invoice.id=link.supplier_invoice_id
    WHERE link.workspace_id=NEW.workspace_id
      AND link.settlement_actor_id=NEW.settlement_actor_id
      AND json_extract(NEW.result_json,'$.payment_link_id')=link.id
      AND json_extract(NEW.result_json,'$.supplier_invoice_id')=link.supplier_invoice_id
      AND json_extract(NEW.result_json,'$.finance_effect_id')=link.finance_effect_id
      AND json_extract(NEW.result_json,'$.finance_entry_id')=link.finance_entry_id
      AND json_extract(NEW.result_json,'$.ap_account_id')=link.ap_account_id
      AND json_extract(NEW.result_json,'$.cash_account_id')=link.cash_account_id
      AND json_extract(NEW.result_json,'$.amount_minor')=link.amount_minor
      AND json_extract(NEW.result_json,'$.currency_code')=link.currency_code
      AND json_extract(NEW.result_json,'$.payment_date')=link.payment_date
      AND json_extract(NEW.result_json,'$.finance_validation_digest')=link.finance_validation_digest
      AND json_extract(NEW.result_json,'$.finance_posted_actor_id')=link.finance_posted_actor_id
      AND json_extract(NEW.result_json,'$.settlement_actor_id')=link.settlement_actor_id
      AND json_extract(NEW.result_json,'$.invoice_version_before')=link.invoice_version_before
      AND json_extract(NEW.result_json,'$.invoice_version_after')=link.invoice_version_before+1
      AND json_extract(NEW.result_json,'$.audit_event_id')=link.audit_event_id
      AND json_extract(NEW.result_json,'$.outbox_event_id')=link.outbox_event_id
      AND json_extract(NEW.result_json,'$.allocated_minor')=(
          SELECT COALESCE(SUM(history.amount_minor),0) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before)
      AND json_extract(NEW.result_json,'$.outstanding_minor')=invoice.total_minor-(
          SELECT COALESCE(SUM(history.amount_minor),0) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before)
      AND json_extract(NEW.result_json,'$.invoice_status')=CASE WHEN (
          SELECT COALESCE(SUM(history.amount_minor),0) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before)=invoice.total_minor
          THEN 'Paid' ELSE 'Approved' END
)
BEGIN SELECT RAISE(ABORT, 'supplier payment command requires its immutable exact settlement link'); END;

CREATE TRIGGER ap_supplier_invoice_payment_transition_guard
BEFORE UPDATE ON ap_supplier_invoices
WHEN OLD.status='Paid'
 OR (
    OLD.status='Approved'
    AND (
        NEW.row_version<>OLD.row_version+1
        OR NOT EXISTS(
            SELECT 1 FROM ap_payment_links link
             WHERE link.supplier_invoice_id=OLD.id
               AND link.invoice_version_before=OLD.row_version
        )
        OR NEW.status<>CASE WHEN
            COALESCE((SELECT SUM(amount_minor) FROM ap_payment_links
                       WHERE supplier_invoice_id=OLD.id),0)=OLD.total_minor
            THEN 'Paid' ELSE 'Approved' END
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'supplier invoice Paid status requires immutable exact payment links');
END;

CREATE TRIGGER ap_payment_link_invoice_transition AFTER INSERT ON ap_payment_links
BEGIN
    UPDATE ap_supplier_invoices
       SET status=CASE WHEN COALESCE((
               SELECT SUM(amount_minor) FROM ap_payment_links
                WHERE supplier_invoice_id=NEW.supplier_invoice_id
           ),0)=total_minor THEN 'Paid' ELSE 'Approved' END,
           updated_at=NEW.created_at,
           row_version=row_version+1
     WHERE id=NEW.supplier_invoice_id
       AND status='Approved'
       AND row_version=NEW.invoice_version_before;
    SELECT CASE WHEN changes()<>1
        THEN RAISE(ABORT, 'supplier payment link must atomically advance its invoice state')
    END;
END;

INSERT OR IGNORE INTO permissions(name,description) VALUES
    ('payables.settle', 'Link an approved supplier invoice to an exact independently posted AP/cash financial effect.');

INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
SELECT roles.id,permissions.name
FROM roles JOIN permissions
WHERE roles.name IN ('admin','controller') AND permissions.name='payables.settle';
"""


__all__ = ["SQLITE_PAYABLES_PAYMENT_LINK_SQL"]
