import type { EvidenceBinderContract, ExceptionQueueContract, InventoryControlContract, StudioOverview } from "./types";

const OVERVIEW_URL = `${import.meta.env.BASE_URL}demo/studio-overview.json`;
const EXCEPTIONS_URL = `${import.meta.env.BASE_URL}demo/studio-exceptions.json`;
const EVIDENCE_URL = `${import.meta.env.BASE_URL}demo/studio-evidence.json`;
const INVENTORY_URL = `${import.meta.env.BASE_URL}demo/studio-inventory.json`;
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
