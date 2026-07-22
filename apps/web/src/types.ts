export type Locale = "en" | "ar";
export type ThemePreference = "light" | "dark" | "system";
export type Density = "comfortable" | "compact";

export interface StudioMetric {
  key: string;
  label: string;
  value: number;
  format: "percent" | "count" | "days";
  tone: "positive" | "critical" | "warning" | "neutral";
  lineage: string;
}

export interface DistributionPoint {
  risk?: string;
  status?: string;
  count: number;
}

export interface StudioEntity {
  entity_code: string;
  entity_name: string;
  region: string;
  currency: string;
}

export type ShowcaseStatus = "strong" | "watch" | "attention";

export interface ExecutiveBrief {
  readiness_score: number;
  readiness_status: ShowcaseStatus;
  high_risk_count: number;
  open_exception_count: number;
  blocked_task_count: number;
  completed_task_count: number;
}

export interface ControlDomainHealth {
  domain: "close" | "evidence" | "matching" | "controls";
  score: number;
  status: ShowcaseStatus;
  lineage: string;
}

export interface EntityHealth extends StudioEntity {
  open_exception_count: number;
  high_risk_count: number;
  status: ShowcaseStatus;
}

export interface CloseTask {
  task_id: string;
  period_name: string;
  name: string;
  status: string;
  owner: string;
}

export interface StudioException {
  source_type: string;
  period_name: string;
  entity_code: string;
  account_code: string;
  control_code: string;
  risk_rating: string;
  owner: string;
  status: string;
  description: string;
}

export interface ContractSource {
  kind: "reconforge-enterprise-demo";
  local_first: true;
  external_calls: false;
}

export interface StudioExceptionRecord extends StudioException {
  exception_id: string;
}

export interface ExceptionQueueContract {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY";
  generated_at: string;
  source: ContractSource;
  summary: {
    total: number;
    open: number;
    high_risk: number;
    unassigned: number;
    entity_count: number;
  };
  risk_distribution: DistributionPoint[];
  status_distribution: DistributionPoint[];
  exceptions: StudioExceptionRecord[];
  notices: string[];
}

export interface EvidenceRecord {
  evidence_code: string;
  provenance_type: string;
  redaction_status: string;
  evidence_status: string;
  checksum_sha256: string;
}

export interface EvidenceBinderContract {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY";
  generated_at: string;
  source: ContractSource;
  summary: {
    total: number;
    available: number;
    checksum_count: number;
    synthetic_redaction_count: number;
    coverage_percent: number;
  };
  status_distribution: DistributionPoint[];
  evidence: EvidenceRecord[];
  notices: string[];
}

export interface InventoryWarehouse {
  warehouse_code: string;
  warehouse_name: string;
  entity_code: string;
  on_hand_lines: number;
  negative_lines: number;
}

export interface InventoryOnHandRecord {
  item_code: string;
  item_name: string;
  uom_code: string;
  warehouse_code: string;
  warehouse_name: string;
  location_code: string;
  entity_code: string;
  lot_serial_code: string;
  tracking_type: "None" | "Lot" | "Serial";
  quantity: string;
}

export interface InventoryMovementRecord {
  movement_number: string;
  movement_type: "Receipt" | "Delivery" | "Transfer" | "Adjustment";
  status: "Draft" | "Posted" | "Voided";
  movement_date: string;
  entity_code: string;
  from_location: string;
  to_location: string;
  line_count: number;
  quantity: string;
}

export interface InventoryExceptionRecord {
  exception_id: string;
  control_code: string;
  risk_rating: "critical" | "high" | "medium" | "low";
  item_code: string;
  location: string;
  quantity: string;
  description: string;
}

export interface InventoryCountRecord {
  count_number: string;
  status: "Draft" | "Counting" | "Submitted" | "Approved" | "Cancelled";
  count_date: string;
  entity_code: string;
  warehouse_code: string;
  location_code: string;
  line_count: number;
  counted_line_count: number;
  variance_line_count: number;
  adjustment_movement_number: string;
}

export interface InventoryReorderSignalRecord {
  signal_id: string;
  risk_rating: "high" | "medium";
  item_code: string;
  item_name: string;
  uom_code: string;
  warehouse_code: string;
  location_code: string;
  on_hand_quantity: string;
  minimum_quantity: string;
  target_quantity: string;
  suggested_quantity: string;
  lead_time_days: number;
}

export interface InventoryValuationRecord {
  valuation_number: string;
  movement_number: string;
  movement_type: "Receipt" | "Delivery" | "Adjustment";
  status: "Draft" | "Approved" | "Cancelled";
  valuation_date: string;
  entity_code: string;
  costing_method: "FIFO";
  currency_code: string;
  total_value: string;
  finance_entry_number: string;
  finance_entry_status: "" | "Draft" | "Validated" | "Voided";
}

export interface InventoryCostLayerRecord {
  layer_id: string;
  valuation_number: string;
  item_code: string;
  item_name: string;
  uom_code: string;
  lot_serial_code: string;
  entity_code: string;
  currency_code: string;
  original_quantity: string;
  remaining_quantity: string;
  original_value: string;
  remaining_value: string;
  layer_status: "Open" | "Closed";
}

export interface InventoryValuationReversalRecord {
  reversal_number: string;
  original_valuation_number: string;
  reversal_movement_number: string;
  original_movement_type: "Receipt" | "Delivery" | "Adjustment";
  reversal_movement_type: "Receipt" | "Delivery" | "Adjustment";
  status: "Draft" | "Approved" | "Cancelled";
  reversal_date: string;
  entity_code: string;
  currency_code: string;
  layer_effect: "Restore" | "Remove";
  layer_effect_count: number;
  total_value: string;
  finance_entry_number: string;
  finance_entry_status: "" | "Draft" | "Validated" | "Voided";
}

export interface InventoryControlContract {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY";
  generated_at: string;
  source: ContractSource;
  summary: {
    item_count: number;
    warehouse_count: number;
    location_count: number;
    movement_count: number;
    posted_movement_count: number;
    exception_count: number;
    count_session_count: number;
    reorder_signal_count: number;
    valuation_document_count: number;
    valuation_reversal_count: number;
    open_cost_layer_count: number;
    finance_draft_count: number;
  };
  warehouses: InventoryWarehouse[];
  on_hand: InventoryOnHandRecord[];
  movements: InventoryMovementRecord[];
  exceptions: InventoryExceptionRecord[];
  count_sessions: InventoryCountRecord[];
  reorder_signals: InventoryReorderSignalRecord[];
  valuations: InventoryValuationRecord[];
  valuation_reversals: InventoryValuationReversalRecord[];
  cost_layers: InventoryCostLayerRecord[];
  notices: string[];
}

export type StudioPage = "dashboard" | "exceptions" | "evidence" | "inventory";

export interface StudioOverview {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY";
  generated_at: string;
  source: {
    kind: "reconforge-enterprise-demo";
    local_first: true;
    external_calls: false;
  };
  workspace: {
    name: string;
    current_period: string;
    entity_count: number;
    evidence_count: number;
    close_task_count: number;
  };
  executive_brief: ExecutiveBrief;
  control_domains: ControlDomainHealth[];
  entity_health: EntityHealth[];
  metrics: StudioMetric[];
  risk_distribution: DistributionPoint[];
  status_distribution: DistributionPoint[];
  entities: StudioEntity[];
  close_tasks: CloseTask[];
  exceptions: StudioException[];
  notices: string[];
}

export interface AccessibilityPreferences {
  largerText: boolean;
  highContrast: boolean;
  colorSafe: boolean;
  reducedMotion: boolean;
  focusOutlines: boolean;
}
