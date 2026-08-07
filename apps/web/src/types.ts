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

export type RetailSettlementStatus = "matched" | "exception" | "unmatched_pos" | "unmatched_settlement" | "ambiguous";

export interface RetailSettlementDecision {
  batch_id: string;
  store_id: string;
  status: RetailSettlementStatus;
  settlement_ids: string[];
  expected_card_net: string;
  settlement_net: string | null;
  net_variance: string | null;
  currency: string;
  reason_code: string;
}

export interface RetailSettlementStudioContract {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_RETAIL_SETTLEMENT_UI_ONLY";
  generated_at: string;
  source: ContractSource;
  algorithm_version: string;
  decision_digest: string;
  artifact_digest: string;
  tolerance: string;
  currency: string;
  summary: {
    total: number;
    matched: number;
    exceptions: number;
    unmatched: number;
    ambiguous: number;
  };
  decisions: RetailSettlementDecision[];
  notices: string[];
}

export type BankStatementStatus = "matched" | "exception" | "unmatched_bank" | "unmatched_ledger" | "ambiguous";

export interface BankStatementDecision {
  bank_line_id: string;
  account_id: string;
  status: BankStatementStatus;
  ledger_record_ids: string[];
  amount_variance: string | null;
  days_variance: number | null;
  reason_code: string;
}

export interface BankStatementStudioContract {
  schema_version: 1;
  synthetic_data_only: true;
  synthetic_data_marker: "SYNTHETIC_BANK_STATEMENT_UI_ONLY";
  generated_at: string;
  source: ContractSource;
  algorithm_version: string;
  decision_digest: string;
  artifact_digest: string;
  tolerance: string;
  currency: string;
  date_window_days: number;
  summary: {
    total: number;
    matched: number;
    exceptions: number;
    unmatched: number;
    ambiguous: number;
  };
  decisions: BankStatementDecision[];
  notices: string[];
}

export type StudioPage = "dashboard" | "exceptions" | "evidence" | "inventory" | "retailSettlement" | "bankStatement" | "mapping" | "rules" | "live" | "adminAudit";

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

export interface LiveStudioMetric {
  metric_key: string;
  period_name: string;
  value_text: string;
  lineage: string;
  computed_at: string;
  name: string;
  description: string;
}

export interface LiveStudioContract {
  mode: "live";
  endpoint: "/api/v1/metrics/dashboard";
  fetched_at: string;
  generated_at: string | null;
  stale_after_seconds: number;
  stale: boolean;
  empty: boolean;
  metrics: LiveStudioMetric[];
}

export interface BrowserAdminSession {
  csrfToken: string;
  expiresAt: string;
  tenantId: string;
}

export interface AdminAuditEvent {
  source: "domain" | "ledger_control";
  event_id: string;
  sequence: number;
  occurred_at: string;
  action: string;
  object_type: string;
  actor_digest: string;
  object_digest: string;
  metadata_digest: string;
  previous_event_hash: string;
  event_hash: string;
  before_state_hash: string | null;
  after_state_hash: string | null;
}

export interface AdminAuditPage {
  events: AdminAuditEvent[];
  nextCursor: string | null;
}

export interface AdminAuditVerification {
  source: "domain" | "ledger_control";
  ok: boolean;
  checked_events: number;
  head_hash: string;
  issue_codes: string[];
}

export interface AdminSecurityAttention {
  severity: "medium" | "high";
  code: string;
  count: number;
}

export interface AdminSecuritySnapshot {
  asOf: string;
  posture: "attention_required" | "observed_no_count_based_attention";
  attention: AdminSecurityAttention[];
  sections: Array<{ id: "identity" | "sessions" | "integrations" | "policy" | "retention" | "audit"; values: Record<string, number | boolean | string> }>;
}

export interface AdminIdentityUser {
  id: string;
  username: string;
  displayName: string;
  disabled: boolean;
  lifecycleVersion: number;
  roles: string[];
  activeSessions: number;
  createdAt: string;
  disabledAt: string | null;
  stateDigest: string;
}

export interface AdminIdentitySession {
  id: string;
  userId: string;
  username: string;
  status: "active" | "expired" | "revoked";
  lifecycleVersion: number;
  createdAt: string;
  expiresAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
  revocationReasonCode: string | null;
  clientIpRecorded: boolean;
  userAgentRecorded: boolean;
  stateDigest: string;
}

export interface AdminSessionRevocation {
  session: AdminIdentitySession;
  transitioned: boolean;
  revokedCurrentSession: boolean;
  auditEventId: string | null;
}

export interface AdminIdentityUserStatusChange {
  user: AdminIdentityUser;
  transitioned: boolean;
  revokedSessions: number;
  auditEventId: string | null;
}

export interface AdminAccessPermission { name: string; description: string; activeRoleCount: number; stateDigest: string; }
export interface AdminAccessRole { id: string; name: string; description: string; active: boolean; lifecycleVersion: number; permissions: string[]; activeUserCount: number; createdAt: string; updatedAt: string; retiredAt: string | null; stateDigest: string; }
export interface AdminAccessRoleChange { role: AdminAccessRole; transitioned: boolean; revokedSessions: number; auditEventId: string | null; }
export interface AdminUserRoleAssignment { userId: string; username: string; lifecycleVersion: number; roleIds: string[]; roleNames: string[]; transitioned: boolean; revokedSessions: number; auditEventId: string | null; stateDigest: string; }
export interface AdminIntegration { kind: "federation_link" | "notification_route" | "scim_credential" | "service_account"; id: string; status: "active" | "disabled" | "expired"; lifecycleVersion: number; credentialCount: number; activeCredentialCount: number; createdAt: string; expiresAt: string | null; lastUsedAt: string | null; scopeDigest: string; stateDigest: string; }
export interface AdminRetentionPolicy { id: string; name: string; description: string; dataClassification: "public" | "internal" | "confidential" | "restricted"; durationDays: number; active: boolean; lifecycleVersion: number; createdAt: string; updatedAt: string; retiredAt: string | null; stateDigest: string; }
export interface AdminIntegrationDisable { integration: AdminIntegration; transitioned: boolean; revokedCredentials: number; auditEventId: string | null; }
export interface AdminRetentionPolicyChange { policy: AdminRetentionPolicy; transitioned: boolean; auditEventId: string | null; }
export interface AdminEvidenceRetentionChange { retentionVersion: number; retentionExtended: boolean; transitioned: boolean; auditEventId: string | null; stateDigest: string; }
