import type { AdminAccessPermission, AdminAccessRole, AdminAccessRoleChange, AdminAuditEvent, AdminAuditPage, AdminAuditVerification, AdminIdentitySession, AdminIdentityUser, AdminIdentityUserStatusChange, AdminIntegration, AdminRetentionPolicy, AdminSecuritySnapshot, AdminSessionRevocation, AdminUserRoleAssignment, BankStatementStatus, BankStatementStudioContract, BrowserAdminSession, EvidenceBinderContract, ExceptionQueueContract, IndividualCashflowStatus, IndividualCashflowStudioContract, InventoryControlContract, LiveStudioContract, LiveStudioMetric, ManufacturingCostStatus, ManufacturingCostStudioContract, ProfessionalInvoicePaymentStatus, ProfessionalInvoicePaymentStudioContract, RetailSettlementStudioContract, StudioOverview } from "./types";

const OVERVIEW_URL = `${import.meta.env.BASE_URL}demo/studio-overview.json`;
const EXCEPTIONS_URL = `${import.meta.env.BASE_URL}demo/studio-exceptions.json`;
const EVIDENCE_URL = `${import.meta.env.BASE_URL}demo/studio-evidence.json`;
const INVENTORY_URL = `${import.meta.env.BASE_URL}demo/studio-inventory.json`;
const RETAIL_SETTLEMENT_URL = `${import.meta.env.BASE_URL}demo/studio-retail-settlement.json`;
const BANK_STATEMENT_URL = `${import.meta.env.BASE_URL}demo/studio-bank-statement.json`;
const MANUFACTURING_COST_URL = `${import.meta.env.BASE_URL}demo/studio-manufacturing-cost.json`;
const PROFESSIONAL_INVOICE_PAYMENT_URL = `${import.meta.env.BASE_URL}demo/studio-professional-invoice-payment.json`;
const INDIVIDUAL_CASHFLOW_URL = `${import.meta.env.BASE_URL}demo/studio-individual-cashflow.json`;
const metricFormats = new Set(["percent", "count", "days"]);
const metricTones = new Set(["positive", "critical", "warning", "neutral"]);
const riskRatings = new Set(["critical", "high", "medium", "low"]);
const inventoryMovementTypes = new Set(["Receipt", "Delivery", "Transfer", "Adjustment"]);
const inventoryStatuses = new Set(["Draft", "Posted", "Voided"]);
const inventoryTrackingTypes = new Set(["None", "Lot", "Serial"]);
const inventoryCountStatuses = new Set(["Draft", "Counting", "Submitted", "Approved", "Cancelled"]);
const inventoryValuationStatuses = new Set(["Draft", "Approved", "Cancelled"]);
const financeEntryStatuses = new Set(["", "Draft", "Validated", "Voided"]);
const showcaseStatuses = new Set(["strong", "watch", "attention"]);
const controlDomains = new Set(["close", "evidence", "matching", "controls"]);
const exactQuantity = /^-?(?:0|[1-9]\d*)(?:\.\d{1,6})?$/;
const exactMoney = /^-?(?:0|[1-9]\d*)(?:\.\d{1,6})?$/;
const currencyCode = /^[A-Z]{3}$/;
const digest = /^[a-f0-9]{64}$/;
const retailStatuses = new Set(["matched", "exception", "unmatched_pos", "unmatched_settlement", "ambiguous"]);
const bankStatuses = new Set<BankStatementStatus>(["matched", "exception", "unmatched_bank", "unmatched_ledger", "ambiguous"]);
const manufacturingStatuses = new Set<ManufacturingCostStatus>(["reconciled", "exception", "unmatched"]);
const professionalStatuses = new Set<ProfessionalInvoicePaymentStatus>(["matched", "exception", "unmatched_invoice", "unmatched_payment", "ambiguous"]);
const individualCashflowStatuses = new Set<IndividualCashflowStatus>(["within_budget", "over_budget", "unbudgeted", "no_activity"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.length <= 2_000;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
}

function isContractSource(value: unknown): boolean {
  return (
    isObject(value) &&
    value.kind === "reconforge-enterprise-demo" &&
    value.local_first === true &&
    value.external_calls === false
  );
}

function hasContractEnvelope(value: Record<string, unknown>): boolean {
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_ENTERPRISE_DEMO_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText)
  );
}

function isMetric(value: unknown): boolean {
  return (
    isObject(value) &&
    isText(value.key) &&
    isText(value.label) &&
    typeof value.value === "number" &&
    Number.isFinite(value.value) &&
    typeof value.format === "string" &&
    metricFormats.has(value.format) &&
    typeof value.tone === "string" &&
    metricTones.has(value.tone) &&
    isText(value.lineage)
  );
}

function isDistributionPoint(value: unknown): boolean {
  if (!isObject(value) || !isCount(value.count)) return false;
  if ("risk" in value) return typeof value.risk === "string" && riskRatings.has(value.risk);
  return "status" in value && isText(value.status);
}

function hasTextFields(value: unknown, fields: readonly string[]): boolean {
  return isObject(value) && fields.every((field) => isText(value[field]));
}

function isException(value: unknown): boolean {
  return (
    hasTextFields(value, ["source_type", "period_name", "entity_code", "account_code", "control_code", "risk_rating", "owner", "status", "description"]) &&
    isObject(value) &&
    riskRatings.has(value.risk_rating as string)
  );
}

function isExceptionRecord(value: unknown): boolean {
  return (
    isException(value) &&
    isObject(value) &&
    typeof value.exception_id === "string" &&
    /^SYN-EXC-[0-9A-F]{12}$/.test(value.exception_id)
  );
}

function hasCountFields(value: unknown, fields: readonly string[]): boolean {
  return isObject(value) && fields.every((field) => isCount(value[field]));
}

function isExceptionQueue(value: unknown): value is ExceptionQueueContract {
  if (!isObject(value)) return false;
  return (
    hasContractEnvelope(value) &&
    hasCountFields(value.summary, ["total", "open", "high_risk", "unassigned", "entity_count"]) &&
    Array.isArray(value.risk_distribution) && value.risk_distribution.every(isDistributionPoint) &&
    Array.isArray(value.status_distribution) && value.status_distribution.every(isDistributionPoint) &&
    Array.isArray(value.exceptions) && value.exceptions.every(isExceptionRecord)
  );
}

function isEvidenceRecord(value: unknown): boolean {
  return (
    hasTextFields(value, ["evidence_code", "provenance_type", "redaction_status", "evidence_status", "checksum_sha256"]) &&
    isObject(value) &&
    /^[0-9a-f]{64}$/.test(value.checksum_sha256 as string)
  );
}

function isEvidenceBinder(value: unknown): value is EvidenceBinderContract {
  if (!isObject(value) || !isObject(value.summary)) return false;
  return (
    hasContractEnvelope(value) &&
    hasCountFields(value.summary, ["total", "available", "checksum_count", "synthetic_redaction_count"]) &&
    typeof value.summary.coverage_percent === "number" &&
    Number.isFinite(value.summary.coverage_percent) &&
    value.summary.coverage_percent >= 0 &&
    value.summary.coverage_percent <= 100 &&
    Array.isArray(value.status_distribution) && value.status_distribution.every(isDistributionPoint) &&
    Array.isArray(value.evidence) && value.evidence.every(isEvidenceRecord)
  );
}

function isInventoryWarehouse(value: unknown): boolean {
  return (
    hasTextFields(value, ["warehouse_code", "warehouse_name", "entity_code"]) &&
    isObject(value) &&
    isCount(value.on_hand_lines) &&
    isCount(value.negative_lines)
  );
}

function isInventoryOnHand(value: unknown): boolean {
  return (
    hasTextFields(value, ["item_code", "item_name", "uom_code", "warehouse_code", "warehouse_name", "location_code", "entity_code", "lot_serial_code", "tracking_type", "quantity"]) &&
    isObject(value) &&
    inventoryTrackingTypes.has(value.tracking_type as string) &&
    exactQuantity.test(value.quantity as string)
  );
}

function isInventoryMovement(value: unknown): boolean {
  return (
    hasTextFields(value, ["movement_number", "movement_type", "status", "movement_date", "entity_code", "from_location", "to_location", "quantity"]) &&
    isObject(value) &&
    inventoryMovementTypes.has(value.movement_type as string) &&
    inventoryStatuses.has(value.status as string) &&
    isCount(value.line_count) &&
    value.line_count >= 1 &&
    value.line_count <= 1_000 &&
    exactQuantity.test(value.quantity as string) &&
    !String(value.quantity).startsWith("-") &&
    !/^0(?:\.0+)?$/.test(value.quantity as string)
  );
}

function isInventoryException(value: unknown): boolean {
  return (
    hasTextFields(value, ["exception_id", "control_code", "risk_rating", "item_code", "location", "quantity", "description"]) &&
    isObject(value) &&
    /^SYN-INV-EXC-[0-9A-F]{12}$/.test(value.exception_id as string) &&
    riskRatings.has(value.risk_rating as string) &&
    (value.quantity === "" || exactQuantity.test(value.quantity as string))
  );
}

