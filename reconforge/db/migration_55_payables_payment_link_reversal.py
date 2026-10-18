"""SQLite migration for immutable Finance-backed AP payment-link reversals."""


SQLITE_PAYABLES_PAYMENT_LINK_REVERSAL_SQL = """
CREATE TABLE ap_payment_link_reversals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    supplier_invoice_id TEXT NOT NULL REFERENCES ap_supplier_invoices(id) ON DELETE RESTRICT,
    payment_link_id TEXT NOT NULL UNIQUE REFERENCES ap_payment_links(id) ON DELETE RESTRICT,
    reversal_finance_effect_id TEXT NOT NULL UNIQUE REFERENCES finance_posting_effects(id) ON DELETE RESTRICT,
    reversal_finance_entry_id TEXT NOT NULL UNIQUE REFERENCES ledger_entries(id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
    currency_code TEXT NOT NULL,
    reversal_date TEXT NOT NULL,
    finance_validation_digest TEXT NOT NULL
        CHECK(length(finance_validation_digest)=64 AND finance_validation_digest NOT GLOB '*[^0-9a-f]*'),
    finance_posted_actor_id TEXT NOT NULL,
    reversal_actor_id TEXT NOT NULL,
    invoice_version_before INTEGER NOT NULL CHECK(invoice_version_before > 0),
    audit_event_id TEXT NOT NULL REFERENCES audit_events(id) ON DELETE RESTRICT,
    outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(supplier_invoice_id, invoice_version_before)
);

CREATE TABLE ap_payment_link_reversal_commands (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
    reversal_actor_id TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK(length(request_digest)=64 AND request_digest NOT GLOB '*[^0-9a-f]*'),
    result_json TEXT NOT NULL CHECK(json_valid(result_json) AND length(CAST(result_json AS BLOB)) <= 2097152),
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, command_id)
);

CREATE INDEX idx_ap_payment_link_reversals_invoice
ON ap_payment_link_reversals(supplier_invoice_id, invoice_version_before, id);

CREATE INDEX idx_ap_payment_link_reversal_commands_scope
ON ap_payment_link_reversal_commands(workspace_id, created_at, command_id);

CREATE TRIGGER ap_payment_link_reversal_immutable_update BEFORE UPDATE ON ap_payment_link_reversals
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversals are immutable'); END;

CREATE TRIGGER ap_payment_link_reversal_immutable_delete BEFORE DELETE ON ap_payment_link_reversals
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversals cannot be deleted'); END;

CREATE TRIGGER ap_payment_link_reversal_command_immutable_update BEFORE UPDATE ON ap_payment_link_reversal_commands
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversal commands are immutable'); END;

CREATE TRIGGER ap_payment_link_reversal_command_immutable_delete BEFORE DELETE ON ap_payment_link_reversal_commands
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversal commands cannot be deleted'); END;

DROP TRIGGER ap_payment_link_source_guard;

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
      AND NEW.amount_minor + COALESCE((
          SELECT SUM(prior.amount_minor)
          FROM ap_payment_links prior
          WHERE prior.supplier_invoice_id=invoice.id
            AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals reversed
                           WHERE reversed.payment_link_id=prior.id)
      ),0) <= invoice.total_minor
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

CREATE TRIGGER ap_payment_link_reversal_source_guard BEFORE INSERT ON ap_payment_link_reversals
WHEN NEW.amount_minor <= 0
 OR NOT EXISTS(
    SELECT 1
    FROM ap_supplier_invoices invoice
    JOIN ap_payment_links link ON link.id=NEW.payment_link_id
    JOIN finance_posting_effects effect ON effect.id=NEW.reversal_finance_effect_id
    JOIN ledger_entries entry ON entry.id=effect.entry_id
    WHERE invoice.id=NEW.supplier_invoice_id
      AND invoice.status IN ('Approved','Paid')
      AND invoice.row_version=NEW.invoice_version_before
      AND (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
      AND (link.workspace_id,link.organization_id,link.legal_entity_id,link.supplier_invoice_id,
           link.amount_minor,link.currency_code)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,invoice.id,
           NEW.amount_minor,NEW.currency_code)
      AND effect.entry_id=NEW.reversal_finance_entry_id
      AND effect.source_kind='Reversal'
      AND effect.source_id=link.finance_effect_id
      AND effect.reverses_effect_id=link.finance_effect_id
      AND (effect.workspace_id,effect.organization_id,effect.legal_entity_id,effect.currency_code,
           effect.validation_digest,effect.posted_actor_id)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.currency_code,
           NEW.finance_validation_digest,NEW.finance_posted_actor_id)
      AND NEW.reversal_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.created_by),invoice.created_by)
      AND NEW.reversal_actor_id<>COALESCE((SELECT id FROM users WHERE username=invoice.approved_by),invoice.approved_by)
      AND NEW.reversal_actor_id<>link.settlement_actor_id
      AND NEW.reversal_actor_id<>effect.posted_actor_id
      AND entry.validator_actor_id IS NOT NULL
      AND json_extract(effect.snapshot_json,'$.entry.preparer_actor_id') IS NOT NULL
      AND json_extract(effect.snapshot_json,'$.entry.preparer_actor_id')<>entry.validator_actor_id
      AND json_extract(effect.snapshot_json,'$.entry.preparer_actor_id')<>effect.posted_actor_id
      AND entry.validator_actor_id<>effect.posted_actor_id
      AND NEW.reversal_actor_id<>entry.validator_actor_id
      AND NEW.reversal_actor_id<>json_extract(effect.snapshot_json,'$.entry.preparer_actor_id')
      AND json_extract(effect.snapshot_json,'$.entry.id')=effect.entry_id
      AND json_extract(effect.snapshot_json,'$.entry.reverses_posting_id')=link.finance_effect_id
      AND json_extract(effect.snapshot_json,'$.entry.external_reference')=link.finance_effect_id
      AND json_extract(effect.snapshot_json,'$.entry.currency_code')=link.currency_code
      AND NEW.reversal_date=json_extract(effect.snapshot_json,'$.entry.posting_date')
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines'))=2
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines') AS line
           WHERE json_extract(line.value,'$.account_id')=link.cash_account_id
             AND json_extract(line.value,'$.debit_minor')=link.amount_minor
             AND json_extract(line.value,'$.credit_minor')=0)=1
      AND (SELECT count(*) FROM json_each(effect.snapshot_json,'$.lines') AS line
           WHERE json_extract(line.value,'$.account_id')=link.ap_account_id
             AND json_extract(line.value,'$.debit_minor')=0
             AND json_extract(line.value,'$.credit_minor')=link.amount_minor)=1
      AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals existing
                     WHERE existing.payment_link_id=link.id
                        OR existing.reversal_finance_effect_id=effect.id)
      AND EXISTS(SELECT 1 FROM audit_events audit
                 WHERE audit.id=NEW.audit_event_id AND audit.object_type='ap_payment_link_reversal'
                   AND audit.object_id=NEW.id AND audit.action='ap_payment_link_reversed'
                   AND (audit.actor_user_id=NEW.reversal_actor_id OR audit.actor_label=NEW.reversal_actor_id)
                   AND json_extract(audit.metadata_json,'$.payment_link_id')=link.id
                   AND json_extract(audit.metadata_json,'$.supplier_invoice_id')=invoice.id
                   AND json_extract(audit.metadata_json,'$.original_finance_effect_id')=link.finance_effect_id
                   AND json_extract(audit.metadata_json,'$.reversal_finance_effect_id')=effect.id
                   AND json_extract(audit.metadata_json,'$.amount_minor')=link.amount_minor
                   AND json_extract(audit.metadata_json,'$.currency_code')=link.currency_code
                   AND json_extract(audit.metadata_json,'$.invoice_version_before')=NEW.invoice_version_before)
      AND EXISTS(SELECT 1 FROM outbox_events outbox
                 WHERE outbox.id=NEW.outbox_event_id AND outbox.event_type='ap.payment_link_reversed'
                   AND outbox.aggregate_type='ap_payment_link_reversal' AND outbox.aggregate_id=NEW.id
                   AND json_extract(outbox.payload_json,'$.payment_link_reversal_id')=NEW.id
                   AND json_extract(outbox.payload_json,'$.payment_link_id')=link.id
                   AND json_extract(outbox.payload_json,'$.reversal_finance_effect_id')=effect.id)
 )
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversal requires an exact independently posted Finance inverse and evidence'); END;

DROP TRIGGER ap_payment_link_command_guard;

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
      AND json_extract(NEW.result_json,'$.allocated_minor')=COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=link.invoice_version_before)
      ),0)
      AND json_extract(NEW.result_json,'$.outstanding_minor')=invoice.total_minor-COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=link.invoice_version_before)
      ),0)
      AND json_extract(NEW.result_json,'$.invoice_status')=CASE WHEN COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=link.supplier_invoice_id
             AND history.invoice_version_before<=link.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=link.invoice_version_before)
      ),0)=invoice.total_minor THEN 'Paid' ELSE 'Approved' END
)
BEGIN SELECT RAISE(ABORT, 'supplier payment command requires its immutable exact settlement link'); END;

DROP TRIGGER ap_supplier_invoice_payment_transition_guard;

CREATE TRIGGER ap_supplier_invoice_payment_transition_guard
BEFORE UPDATE ON ap_supplier_invoices
WHEN OLD.status IN ('Approved','Paid')
 AND (
    NEW.row_version<>OLD.row_version+1
    OR (
        NOT EXISTS(SELECT 1 FROM ap_payment_links link
                   WHERE link.supplier_invoice_id=OLD.id AND link.invoice_version_before=OLD.row_version)
        AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals reversal
                       WHERE reversal.supplier_invoice_id=OLD.id AND reversal.invoice_version_before=OLD.row_version)
    )
    OR NEW.status<>CASE WHEN COALESCE((
        SELECT SUM(link.amount_minor) FROM ap_payment_links link
         WHERE link.supplier_invoice_id=OLD.id
           AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals reversal
                          WHERE reversal.payment_link_id=link.id)
    ),0)=OLD.total_minor THEN 'Paid' ELSE 'Approved' END
 )
BEGIN
    SELECT RAISE(ABORT, 'supplier invoice Paid status requires immutable exact payment-link evidence');
END;

DROP TRIGGER ap_payment_link_invoice_transition;

CREATE TRIGGER ap_payment_link_invoice_transition AFTER INSERT ON ap_payment_links
BEGIN
    UPDATE ap_supplier_invoices
       SET status=CASE WHEN COALESCE((
               SELECT SUM(link.amount_minor) FROM ap_payment_links link
                WHERE link.supplier_invoice_id=NEW.supplier_invoice_id
                  AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals reversal
                                 WHERE reversal.payment_link_id=link.id)
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

CREATE TRIGGER ap_payment_link_reversal_invoice_transition AFTER INSERT ON ap_payment_link_reversals
BEGIN
    UPDATE ap_supplier_invoices
       SET status=CASE WHEN COALESCE((
               SELECT SUM(link.amount_minor) FROM ap_payment_links link
                WHERE link.supplier_invoice_id=NEW.supplier_invoice_id
                  AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals reversal
                                 WHERE reversal.payment_link_id=link.id)
           ),0)=total_minor THEN 'Paid' ELSE 'Approved' END,
           updated_at=NEW.created_at,
           row_version=row_version+1
     WHERE id=NEW.supplier_invoice_id
       AND status IN ('Approved','Paid')
       AND row_version=NEW.invoice_version_before;
    SELECT CASE WHEN changes()<>1
        THEN RAISE(ABORT, 'supplier payment-link reversal must atomically advance its invoice state')
    END;
END;

CREATE TRIGGER ap_payment_link_reversal_command_guard BEFORE INSERT ON ap_payment_link_reversal_commands
WHEN NOT EXISTS(
    SELECT 1
    FROM ap_payment_link_reversals reversal
    JOIN ap_payment_links link ON link.id=reversal.payment_link_id
    JOIN ap_supplier_invoices invoice ON invoice.id=reversal.supplier_invoice_id
    WHERE reversal.workspace_id=NEW.workspace_id
      AND reversal.reversal_actor_id=NEW.reversal_actor_id
      AND json_extract(NEW.result_json,'$.payment_link_reversal_id')=reversal.id
      AND json_extract(NEW.result_json,'$.payment_link_id')=link.id
      AND json_extract(NEW.result_json,'$.supplier_invoice_id')=reversal.supplier_invoice_id
      AND json_extract(NEW.result_json,'$.original_finance_effect_id')=link.finance_effect_id
      AND json_extract(NEW.result_json,'$.original_finance_entry_id')=link.finance_entry_id
      AND json_extract(NEW.result_json,'$.reversal_finance_effect_id')=reversal.reversal_finance_effect_id
      AND json_extract(NEW.result_json,'$.reversal_finance_entry_id')=reversal.reversal_finance_entry_id
      AND json_extract(NEW.result_json,'$.amount_minor')=reversal.amount_minor
      AND json_extract(NEW.result_json,'$.currency_code')=reversal.currency_code
      AND json_extract(NEW.result_json,'$.reversal_date')=reversal.reversal_date
      AND json_extract(NEW.result_json,'$.finance_validation_digest')=reversal.finance_validation_digest
      AND json_extract(NEW.result_json,'$.finance_posted_actor_id')=reversal.finance_posted_actor_id
      AND json_extract(NEW.result_json,'$.reversal_actor_id')=reversal.reversal_actor_id
      AND json_extract(NEW.result_json,'$.invoice_version_before')=reversal.invoice_version_before
      AND json_extract(NEW.result_json,'$.invoice_version_after')=reversal.invoice_version_before+1
      AND json_extract(NEW.result_json,'$.audit_event_id')=reversal.audit_event_id
      AND json_extract(NEW.result_json,'$.outbox_event_id')=reversal.outbox_event_id
      AND json_extract(NEW.result_json,'$.allocated_minor')=COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=reversal.supplier_invoice_id
             AND history.invoice_version_before<=reversal.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=reversal.invoice_version_before)
      ),0)
      AND json_extract(NEW.result_json,'$.outstanding_minor')=invoice.total_minor-COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=reversal.supplier_invoice_id
             AND history.invoice_version_before<=reversal.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=reversal.invoice_version_before)
      ),0)
      AND json_extract(NEW.result_json,'$.invoice_status')=CASE WHEN COALESCE((
          SELECT SUM(history.amount_minor) FROM ap_payment_links history
           WHERE history.supplier_invoice_id=reversal.supplier_invoice_id
             AND history.invoice_version_before<=reversal.invoice_version_before
             AND NOT EXISTS(SELECT 1 FROM ap_payment_link_reversals historical_reversal
                            WHERE historical_reversal.payment_link_id=history.id
                              AND historical_reversal.invoice_version_before<=reversal.invoice_version_before)
      ),0)=invoice.total_minor THEN 'Paid' ELSE 'Approved' END
)
BEGIN SELECT RAISE(ABORT, 'supplier payment-link reversal command requires its immutable exact evidence'); END;

INSERT OR IGNORE INTO permissions(name,description) VALUES
    ('payables.reverse', 'Reverse retained supplier payment-link evidence only with an independently posted exact Finance inverse.');

INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
SELECT roles.id,permissions.name
FROM roles JOIN permissions
WHERE roles.name IN ('admin','controller') AND permissions.name='payables.reverse';
"""


__all__ = ["SQLITE_PAYABLES_PAYMENT_LINK_REVERSAL_SQL"]