function isInventoryCount(value: unknown): boolean {
  if (
    !hasTextFields(value, ["count_number", "status", "count_date", "entity_code", "warehouse_code", "location_code", "adjustment_movement_number"]) ||
    !isObject(value) ||
    !inventoryCountStatuses.has(value.status as string) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value.count_date as string) ||
    !isCount(value.line_count) || value.line_count < 1 || value.line_count > 100_000 ||
    !isCount(value.counted_line_count) || value.counted_line_count > value.line_count ||
    !isCount(value.variance_line_count) || value.variance_line_count > value.counted_line_count
  ) return false;
  return !(["Submitted", "Approved"].includes(value.status as string)) || value.counted_line_count === value.line_count;
}

function isInventoryReorderSignal(value: unknown): boolean {
  if (
    !hasTextFields(value, ["signal_id", "risk_rating", "item_code", "item_name", "uom_code", "warehouse_code", "location_code", "on_hand_quantity", "minimum_quantity", "target_quantity", "suggested_quantity"]) ||
    !isObject(value)
  ) return false;
  return (
    /^SYN-INV-REORDER-[0-9A-F]{12}$/.test(value.signal_id as string) &&
    ["high", "medium"].includes(value.risk_rating as string) &&
    exactQuantity.test(value.on_hand_quantity as string) &&
    exactQuantity.test(value.minimum_quantity as string) &&
    exactQuantity.test(value.target_quantity as string) &&
    exactQuantity.test(value.suggested_quantity as string) &&
    !String(value.minimum_quantity).startsWith("-") &&
    !String(value.target_quantity).startsWith("-") &&
    !String(value.suggested_quantity).startsWith("-") &&
    !/^0(?:\.0+)?$/.test(value.suggested_quantity as string) &&
    isCount(value.lead_time_days) && value.lead_time_days <= 3_650
  );
}

function isInventoryValuation(value: unknown): boolean {
  if (
    !hasTextFields(value, ["valuation_number", "movement_number", "movement_type", "status", "valuation_date", "entity_code", "costing_method", "currency_code", "total_value", "finance_entry_number", "finance_entry_status"]) ||
    !isObject(value)
  ) return false;
  return (
    ["Receipt", "Delivery", "Adjustment"].includes(value.movement_type as string) &&
    inventoryValuationStatuses.has(value.status as string) &&
    /^\d{4}-\d{2}-\d{2}$/.test(value.valuation_date as string) &&
    value.costing_method === "FIFO" &&
    exactQuantity.test(value.total_value as string) &&
    !String(value.total_value).startsWith("-") &&
    !/^0(?:\.0+)?$/.test(value.total_value as string) &&
    financeEntryStatuses.has(value.finance_entry_status as string) &&
    (value.status !== "Approved" || (Boolean(value.finance_entry_number) && Boolean(value.finance_entry_status)))
  );
}

function isInventoryValuationReversal(value: unknown): boolean {
  if (
    !hasTextFields(value, ["reversal_number", "original_valuation_number", "reversal_movement_number", "original_movement_type", "reversal_movement_type", "status", "reversal_date", "entity_code", "currency_code", "layer_effect", "total_value", "finance_entry_number", "finance_entry_status"]) ||
    !isObject(value)
  ) return false;
  const inverseTypes: Record<string, string> = {
    Receipt: "Delivery",
    Delivery: "Receipt",
    Adjustment: "Adjustment",
  };
  return (
    inverseTypes[value.original_movement_type as string] === value.reversal_movement_type &&
    inventoryValuationStatuses.has(value.status as string) &&
    /^\d{4}-\d{2}-\d{2}$/.test(value.reversal_date as string) &&
    ["Restore", "Remove"].includes(value.layer_effect as string) &&
    Number.isInteger(value.layer_effect_count) &&
    (value.layer_effect_count as number) >= 1 &&
    (value.layer_effect_count as number) <= 100_000 &&
    exactQuantity.test(value.total_value as string) &&
    !String(value.total_value).startsWith("-") &&
    !/^0(?:\.0+)?$/.test(value.total_value as string) &&
    financeEntryStatuses.has(value.finance_entry_status as string) &&
    (value.status !== "Approved" || Boolean(value.finance_entry_number && value.finance_entry_status))
  );
}

function isInventoryCostLayer(value: unknown): boolean {
  if (
    !hasTextFields(value, ["layer_id", "valuation_number", "item_code", "item_name", "uom_code", "lot_serial_code", "entity_code", "currency_code", "original_quantity", "remaining_quantity", "original_value", "remaining_value", "layer_status"]) ||
    !isObject(value)
  ) return false;
  const exactFields = ["original_quantity", "remaining_quantity", "original_value", "remaining_value"];
  if (!exactFields.every((field) => exactQuantity.test(value[field] as string) && !String(value[field]).startsWith("-"))) return false;
  const originalQuantity = Number(value.original_quantity);
  const remainingQuantity = Number(value.remaining_quantity);
  const originalValue = Number(value.original_value);
  const remainingValue = Number(value.remaining_value);
  return (
    originalQuantity > 0 && remainingQuantity >= 0 && remainingQuantity <= originalQuantity &&
    originalValue > 0 && remainingValue >= 0 && remainingValue <= originalValue &&
    (remainingQuantity === 0) === (remainingValue === 0) &&
    value.layer_status === (remainingQuantity > 0 ? "Open" : "Closed")
  );
}

function inventoryValuationReversalsAreConsistent(value: Record<string, unknown>): boolean {
  const valuations = value.valuations as Array<Record<string, unknown>>;
  const reversals = value.valuation_reversals as Array<Record<string, unknown>>;
  const costLayers = value.cost_layers as Array<Record<string, unknown>>;
  const valuationByNumber = new Map<string, Record<string, unknown>>();
  for (const valuation of valuations) {
    const number = String(valuation.valuation_number);
    if (valuationByNumber.has(number)) return false;
    valuationByNumber.set(number, valuation);
  }
  const reversalNumbers = new Set<string>();
  for (const reversal of reversals) {
    const number = String(reversal.reversal_number);
    if (reversalNumbers.has(number)) return false;
    reversalNumbers.add(number);
    const original = valuationByNumber.get(String(reversal.original_valuation_number));
    if (
      !original || original.status !== "Approved" ||
      reversal.original_movement_type !== original.movement_type ||
      reversal.entity_code !== original.entity_code ||
      reversal.currency_code !== original.currency_code ||
      reversal.total_value !== original.total_value ||
      String(reversal.reversal_date) < String(original.valuation_date)
    ) return false;
    const expectedEffect = original.movement_type === "Receipt" ? "Remove" : original.movement_type === "Delivery" ? "Restore" : reversal.layer_effect;
    if (reversal.layer_effect !== expectedEffect) return false;
    if (original.movement_type === "Receipt") {
      const originalLayers = costLayers.filter((layer) => layer.valuation_number === original.valuation_number);
      if (!originalLayers.length || originalLayers.some((layer) => Number(layer.remaining_quantity) !== 0 || Number(layer.remaining_value) !== 0)) return false;
    }
  }
  return true;
}

function inventorySummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, number>;
  const onHand = value.on_hand as Array<Record<string, unknown>>;
  const movements = value.movements as Array<Record<string, unknown>>;
  const valuations = value.valuations as Array<Record<string, unknown>>;
  const reversals = value.valuation_reversals as Array<Record<string, unknown>>;
  const layers = value.cost_layers as Array<Record<string, unknown>>;
  return (
    summary.item_count === new Set(onHand.map((record) => String(record.item_code))).size &&
    summary.warehouse_count === (value.warehouses as unknown[]).length &&
    summary.location_count === new Set(onHand.map((record) => `${record.warehouse_code}/${record.location_code}`)).size &&
    summary.movement_count === movements.length &&
    summary.posted_movement_count === movements.filter((record) => record.status === "Posted").length &&
    summary.exception_count === (value.exceptions as unknown[]).length &&
    summary.count_session_count === (value.count_sessions as unknown[]).length &&
    summary.reorder_signal_count === (value.reorder_signals as unknown[]).length &&
    summary.valuation_document_count === valuations.length &&
    summary.valuation_reversal_count === reversals.length &&
    summary.open_cost_layer_count === layers.filter((layer) => layer.layer_status === "Open").length &&
    summary.finance_draft_count === [...valuations, ...reversals].filter((record) => record.finance_entry_status === "Draft").length
  );
}

function isInventoryControl(value: unknown): value is InventoryControlContract {
  if (!isObject(value)) return false;
  return (
    hasContractEnvelope(value) &&
    hasCountFields(value.summary, ["item_count", "warehouse_count", "location_count", "movement_count", "posted_movement_count", "exception_count", "count_session_count", "reorder_signal_count", "valuation_document_count", "valuation_reversal_count", "open_cost_layer_count", "finance_draft_count"]) &&
    Array.isArray(value.warehouses) && value.warehouses.every(isInventoryWarehouse) &&
    Array.isArray(value.on_hand) && value.on_hand.every(isInventoryOnHand) &&
    Array.isArray(value.movements) && value.movements.every(isInventoryMovement) &&
    Array.isArray(value.exceptions) && value.exceptions.every(isInventoryException) &&
    Array.isArray(value.count_sessions) && value.count_sessions.every(isInventoryCount) &&
    Array.isArray(value.reorder_signals) && value.reorder_signals.every(isInventoryReorderSignal) &&
    Array.isArray(value.valuations) && value.valuations.every(isInventoryValuation) &&
    Array.isArray(value.valuation_reversals) && value.valuation_reversals.every(isInventoryValuationReversal) &&
    Array.isArray(value.cost_layers) && value.cost_layers.every(isInventoryCostLayer) &&
    inventoryValuationReversalsAreConsistent(value) &&
    inventorySummaryIsConsistent(value)
  );
}

function isRetailSettlementDecision(value: unknown, expectedCurrency: string): boolean {
  if (!isObject(value)) return false;
  if (!hasTextFields(value, ["batch_id", "store_id", "expected_card_net", "currency", "reason_code"])) return false;
  if (!retailStatuses.has(String(value.status)) || !exactMoney.test(String(value.expected_card_net))) return false;
  if (!Array.isArray(value.settlement_ids) || value.settlement_ids.length > 100 || !value.settlement_ids.every(isText)) return false;
  if (value.settlement_net !== null && (!isText(value.settlement_net) || !exactMoney.test(value.settlement_net))) return false;
  if (value.net_variance !== null && (!isText(value.net_variance) || !exactMoney.test(value.net_variance))) return false;
  return value.currency === expectedCurrency && String(value.batch_id).length <= 120 && String(value.store_id).length <= 120;
}

function retailSettlementSummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, unknown>;
  const decisions = value.decisions as Array<Record<string, unknown>>;
  const statuses = decisions.map((decision) => String(decision.status));
  const unmatched = statuses.filter((status) => status === "unmatched_pos" || status === "unmatched_settlement").length;
  return (
    summary.total === decisions.length &&
    summary.matched === statuses.filter((status) => status === "matched").length &&
    summary.exceptions === statuses.filter((status) => status === "exception").length &&
    summary.unmatched === unmatched &&
    summary.ambiguous === statuses.filter((status) => status === "ambiguous").length &&
    new Set(decisions.map((decision) => String(decision.batch_id))).size === decisions.length
  );
}

function isRetailSettlementStudio(value: unknown): value is RetailSettlementStudioContract {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_RETAIL_SETTLEMENT_UI_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isText(value.algorithm_version) &&
    digest.test(String(value.decision_digest)) &&
    digest.test(String(value.artifact_digest)) &&
    exactMoney.test(String(value.tolerance)) &&
    !String(value.tolerance).startsWith("-") &&
    isText(value.currency) &&
    currencyCode.test(value.currency) &&
    hasCountFields(value.summary, ["total", "matched", "exceptions", "unmatched", "ambiguous"]) &&
    Array.isArray(value.decisions) &&
    value.decisions.length > 0 &&
    value.decisions.length <= 10_000 &&
    value.decisions.every((decision) => isRetailSettlementDecision(decision, value.currency as string)) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText) &&
    retailSettlementSummaryIsConsistent(value)
  );
}

function isBankStatementDecision(value: unknown, expectedCurrency: string): boolean {
  if (!isObject(value)) return false;
  if (!hasTextFields(value, ["bank_line_id", "account_id", "reason_code"])) return false;
  if (typeof value.status !== "string" || !bankStatuses.has(value.status as BankStatementStatus)) return false;
  if (!Array.isArray(value.ledger_record_ids) || value.ledger_record_ids.length > 100 || !value.ledger_record_ids.every(isText)) return false;
  if (value.amount_variance !== null && (!isText(value.amount_variance) || !exactMoney.test(value.amount_variance))) return false;
  if (value.days_variance !== null && (!isCount(value.days_variance) || value.days_variance > 366)) return false;
  return String(value.account_id).length <= 160 && String(value.bank_line_id).length <= 160 && expectedCurrency.length === 3;
}

function bankStatementSummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, unknown>;
  const decisions = value.decisions as Array<Record<string, unknown>>;
  const statuses = decisions.map((decision) => String(decision.status));
  const unmatched = statuses.filter((status) => status === "unmatched_bank" || status === "unmatched_ledger").length;
  return (
    summary.total === decisions.length &&
    summary.matched === statuses.filter((status) => status === "matched").length &&
    summary.exceptions === statuses.filter((status) => status === "exception").length &&
    summary.unmatched === unmatched &&
    summary.ambiguous === statuses.filter((status) => status === "ambiguous").length &&
    new Set(decisions.map((decision) => String(decision.bank_line_id))).size === decisions.length
  );
}

function isBankStatementStudio(value: unknown): value is BankStatementStudioContract {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_BANK_STATEMENT_UI_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isText(value.algorithm_version) &&
    digest.test(String(value.decision_digest)) &&
    digest.test(String(value.artifact_digest)) &&
    exactMoney.test(String(value.tolerance)) &&
    !String(value.tolerance).startsWith("-") &&
    isText(value.currency) &&
    currencyCode.test(value.currency) &&
    isCount(value.date_window_days) &&
    value.date_window_days <= 366 &&
    hasCountFields(value.summary, ["total", "matched", "exceptions", "unmatched", "ambiguous"]) &&
    Array.isArray(value.decisions) &&
    value.decisions.length > 0 &&
    value.decisions.length <= 10_000 &&
    value.decisions.every((decision) => isBankStatementDecision(decision, value.currency as string)) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText) &&
    bankStatementSummaryIsConsistent(value)
  );
}

function isManufacturingCostDecision(value: unknown, expectedUnit: string, expectedCurrency: string): boolean {
  if (!isObject(value)) return false;
  if (!hasTextFields(value, ["order_id", "product_id"])) return false;
  if (typeof value.status !== "string" || !manufacturingStatuses.has(value.status as ManufacturingCostStatus)) return false;
  const quantities = ["planned_quantity", "issued_quantity", "completed_quantity", "scrap_quantity"];
  if (!quantities.every((field) => isText(value[field]) && exactQuantity.test(value[field] as string) && !String(value[field]).startsWith("-"))) return false;
  if (!isText(value.material_cost_variance) || !exactMoney.test(value.material_cost_variance) || !isText(value.completion_cost_variance) || !exactMoney.test(value.completion_cost_variance)) return false;
  if (!Array.isArray(value.reason_codes) || value.reason_codes.length < 1 || value.reason_codes.length > 20 || !value.reason_codes.every(isText)) return false;
  return String(value.order_id).length <= 160 && String(value.product_id).length <= 160 && expectedUnit.length <= 16 && expectedCurrency.length === 3;
}

function manufacturingSummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, unknown>;
  const decisions = value.decisions as Array<Record<string, unknown>>;
  const statuses = decisions.map((decision) => String(decision.status));
  return (
    summary.total === decisions.length &&
    summary.reconciled === statuses.filter((status) => status === "reconciled").length &&
    summary.exceptions === statuses.filter((status) => status === "exception").length &&
    summary.unmatched === statuses.filter((status) => status === "unmatched").length &&
    new Set(decisions.map((decision) => String(decision.order_id))).size === decisions.length
  );
}

function isManufacturingCostStudio(value: unknown): value is ManufacturingCostStudioContract {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_MANUFACTURING_COST_UI_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isText(value.algorithm_version) &&
    digest.test(String(value.decision_digest)) &&
    digest.test(String(value.artifact_digest)) &&
    exactMoney.test(String(value.tolerance)) &&
    !String(value.tolerance).startsWith("-") &&
    isText(value.currency) &&
    currencyCode.test(value.currency) &&
    isText(value.unit) &&
    isText(value.max_scrap_quantity) &&
    exactQuantity.test(value.max_scrap_quantity) &&
    !String(value.max_scrap_quantity).startsWith("-") &&
    hasCountFields(value.summary, ["total", "reconciled", "exceptions", "unmatched"]) &&
    Array.isArray(value.decisions) &&
    value.decisions.length > 0 &&
    value.decisions.length <= 10_000 &&
    value.decisions.every((decision) => isManufacturingCostDecision(decision, value.unit as string, value.currency as string)) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText) &&
    manufacturingSummaryIsConsistent(value)
  );
}

function isProfessionalInvoicePaymentDecision(value: unknown, expectedCurrency: string): boolean {
  if (!isObject(value)) return false;
  if (!hasTextFields(value, ["invoice_id", "client_id", "reason_code"])) return false;
  if (typeof value.status !== "string" || !professionalStatuses.has(value.status as ProfessionalInvoicePaymentStatus)) return false;
  if (!Array.isArray(value.payment_ids) || value.payment_ids.length > 100 || !value.payment_ids.every(isText)) return false;
  if (value.amount_variance !== null && (!isText(value.amount_variance) || !exactMoney.test(value.amount_variance))) return false;
  if (value.days_from_due_date !== null && (typeof value.days_from_due_date !== "number" || !Number.isInteger(value.days_from_due_date) || value.days_from_due_date < -366 || value.days_from_due_date > 366)) return false;
  return String(value.invoice_id).length <= 160 && String(value.client_id).length <= 160 && expectedCurrency.length === 3;
}

function professionalSummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, unknown>;
  const decisions = value.decisions as Array<Record<string, unknown>>;
  const statuses = decisions.map((decision) => String(decision.status));
  return (
    summary.total === decisions.length &&
    summary.matched === statuses.filter((status) => status === "matched").length &&
    summary.exceptions === statuses.filter((status) => status === "exception").length &&
    summary.ambiguous === statuses.filter((status) => status === "ambiguous").length &&
    summary.unmatched_invoice === statuses.filter((status) => status === "unmatched_invoice").length &&
    summary.unmatched_payment === statuses.filter((status) => status === "unmatched_payment").length &&
    new Set(decisions.map((decision) => String(decision.invoice_id))).size === decisions.length
  );
}

function isProfessionalInvoicePaymentStudio(value: unknown): value is ProfessionalInvoicePaymentStudioContract {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_PROFESSIONAL_INVOICE_PAYMENT_UI_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isText(value.algorithm_version) &&
    digest.test(String(value.decision_digest)) &&
    digest.test(String(value.artifact_digest)) &&
    exactMoney.test(String(value.tolerance)) &&
    !String(value.tolerance).startsWith("-") &&
    isText(value.currency) &&
    currencyCode.test(value.currency) &&
    isCount(value.payment_window_days) &&
    value.payment_window_days <= 366 &&
    hasCountFields(value.summary, ["total", "matched", "exceptions", "ambiguous", "unmatched_invoice", "unmatched_payment"]) &&
    Array.isArray(value.decisions) &&
    value.decisions.length > 0 &&
    value.decisions.length <= 10_000 &&
    value.decisions.every((decision) => isProfessionalInvoicePaymentDecision(decision, value.currency as string)) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText) &&
    professionalSummaryIsConsistent(value)
  );
}

function isIndividualCashflowDecision(value: unknown, expectedCurrency: string): boolean {
  if (!isObject(value)) return false;
  if (!hasTextFields(value, ["period", "category", "reason_code"])) return false;
  if (typeof value.period !== "string" || !/^\d{4}-\d{2}$/.test(value.period)) return false;
  if (value.flow_type !== "income" && value.flow_type !== "expense") return false;
  if (typeof value.status !== "string" || !individualCashflowStatuses.has(value.status as IndividualCashflowStatus)) return false;
  if (!isText(value.actual) || !exactMoney.test(value.actual) || !isText(value.reason_code)) return false;
  if (value.budget !== null && (!isText(value.budget) || !exactMoney.test(value.budget))) return false;
  if (value.variance !== null && (!isText(value.variance) || !exactMoney.test(value.variance))) return false;
  return Array.isArray(value.transaction_ids) && value.transaction_ids.length <= 10_000 && value.transaction_ids.every(isText) && expectedCurrency.length === 3;
}

function individualCashflowSummaryIsConsistent(value: Record<string, unknown>): boolean {
  const summary = value.summary as Record<string, unknown>;
  const decisions = value.decisions as Array<Record<string, unknown>>;
  const statuses = decisions.map((decision) => String(decision.status));
  return (
    summary.total === decisions.length &&
    summary.within_budget === statuses.filter((status) => status === "within_budget").length &&
    summary.over_budget === statuses.filter((status) => status === "over_budget").length &&
    summary.unbudgeted === statuses.filter((status) => status === "unbudgeted").length &&
    summary.no_activity === statuses.filter((status) => status === "no_activity").length &&
    new Set(decisions.map((decision) => `${decision.period}:${decision.flow_type}:${decision.category}`)).size === decisions.length
  );
}

function isIndividualCashflowStudio(value: unknown): value is IndividualCashflowStudioContract {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_INDIVIDUAL_CASHFLOW_UI_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isText(value.algorithm_version) &&
    digest.test(String(value.decision_digest)) &&
    digest.test(String(value.artifact_digest)) &&
    isText(value.currency) &&
    currencyCode.test(value.currency) &&
    hasCountFields(value.summary, ["total", "within_budget", "over_budget", "unbudgeted", "no_activity"]) &&
    Array.isArray(value.decisions) &&
    value.decisions.length > 0 &&
    value.decisions.length <= 10_000 &&
    value.decisions.every((decision) => isIndividualCashflowDecision(decision, value.currency as string)) &&
    Array.isArray(value.notices) &&
    value.notices.every(isText) &&
    individualCashflowSummaryIsConsistent(value)
  );
}

function isExecutiveBrief(value: unknown): boolean {
  return (
    isObject(value) &&
    isScore(value.readiness_score) &&
    typeof value.readiness_status === "string" && showcaseStatuses.has(value.readiness_status) &&
    hasCountFields(value, ["high_risk_count", "open_exception_count", "blocked_task_count", "completed_task_count"])
  );
}

function isControlDomain(value: unknown): boolean {
  return (
    isObject(value) &&
    typeof value.domain === "string" && controlDomains.has(value.domain) &&
    isScore(value.score) &&
    typeof value.status === "string" && showcaseStatuses.has(value.status) &&
    isText(value.lineage)
  );
}

function isEntityHealth(value: unknown): boolean {
  return (
    hasTextFields(value, ["entity_code", "entity_name", "region", "currency"]) &&
    isObject(value) &&
    hasCountFields(value, ["open_exception_count", "high_risk_count"]) &&
    typeof value.status === "string" && showcaseStatuses.has(value.status)
  );
}

function showcaseIsConsistent(value: Record<string, unknown>): boolean {
  const brief = value.executive_brief as Record<string, unknown>;
  const metrics = value.metrics as Array<Record<string, unknown>>;
  const tasks = value.close_tasks as Array<Record<string, unknown>>;
  const riskDistribution = value.risk_distribution as Array<Record<string, unknown>>;
  const statusDistribution = value.status_distribution as Array<Record<string, unknown>>;
  const domains = value.control_domains as Array<Record<string, unknown>>;
  const entities = value.entities as Array<Record<string, unknown>>;
  const entityHealth = value.entity_health as Array<Record<string, unknown>>;
  const metricByKey = new Map(metrics.map((metric) => [String(metric.key), Number(metric.value)]));
  const domainMetric: Record<string, string> = {
    close: "close_completion",
    evidence: "evidence_coverage",
    matching: "match_rate",
    controls: "control_effectiveness",
  };
  const entityByCode = new Map(entities.map((entity) => [String(entity.entity_code), entity]));
  const entityHealthCodes = new Set<string>();
  const metricsAreEmpty = metrics.length === 0;
  const readinessIsConsistent = metricsAreEmpty
    ? brief.readiness_score === 0
    : brief.readiness_score === metricByKey.get("period_readiness");
  const domainsAreConsistent = metricsAreEmpty
    ? domains.length === 0
    : domains.length === 4 &&
      new Set(domains.map((domain) => String(domain.domain))).size === 4 &&
      domains.every((domain) => domain.score === metricByKey.get(domainMetric[String(domain.domain)]));
  return (
    readinessIsConsistent &&
    brief.high_risk_count === riskDistribution
      .filter((point) => ["critical", "high"].includes(String(point.risk)))
      .reduce((sum, point) => sum + Number(point.count), 0) &&
    brief.open_exception_count === statusDistribution
      .filter((point) => !["closed", "resolved"].includes(String(point.status).toLowerCase()))
      .reduce((sum, point) => sum + Number(point.count), 0) &&
    brief.blocked_task_count === tasks.filter((task) => String(task.status).toLowerCase() === "blocked").length &&
    brief.completed_task_count === tasks.filter((task) => String(task.status).toLowerCase() === "complete").length &&
    domainsAreConsistent &&
    entityHealth.length === entities.length &&
    entityHealth.every((health) => {
      const code = String(health.entity_code);
      const entity = entityByCode.get(code);
      if (!entity || entityHealthCodes.has(code)) return false;
      entityHealthCodes.add(code);
      return health.entity_name === entity.entity_name && health.region === entity.region && health.currency === entity.currency;
    })
  );
}

function isStudioOverview(value: unknown): value is StudioOverview {
  if (!isObject(value)) return false;
  return (
    value.schema_version === 1 &&
    value.synthetic_data_only === true &&
    value.synthetic_data_marker === "SYNTHETIC_ENTERPRISE_DEMO_ONLY" &&
    isText(value.generated_at) &&
    isContractSource(value.source) &&
    isObject(value.workspace) &&
    isText(value.workspace.name) &&
    isText(value.workspace.current_period) &&
    isCount(value.workspace.entity_count) &&
    isCount(value.workspace.evidence_count) &&
    isCount(value.workspace.close_task_count) &&
    isExecutiveBrief(value.executive_brief) &&
    Array.isArray(value.control_domains) && value.control_domains.every(isControlDomain) &&
    Array.isArray(value.entity_health) && value.entity_health.every(isEntityHealth) &&
    Array.isArray(value.metrics) && value.metrics.every(isMetric) &&
    Array.isArray(value.risk_distribution) && value.risk_distribution.every(isDistributionPoint) &&
    Array.isArray(value.status_distribution) && value.status_distribution.every(isDistributionPoint) &&
    Array.isArray(value.entities) && value.entities.every((record) => hasTextFields(record, ["entity_code", "entity_name", "region", "currency"])) &&
    Array.isArray(value.close_tasks) && value.close_tasks.every((record) => hasTextFields(record, ["task_id", "period_name", "name", "status", "owner"])) &&
    Array.isArray(value.exceptions) && value.exceptions.every(isException) &&
    Array.isArray(value.notices) && value.notices.every(isText) &&
    showcaseIsConsistent(value)
  );
}

export async function loadStudioOverview(signal?: AbortSignal): Promise<StudioOverview> {
  return loadContract(OVERVIEW_URL, isStudioOverview, "overview", signal);
}

export async function loadExceptionQueue(signal?: AbortSignal): Promise<ExceptionQueueContract> {
  return loadContract(EXCEPTIONS_URL, isExceptionQueue, "exception queue", signal);
}

export async function loadEvidenceBinder(signal?: AbortSignal): Promise<EvidenceBinderContract> {
  return loadContract(EVIDENCE_URL, isEvidenceBinder, "evidence binder", signal);
}

export async function loadInventoryControl(signal?: AbortSignal): Promise<InventoryControlContract> {
  return loadContract(INVENTORY_URL, isInventoryControl, "inventory control", signal);
}

export async function loadRetailSettlementStudio(signal?: AbortSignal): Promise<RetailSettlementStudioContract> {
  return loadContract(RETAIL_SETTLEMENT_URL, isRetailSettlementStudio, "retail settlement", signal);
}

export async function loadBankStatementStudio(signal?: AbortSignal): Promise<BankStatementStudioContract> {
  return loadContract(BANK_STATEMENT_URL, isBankStatementStudio, "bank statement", signal);
}

export async function loadManufacturingCostStudio(signal?: AbortSignal): Promise<ManufacturingCostStudioContract> {
  return loadContract(MANUFACTURING_COST_URL, isManufacturingCostStudio, "manufacturing cost", signal);
}

export async function loadProfessionalInvoicePaymentStudio(signal?: AbortSignal): Promise<ProfessionalInvoicePaymentStudioContract> {
  return loadContract(PROFESSIONAL_INVOICE_PAYMENT_URL, isProfessionalInvoicePaymentStudio, "professional invoice/payment", signal);
}

export async function loadIndividualCashflowStudio(signal?: AbortSignal): Promise<IndividualCashflowStudioContract> {
  return loadContract(INDIVIDUAL_CASHFLOW_URL, isIndividualCashflowStudio, "individual cashflow", signal);
}

async function loadContract<T>(
  url: string,
  validator: (value: unknown) => value is T,
  label: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) {
    throw new Error(`The local Studio ${label} artifact could not be loaded (${response.status}).`);
  }
  const value: unknown = await response.json();
  if (!validator(value)) {
    throw new Error(`The local Studio ${label} artifact does not match schema version 1.`);
  }
  return value;
}

const LIVE_METRICS_PATH = "/api/v1/metrics/dashboard" as const;
const exactMetricValue = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

function isLiveMetric(value: unknown): value is LiveStudioMetric {
  const allowed = new Set(["id", "workspace_id", "metric_key", "period_name", "value", "value_text", "lineage", "computed_at", "name", "description"]);
  return isObject(value) &&
    Object.keys(value).every((key) => allowed.has(key)) &&
    hasTextFields(value, ["metric_key", "period_name", "value_text", "lineage", "computed_at", "name", "description"]) &&
    /^[a-z0-9][a-z0-9_]{0,79}$/.test(value.metric_key as string) &&
    exactMetricValue.test(value.value_text as string) &&
    Number.isFinite(Date.parse(value.computed_at as string));
}

export interface LiveStudioLoadOptions {
  baseUrl?: string;
  period?: string;
  staleAfterSeconds?: number;
  signal?: AbortSignal;
  now?: Date;
  fetcher?: typeof fetch;
}

export async function loadLiveStudioContract(options: LiveStudioLoadOptions = {}): Promise<LiveStudioContract> {
  const staleAfterSeconds = options.staleAfterSeconds ?? 300;
  if (!Number.isInteger(staleAfterSeconds) || staleAfterSeconds < 30 || staleAfterSeconds > 86_400) throw new Error("Live Studio stale threshold must be between 30 and 86400 seconds.");
  const base = (options.baseUrl ?? "").replace(/\/$/, "");
  const query = options.period ? `?period=${encodeURIComponent(options.period)}` : "";
  const response = await (options.fetcher ?? fetch)(`${base}${LIVE_METRICS_PATH}${query}`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (response.status === 401) throw new Error("Live Studio authentication is required.");
  if (response.status === 403) throw new Error("Live Studio metrics.read permission is required.");
  if (!response.ok) throw new Error(`Live Studio contract could not be loaded (${response.status}).`);
  const payload: unknown = await response.json();
  if (!isObject(payload) || Object.keys(payload).some((key) => key !== "metrics") || !Array.isArray(payload.metrics) || !payload.metrics.every(isLiveMetric)) throw new Error("Live Studio response does not match the authorized metrics contract.");
  const metrics = [...payload.metrics].sort((left, right) => left.period_name.localeCompare(right.period_name) || left.metric_key.localeCompare(right.metric_key));
  const now = options.now ?? new Date();
  const newest = metrics.reduce<string | null>((current, metric) => current === null || Date.parse(metric.computed_at) > Date.parse(current) ? metric.computed_at : current, null);
  const ageSeconds = newest === null ? 0 : Math.max(0, (now.getTime() - Date.parse(newest)) / 1_000);
  return {
    mode: "live",
    endpoint: LIVE_METRICS_PATH,
    fetched_at: now.toISOString(),
    generated_at: newest,
    stale_after_seconds: staleAfterSeconds,
    stale: newest !== null && ageSeconds > staleAfterSeconds,
    empty: metrics.length === 0,
    metrics,
  };
}

export class AdminApiError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super(code);
  }
}

const adminPaths = {
  login: "/api/v1/auth/browser/login",
  stepUp: "/api/v1/auth/step-up",
  events: "/api/v1/admin/audit/events",
  verify: "/api/v1/admin/audit/verify",
  security: "/api/v1/admin/security/overview",
  identityUsers: "/api/v1/admin/identity/users",
  identitySessions: "/api/v1/admin/identity/sessions",
  accessPermissions: "/api/v1/admin/access/permissions",
  accessRoles: "/api/v1/admin/access/roles",
  integrations: "/api/v1/admin/security/integrations",
  retentionPolicies: "/api/v1/admin/security/retention-policies",
} as const;

async function adminResponse(response: Response): Promise<Response> {
  if (response.ok) return response;
  let code = `http_${response.status}`;
  try { const body: unknown = await response.json(); if (isObject(body) && isObject(body.error) && isText(body.error.code)) code = body.error.code; } catch { /* closed fallback */ }
  throw new AdminApiError(response.status, code);
}

function adminHeaders(tenantId: string, csrfToken?: string): HeadersInit {
  return { Accept: "application/json", "X-ReconForge-Tenant": tenantId, ...(csrfToken ? { "X-ReconForge-CSRF": csrfToken } : {}) };
}

export async function beginBrowserAdminSession(input: { tenantId: string; username: string; password: string; fetcher?: typeof fetch }): Promise<BrowserAdminSession> {
  const response = await (input.fetcher ?? fetch)(adminPaths.login, { method: "POST", cache: "no-store", credentials: "same-origin", headers: { ...adminHeaders(input.tenantId), "Content-Type": "application/json" }, body: JSON.stringify({ username: input.username, password: input.password }) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || !isText(body.csrf_token) || !isText(body.expires_at) || Object.keys(body).some((key) => key !== "csrf_token" && key !== "expires_at")) throw new Error("browser_session_contract_invalid");
  return { csrfToken: body.csrf_token, expiresAt: body.expires_at, tenantId: input.tenantId };
}

export async function stepUpBrowserAdminSession(session: BrowserAdminSession, password: string, fetcher?: typeof fetch): Promise<string> {
  const response = await (fetcher ?? fetch)(adminPaths.stepUp, { method: "POST", cache: "no-store", credentials: "same-origin", headers: { ...adminHeaders(session.tenantId, session.csrfToken), "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || !isText(body.expires_at) || Object.keys(body).some((key) => key !== "method" && key !== "expires_at")) throw new Error("step_up_contract_invalid");
  return body.expires_at;
}

function isAdminEvent(value: unknown): value is AdminAuditEvent {
  const allowed = new Set(["source", "event_id", "sequence", "occurred_at", "action", "object_type", "actor_digest", "object_digest", "metadata_digest", "previous_event_hash", "event_hash", "before_state_hash", "after_state_hash"]);
  return isObject(value) && Object.keys(value).every((key) => allowed.has(key)) && ["source", "event_id", "occurred_at", "action", "object_type", "actor_digest", "object_digest", "metadata_digest", "previous_event_hash", "event_hash"].every((key) => isText(value[key])) && ["domain", "ledger_control"].includes(String(value.source)) && Number.isInteger(value.sequence) && Number(value.sequence) >= 0 && ["before_state_hash", "after_state_hash"].every((key) => value[key] === null || isText(value[key]));
}

export async function loadAdminAuditPage(session: BrowserAdminSession, cursor?: string, fetcher?: typeof fetch): Promise<AdminAuditPage> {
  const query = new URLSearchParams({ limit: "100" }); if (cursor) query.set("cursor", cursor);
  const response = await (fetcher ?? fetch)(`${adminPaths.events}?${query}`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || !Array.isArray(body.events) || !body.events.every(isAdminEvent) || !isObject(body.pagination) || (body.pagination.next_cursor !== null && !isText(body.pagination.next_cursor))) throw new Error("audit_contract_invalid");
  return { events: body.events, nextCursor: body.pagination.next_cursor as string | null };
}

export async function verifyAdminAudit(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminAuditVerification[]> {
  const response = await (fetcher ?? fetch)(adminPaths.verify, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || typeof body.ok !== "boolean" || !Array.isArray(body.chains) || !body.chains.every((chain) => isObject(chain) && ["domain", "ledger_control"].includes(String(chain.source)) && typeof chain.ok === "boolean" && Number.isInteger(chain.checked_events) && isText(chain.head_hash) && Array.isArray(chain.issue_codes) && chain.issue_codes.every(isText))) throw new Error("audit_verification_contract_invalid");
  return body.chains as AdminAuditVerification[];
}

const securityNumberKeys = {
  identity: ["total_users", "active_users", "disabled_users", "locked_users", "active_users_without_roles", "roles", "permissions", "role_permission_bindings"],
  sessions: ["active_sessions", "revoked_sessions", "expired_unrevoked_sessions", "active_step_up_assertions", "active_webauthn_credentials", "users_with_active_webauthn"],
  integrations: ["configured_federation_providers", "linked_federation_providers", "active_federation_links", "disabled_federation_links", "scim_domains", "active_scim_users", "active_scim_credentials", "enabled_service_accounts", "active_service_account_credentials", "enabled_notification_routes"],
  policy: ["active_scope_grants", "pending_emergency_requests", "active_emergency_access", "overdue_emergency_reviews"],
  retention: ["evidence_records", "evidence_with_retention", "evidence_retention_expired", "evidence_unverified", "evidence_verification_failed"],
  audit: ["audit_events"],
} as const;

const securityRootKeys = new Set(["schema_version", "as_of", "tenant_scope_digest", "posture", "claim_boundary", "identity", "sessions", "integrations", "policy", "retention", "audit", "attention_items", "snapshot_digest"]);
const sha256Digest = /^[a-f0-9]{64}$/;

function isExactCountSection(value: unknown, keys: readonly string[], booleanKeys: readonly string[] = [], stringKeys: readonly string[] = []): value is Record<string, number | boolean | string> {
  return isObject(value) && Object.keys(value).length === keys.length + booleanKeys.length + stringKeys.length && keys.every((key) => Number.isInteger(value[key]) && Number(value[key]) >= 0) && booleanKeys.every((key) => typeof value[key] === "boolean") && stringKeys.every((key) => isText(value[key]));
}

function isSecurityAttention(value: unknown): boolean {
  return isObject(value) && Object.keys(value).length === 3 && ["medium", "high"].includes(String(value.severity)) && isText(value.code) && Number.isInteger(value.count) && Number(value.count) >= 0;
}

export async function loadAdminSecurityCenter(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminSecuritySnapshot> {
  const response = await (fetcher ?? fetch)(adminPaths.security, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) });
  const body: unknown = await (await adminResponse(response)).json();
  const sections = ["identity", "sessions", "integrations", "policy", "retention", "audit"] as const;
  if (!isObject(body) || Object.keys(body).length !== securityRootKeys.size || !Object.keys(body).every((key) => securityRootKeys.has(key)) || body.schema_version !== 1 || !isText(body.as_of) || !sha256Digest.test(String(body.tenant_scope_digest)) || !["attention_required", "observed_no_count_based_attention"].includes(String(body.posture)) || body.claim_boundary !== "operational_snapshot_not_security_assurance" || !Array.isArray(body.attention_items) || !body.attention_items.every(isSecurityAttention) || !sha256Digest.test(String(body.snapshot_digest)) || !sections.every((section) => isExactCountSection(body[section], securityNumberKeys[section], section === "integrations" ? ["federation_air_gap_mode", "webauthn_required_for_privileged_actions"] : [], section === "audit" ? ["chain_verification"] : [])) || !isObject(body.audit) || body.audit.chain_verification !== "not_evaluated_use_audit_verify_endpoint") throw new Error("security_center_contract_invalid");
  return { asOf: body.as_of, posture: body.posture as AdminSecuritySnapshot["posture"], attention: body.attention_items as AdminSecuritySnapshot["attention"], sections: sections.map((id) => ({ id, values: body[id] as Record<string, number | boolean | string> })) };
}

function isExactIdentityUser(value: unknown): value is Record<string, unknown> {
  const keys = ["id", "username", "display_name", "disabled", "lifecycle_version", "roles", "active_sessions", "created_at", "disabled_at", "state_digest"];
  return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["id", "username", "display_name", "created_at", "state_digest"].every((key) => isText(value[key])) && typeof value.disabled === "boolean" && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && Array.isArray(value.roles) && value.roles.every(isText) && isCount(value.active_sessions) && (value.disabled_at === null || isText(value.disabled_at)) && sha256Digest.test(String(value.state_digest));
}

function isExactIdentitySession(value: unknown): value is Record<string, unknown> {
  const keys = ["id", "user_id", "username", "status", "lifecycle_version", "created_at", "expires_at", "last_used_at", "revoked_at", "revocation_reason_code", "client_ip_recorded", "user_agent_recorded", "state_digest"];
  return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["id", "user_id", "username", "created_at", "expires_at", "state_digest"].every((key) => isText(value[key])) && ["active", "expired", "revoked"].includes(String(value.status)) && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && ["last_used_at", "revoked_at", "revocation_reason_code"].every((key) => value[key] === null || isText(value[key])) && typeof value.client_ip_recorded === "boolean" && typeof value.user_agent_recorded === "boolean" && sha256Digest.test(String(value.state_digest));
}

function isIdentityPage(value: unknown, collection: "users" | "sessions", entry: (item: unknown) => boolean): boolean {
  return isObject(value) && Object.keys(value).length === 2 && Array.isArray(value[collection]) && value[collection].every(entry) && isObject(value.pagination) && Object.keys(value.pagination).length === 3 && Number.isInteger(value.pagination.limit) && Number(value.pagination.limit) >= 1 && Number.isInteger(value.pagination.returned) && Number(value.pagination.returned) === value[collection].length && (value.pagination.next_cursor === null || isText(value.pagination.next_cursor));
}

export async function loadAdminIdentityUsers(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminIdentityUser[]> {
  const response = await (fetcher ?? fetch)(`${adminPaths.identityUsers}?limit=100`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isIdentityPage(body, "users", isExactIdentityUser)) throw new Error("identity_users_contract_invalid");
  const page = body as { users: Record<string, unknown>[] };
  return page.users.map((user) => ({ id: String(user.id), username: String(user.username), displayName: String(user.display_name), disabled: Boolean(user.disabled), lifecycleVersion: Number(user.lifecycle_version), roles: user.roles as string[], activeSessions: Number(user.active_sessions), createdAt: String(user.created_at), disabledAt: user.disabled_at as string | null, stateDigest: String(user.state_digest) }));
}

function userFromResponse(user: Record<string, unknown>): AdminIdentityUser {
  return { id: String(user.id), username: String(user.username), displayName: String(user.display_name), disabled: Boolean(user.disabled), lifecycleVersion: Number(user.lifecycle_version), roles: user.roles as string[], activeSessions: Number(user.active_sessions), createdAt: String(user.created_at), disabledAt: user.disabled_at as string | null, stateDigest: String(user.state_digest) };
}

export async function setAdminIdentityUserDisabled(
  session: BrowserAdminSession,
  target: Pick<AdminIdentityUser, "id" | "lifecycleVersion">,
  disabled: boolean,
  fetcher?: typeof fetch,
): Promise<AdminIdentityUserStatusChange> {
  const response = await (fetcher ?? fetch)(`${adminPaths.identityUsers}/${encodeURIComponent(target.id)}/status`, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { ...adminHeaders(session.tenantId, session.csrfToken), "Content-Type": "application/json" },
    body: JSON.stringify({ disabled, expected_lifecycle_version: target.lifecycleVersion }),
  });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || Object.keys(body).length !== 4 || !isExactIdentityUser(body.user) || typeof body.transitioned !== "boolean" || !isCount(body.revoked_sessions) || (body.audit_event_id !== null && !isText(body.audit_event_id))) throw new Error("identity_user_status_contract_invalid");
  return { user: userFromResponse(body.user), transitioned: body.transitioned, revokedSessions: Number(body.revoked_sessions), auditEventId: body.audit_event_id as string | null };
}

export async function loadAdminIdentitySessions(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminIdentitySession[]> {
  const response = await (fetcher ?? fetch)(`${adminPaths.identitySessions}?limit=100`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isIdentityPage(body, "sessions", isExactIdentitySession)) throw new Error("identity_sessions_contract_invalid");
  const page = body as { sessions: Record<string, unknown>[] };
  return page.sessions.map((item) => ({ id: String(item.id), userId: String(item.user_id), username: String(item.username), status: item.status as AdminIdentitySession["status"], lifecycleVersion: Number(item.lifecycle_version), createdAt: String(item.created_at), expiresAt: String(item.expires_at), lastUsedAt: item.last_used_at as string | null, revokedAt: item.revoked_at as string | null, revocationReasonCode: item.revocation_reason_code as string | null, clientIpRecorded: Boolean(item.client_ip_recorded), userAgentRecorded: Boolean(item.user_agent_recorded), stateDigest: String(item.state_digest) }));
}

function sessionFromResponse(item: Record<string, unknown>): AdminIdentitySession {
  return { id: String(item.id), userId: String(item.user_id), username: String(item.username), status: item.status as AdminIdentitySession["status"], lifecycleVersion: Number(item.lifecycle_version), createdAt: String(item.created_at), expiresAt: String(item.expires_at), lastUsedAt: item.last_used_at as string | null, revokedAt: item.revoked_at as string | null, revocationReasonCode: item.revocation_reason_code as string | null, clientIpRecorded: Boolean(item.client_ip_recorded), userAgentRecorded: Boolean(item.user_agent_recorded), stateDigest: String(item.state_digest) };
}

export async function revokeAdminIdentitySession(
  session: BrowserAdminSession,
  target: Pick<AdminIdentitySession, "id" | "lifecycleVersion">,
  reasonCode: "access_change" | "administrative_cleanup" | "security_response" | "user_request",
  fetcher?: typeof fetch,
): Promise<AdminSessionRevocation> {
  const response = await (fetcher ?? fetch)(`${adminPaths.identitySessions}/${encodeURIComponent(target.id)}/revoke`, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { ...adminHeaders(session.tenantId, session.csrfToken), "Content-Type": "application/json" },
    body: JSON.stringify({ expected_lifecycle_version: target.lifecycleVersion, reason_code: reasonCode }),
  });
  const body: unknown = await (await adminResponse(response)).json();
  if (!isObject(body) || Object.keys(body).length !== 4 || !isExactIdentitySession(body.session) || typeof body.transitioned !== "boolean" || typeof body.revoked_current_session !== "boolean" || (body.audit_event_id !== null && !isText(body.audit_event_id))) throw new Error("identity_session_revocation_contract_invalid");
  return { session: sessionFromResponse(body.session), transitioned: body.transitioned, revokedCurrentSession: body.revoked_current_session, auditEventId: body.audit_event_id as string | null };
}

function isExactAccessPermission(value: unknown): value is Record<string, unknown> { const keys = ["name", "description", "active_role_count", "state_digest"]; return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["name", "description", "state_digest"].every((key) => isText(value[key])) && isCount(value.active_role_count) && sha256Digest.test(String(value.state_digest)); }
function isExactAccessRole(value: unknown): value is Record<string, unknown> { const keys = ["id", "name", "description", "active", "lifecycle_version", "permissions", "active_user_count", "created_at", "updated_at", "retired_at", "state_digest"]; return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["id", "name", "description", "created_at", "updated_at", "state_digest"].every((key) => isText(value[key])) && typeof value.active === "boolean" && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && Array.isArray(value.permissions) && value.permissions.every(isText) && isCount(value.active_user_count) && (value.retired_at === null || isText(value.retired_at)) && sha256Digest.test(String(value.state_digest)); }

export async function loadAdminAccessPermissions(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminAccessPermission[]> { const response = await (fetcher ?? fetch)(adminPaths.accessPermissions, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) }); const body: unknown = await (await adminResponse(response)).json(); if (!Array.isArray(body) || !body.every(isExactAccessPermission)) throw new Error("access_permissions_contract_invalid"); return body.map((item) => ({ name: String(item.name), description: String(item.description), activeRoleCount: Number(item.active_role_count), stateDigest: String(item.state_digest) })); }

export async function loadAdminAccessRoles(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminAccessRole[]> { const response = await (fetcher ?? fetch)(`${adminPaths.accessRoles}?limit=100&include_retired=true`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) }); const body: unknown = await (await adminResponse(response)).json(); if (!isObject(body) || Object.keys(body).length !== 2 || !Array.isArray(body.roles) || !body.roles.every(isExactAccessRole) || !isObject(body.pagination) || Object.keys(body.pagination).length !== 3 || !Number.isInteger(body.pagination.limit) || Number(body.pagination.limit) < 1 || !Number.isInteger(body.pagination.returned) || Number(body.pagination.returned) !== body.roles.length || (body.pagination.next_cursor !== null && !isText(body.pagination.next_cursor))) throw new Error("access_roles_contract_invalid"); return body.roles.map((item) => ({ id: String(item.id), name: String(item.name), description: String(item.description), active: Boolean(item.active), lifecycleVersion: Number(item.lifecycle_version), permissions: item.permissions as string[], activeUserCount: Number(item.active_user_count), createdAt: String(item.created_at), updatedAt: String(item.updated_at), retiredAt: item.retired_at as string | null, stateDigest: String(item.state_digest) })); }

function roleFromResponse(item: Record<string, unknown>): AdminAccessRole { return { id: String(item.id), name: String(item.name), description: String(item.description), active: Boolean(item.active), lifecycleVersion: Number(item.lifecycle_version), permissions: item.permissions as string[], activeUserCount: Number(item.active_user_count), createdAt: String(item.created_at), updatedAt: String(item.updated_at), retiredAt: item.retired_at as string | null, stateDigest: String(item.state_digest) }; }
async function accessRoleChange(response: Response): Promise<AdminAccessRoleChange> { const body: unknown = await (await adminResponse(response)).json(); if (!isObject(body) || Object.keys(body).length !== 4 || !isExactAccessRole(body.role) || typeof body.transitioned !== "boolean" || !isCount(body.revoked_sessions) || (body.audit_event_id !== null && !isText(body.audit_event_id))) throw new Error("access_role_change_contract_invalid"); return { role: roleFromResponse(body.role), transitioned: body.transitioned, revokedSessions: Number(body.revoked_sessions), auditEventId: body.audit_event_id as string | null }; }
function accessMutation(session: BrowserAdminSession, method: "POST" | "PATCH" | "PUT", path: string, payload: object, fetcher?: typeof fetch): Promise<Response> { return (fetcher ?? fetch)(path, { method, cache: "no-store", credentials: "same-origin", headers: { ...adminHeaders(session.tenantId, session.csrfToken), "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }

export async function createAdminAccessRole(session: BrowserAdminSession, input: { name: string; description: string; permissions: string[] }, fetcher?: typeof fetch): Promise<AdminAccessRoleChange> { return accessRoleChange(await accessMutation(session, "POST", adminPaths.accessRoles, input, fetcher)); }
export async function setAdminAccessRoleActive(session: BrowserAdminSession, role: Pick<AdminAccessRole, "id" | "lifecycleVersion">, active: boolean, fetcher?: typeof fetch): Promise<AdminAccessRoleChange> { return accessRoleChange(await accessMutation(session, "PATCH", `${adminPaths.accessRoles}/${encodeURIComponent(role.id)}`, { expected_lifecycle_version: role.lifecycleVersion, active }, fetcher)); }
export async function replaceAdminAccessRolePermissions(session: BrowserAdminSession, role: Pick<AdminAccessRole, "id" | "lifecycleVersion">, permissions: string[], fetcher?: typeof fetch): Promise<AdminAccessRoleChange> { return accessRoleChange(await accessMutation(session, "PUT", `${adminPaths.accessRoles}/${encodeURIComponent(role.id)}/permissions`, { expected_lifecycle_version: role.lifecycleVersion, permissions }, fetcher)); }

function isExactUserRoleAssignment(value: unknown): value is Record<string, unknown> { const keys = ["user_id", "username", "lifecycle_version", "role_ids", "role_names", "transitioned", "revoked_sessions", "audit_event_id", "state_digest"]; return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["user_id", "username", "state_digest"].every((key) => isText(value[key])) && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && Array.isArray(value.role_ids) && value.role_ids.every(isText) && Array.isArray(value.role_names) && value.role_names.every(isText) && typeof value.transitioned === "boolean" && isCount(value.revoked_sessions) && (value.audit_event_id === null || isText(value.audit_event_id)) && sha256Digest.test(String(value.state_digest)); }
export async function replaceAdminUserRoles(session: BrowserAdminSession, user: Pick<AdminIdentityUser, "id" | "lifecycleVersion">, roleIds: string[], fetcher?: typeof fetch): Promise<AdminUserRoleAssignment> { const body: unknown = await (await adminResponse(await accessMutation(session, "PUT", `/api/v1/admin/access/users/${encodeURIComponent(user.id)}/roles`, { expected_user_lifecycle_version: user.lifecycleVersion, role_ids: roleIds }, fetcher))).json(); if (!isExactUserRoleAssignment(body)) throw new Error("access_user_roles_contract_invalid"); return { userId: String(body.user_id), username: String(body.username), lifecycleVersion: Number(body.lifecycle_version), roleIds: body.role_ids as string[], roleNames: body.role_names as string[], transitioned: Boolean(body.transitioned), revokedSessions: Number(body.revoked_sessions), auditEventId: body.audit_event_id as string | null, stateDigest: String(body.state_digest) }; }

function isExactIntegration(value: unknown): value is Record<string, unknown> { const keys = ["kind", "id", "status", "lifecycle_version", "credential_count", "active_credential_count", "created_at", "expires_at", "last_used_at", "scope_digest", "state_digest"]; return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["id", "created_at", "scope_digest", "state_digest"].every((key) => isText(value[key])) && ["federation_link", "notification_route", "scim_credential", "service_account"].includes(String(value.kind)) && ["active", "disabled", "expired"].includes(String(value.status)) && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && isCount(value.credential_count) && isCount(value.active_credential_count) && ["expires_at", "last_used_at"].every((key) => value[key] === null || isText(value[key])) && sha256Digest.test(String(value.scope_digest)) && sha256Digest.test(String(value.state_digest)); }
function isExactRetentionPolicy(value: unknown): value is Record<string, unknown> { const keys = ["id", "name", "description", "data_classification", "duration_days", "active", "lifecycle_version", "created_at", "updated_at", "retired_at", "state_digest"]; return isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)) && ["id", "name", "description", "created_at", "updated_at", "state_digest"].every((key) => isText(value[key])) && ["public", "internal", "confidential", "restricted"].includes(String(value.data_classification)) && Number.isInteger(value.duration_days) && Number(value.duration_days) >= 1 && typeof value.active === "boolean" && Number.isInteger(value.lifecycle_version) && Number(value.lifecycle_version) >= 1 && (value.retired_at === null || isText(value.retired_at)) && sha256Digest.test(String(value.state_digest)); }
function pageRecords(body: unknown, collection: string, entry: (value: unknown) => boolean): Record<string, unknown>[] | null { if (!isObject(body) || Object.keys(body).length !== 2 || !Array.isArray(body[collection]) || !body[collection].every(entry) || !isObject(body.pagination) || Object.keys(body.pagination).length !== 3 || !Number.isInteger(body.pagination.limit) || Number(body.pagination.limit) < 1 || !Number.isInteger(body.pagination.returned) || Number(body.pagination.returned) !== body[collection].length || (body.pagination.next_cursor !== null && !isText(body.pagination.next_cursor))) return null; return body[collection] as Record<string, unknown>[]; }
function integrationFromResponse(item: Record<string, unknown>): AdminIntegration { return { kind: item.kind as AdminIntegration["kind"], id: String(item.id), status: item.status as AdminIntegration["status"], lifecycleVersion: Number(item.lifecycle_version), credentialCount: Number(item.credential_count), activeCredentialCount: Number(item.active_credential_count), createdAt: String(item.created_at), expiresAt: item.expires_at as string | null, lastUsedAt: item.last_used_at as string | null, scopeDigest: String(item.scope_digest), stateDigest: String(item.state_digest) }; }
function retentionPolicyFromResponse(item: Record<string, unknown>): AdminRetentionPolicy { return { id: String(item.id), name: String(item.name), description: String(item.description), dataClassification: item.data_classification as AdminRetentionPolicy["dataClassification"], durationDays: Number(item.duration_days), active: Boolean(item.active), lifecycleVersion: Number(item.lifecycle_version), createdAt: String(item.created_at), updatedAt: String(item.updated_at), retiredAt: item.retired_at as string | null, stateDigest: String(item.state_digest) }; }
export async function loadAdminIntegrations(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminIntegration[]> { const response = await (fetcher ?? fetch)(`${adminPaths.integrations}?limit=100&include_inactive=true`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) }); const records = pageRecords(await (await adminResponse(response)).json(), "integrations", isExactIntegration); if (!records) throw new Error("integrations_contract_invalid"); return records.map(integrationFromResponse); }
export async function loadAdminRetentionPolicies(session: BrowserAdminSession, fetcher?: typeof fetch): Promise<AdminRetentionPolicy[]> { const response = await (fetcher ?? fetch)(`${adminPaths.retentionPolicies}?limit=100&include_retired=true`, { cache: "no-store", credentials: "same-origin", headers: adminHeaders(session.tenantId) }); const records = pageRecords(await (await adminResponse(response)).json(), "policies", isExactRetentionPolicy); if (!records) throw new Error("retention_policies_contract_invalid"); return records.map(retentionPolicyFromResponse); }

export async function disableAdminIntegration(session: BrowserAdminSession, integration: AdminIntegration, reasonCode: string, fetcher?: typeof fetch): Promise<import("./types").AdminIntegrationDisable> { const body: unknown = await (await adminResponse(await accessMutation(session, "POST", `${adminPaths.integrations}/${integration.kind}/${encodeURIComponent(integration.id)}/disable`, { expected_state_digest: integration.stateDigest, reason_code: reasonCode }, fetcher))).json(); if (!isObject(body) || Object.keys(body).length !== 4 || !isExactIntegration(body.integration) || typeof body.transitioned !== "boolean" || !isCount(body.revoked_credentials) || (body.audit_event_id !== null && !isText(body.audit_event_id))) throw new Error("integration_disable_contract_invalid"); return { integration: integrationFromResponse(body.integration), transitioned: body.transitioned, revokedCredentials: Number(body.revoked_credentials), auditEventId: body.audit_event_id as string | null }; }
async function retentionPolicyChange(response: Response): Promise<import("./types").AdminRetentionPolicyChange> { const body: unknown = await (await adminResponse(response)).json(); if (!isObject(body) || Object.keys(body).length !== 3 || !isExactRetentionPolicy(body.policy) || typeof body.transitioned !== "boolean" || (body.audit_event_id !== null && !isText(body.audit_event_id))) throw new Error("retention_policy_change_contract_invalid"); return { policy: retentionPolicyFromResponse(body.policy), transitioned: body.transitioned, auditEventId: body.audit_event_id as string | null }; }
export async function createAdminRetentionPolicy(session: BrowserAdminSession, input: { name: string; description: string; dataClassification: AdminRetentionPolicy["dataClassification"]; durationDays: number }, fetcher?: typeof fetch) { return retentionPolicyChange(await accessMutation(session, "POST", adminPaths.retentionPolicies, { name: input.name, description: input.description, data_classification: input.dataClassification, duration_days: input.durationDays }, fetcher)); }
export async function updateAdminRetentionPolicy(session: BrowserAdminSession, policy: AdminRetentionPolicy, input: { description?: string; dataClassification?: AdminRetentionPolicy["dataClassification"]; durationDays?: number; active?: boolean }, fetcher?: typeof fetch) { return retentionPolicyChange(await accessMutation(session, "PATCH", `${adminPaths.retentionPolicies}/${encodeURIComponent(policy.id)}`, { expected_lifecycle_version: policy.lifecycleVersion, reason_code: "policy_change", ...(input.description === undefined ? {} : { description: input.description }), ...(input.dataClassification === undefined ? {} : { data_classification: input.dataClassification }), ...(input.durationDays === undefined ? {} : { duration_days: input.durationDays }), ...(input.active === undefined ? {} : { active: input.active }) }, fetcher)); }
export async function applyAdminRetentionPolicy(session: BrowserAdminSession, policy: AdminRetentionPolicy, evidenceId: string, expectedRetentionVersion: number, fetcher?: typeof fetch): Promise<import("./types").AdminEvidenceRetentionChange> { const body: unknown = await (await adminResponse(await accessMutation(session, "POST", `${adminPaths.retentionPolicies}/${encodeURIComponent(policy.id)}/evidence/${encodeURIComponent(evidenceId)}`, { expected_retention_version: expectedRetentionVersion, reason_code: "policy_application" }, fetcher))).json(); const keys = ["evidence_id", "policy_id", "policy_lifecycle_version", "retention_version", "previous_retention_until", "policy_retention_until", "effective_retention_until", "retention_extended", "transitioned", "audit_event_id", "state_digest"]; if (!isObject(body) || Object.keys(body).length !== keys.length || !keys.every((key) => Object.hasOwn(body, key)) || !["evidence_id", "policy_id", "policy_retention_until", "effective_retention_until", "state_digest"].every((key) => isText(body[key])) || !Number.isInteger(body.policy_lifecycle_version) || !Number.isInteger(body.retention_version) || (body.previous_retention_until !== null && !isText(body.previous_retention_until)) || typeof body.retention_extended !== "boolean" || typeof body.transitioned !== "boolean" || (body.audit_event_id !== null && !isText(body.audit_event_id)) || !sha256Digest.test(String(body.state_digest))) throw new Error("evidence_retention_contract_invalid"); return { retentionVersion: Number(body.retention_version), retentionExtended: body.retention_extended, transitioned: body.transitioned, auditEventId: body.audit_event_id as string | null, stateDigest: String(body.state_digest) }; }
