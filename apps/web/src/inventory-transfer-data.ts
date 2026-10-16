import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const transferRoot = "/api/v1/inventory-transfer";
export const transferRead = ["inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"];
export const transferPermissions: Record<string, string[]> = {
  create: [...transferRead, "inventory_transfer.manage", "inventory.manage"],
  "inverse-create": [...transferRead, "inventory_transfer.manage", "inventory.manage"],
  review: [...transferRead, "inventory_transfer.approve", "inventory.manage"],
  post: [...transferRead, "inventory_transfer.post", "inventory.post"],
  cancel: [...transferRead, "inventory_transfer.approve", "inventory.manage"],
};
export const transferObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const digest = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && value === value.trim() && !/[\x00-\x1f\x7f]/.test(value);
const exact = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
function invalid(): never { throw new Error("inventory_transfer_evidence_invalid"); }
export function transferCanonical(value: unknown, originals = false, key = ""): string {
  if (originals && (key.endsWith("_minor") || key.endsWith("_scaled")) && exact(value)) return value;
  if (originals && key === "exposed_amounts_minor" && Array.isArray(value)) return `[${value.map(part => { if (!exact(part)) invalid(); return part; }).join(",")}]`;
  if (Array.isArray(value)) return `[${value.map(part => transferCanonical(part, originals)).join(",")}]`;
  if (transferObject(value)) return `{${Object.keys(value).sort().map(name => `${JSON.stringify(name)}:${transferCanonical(value[name], originals, name)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
export async function transferDigest(value: unknown, originals = false): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(transferCanonical(value, originals)));
  return [...new Uint8Array(hash)].map(part => part.toString(16).padStart(2, "0")).join("");
}
async function seal(value: unknown, expected: unknown, originals = true) {
  if (!digest(expected) || await transferDigest(value, originals) !== expected) invalid();
}
function scoped(value: unknown, scope: FinanceScope): value is FinanceScope {
  return transferObject(value) && Object.keys(value).length === 3 && Object.entries(scope).every(([key, expected]) => value[key] === expected);
}
export interface TransferCost extends Record<string, unknown> {
  monetary_policy: { currency_code: string; currency_precision: number };
  remaining_quantity_scaled: string; remaining_value_minor: string; sources: Array<Record<string, unknown>>;
}
export interface TransferSource extends Record<string, unknown> {
  id: string; number: string; scope: FinanceScope; item_code: string; uom_id: string; quantity: string; quantity_scaled: string;
  quantity_precision: number; from_location: string; to_location: string; from_location_id: string; to_location_id: string;
  native_movement_id: string; source_digest: string; row_version: number; phase: number; creator_actor_id: string;
  reviewer_actor_id: string | null; poster_actor_id: string | null; cost_snapshot: TransferCost; review_cost_snapshot: TransferCost | null;
  review_cost_digest: string | null; native_response: Record<string, unknown>; original: Record<string, unknown> | null;
  command_request: Record<string, unknown>;
}
const policyFields = ["currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"];
function fields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!transferObject(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) invalid(); return value;
}
function boundedCorrection(value: unknown, maximumBytes = 262144, maximumNodes = 32768, nativeSpacing = false): void {
  const pending: Array<[unknown, number]> = [[value, 0]]; let nodes = 0, spacing = 0;
  while (pending.length) {
    const [part, depth] = pending.pop()!;
    if (++nodes > maximumNodes || depth > 32) invalid();
    if (Array.isArray(part)) { if (part.length > 1024) invalid(); spacing += Math.max(part.length - 1, 0); for (const child of part) pending.push([child, depth + 1]); }
    else if (transferObject(part)) { const count = Object.keys(part).length; if (count > 1024) invalid(); spacing += count + Math.max(count - 1, 0); for (const [key, child] of Object.entries(part)) { if (key.length > 160) invalid(); pending.push([child, depth + 1]); } }
    else if (!(part === null || typeof part === "boolean" || typeof part === "string" && part.length <= 262144 || typeof part === "number" && Number.isSafeInteger(part))) invalid();
  }
  // Native jsonb text adds one space after each object colon and collection
  // comma. Count structure, never punctuation inside retained string values.
  if (new TextEncoder().encode(transferCanonical(value, true)).length + (nativeSpacing ? spacing : 0) > maximumBytes) invalid();
}
interface CorrectionProtocols {
  remainder: boolean;
  sources: Map<string, string>;
  plans: Map<string, string>;
  history: Map<string, string>;
  events: Map<string, Map<number, { plan: string; original: string | null; direction: number }>>;
}
async function zeroConsumptionAdmissions(source: Record<string, unknown>, consumptions: Map<string, Record<string, unknown>>, scope: FinanceScope, tenantId: string, policy: Record<string, unknown>, v3: boolean, v4 = false): Promise<Map<string, Record<string, unknown>>> {
  const zero = [...consumptions.values()].filter(row => row.value_minor === "0"), result = new Map<string, Record<string, unknown>>();
  if (!zero.length) { if (Object.hasOwn(source, "restituted_consumption_admissions")) invalid(); return result; }
  if (!v3 || !Array.isArray(source.restituted_consumption_admissions) || source.restituted_consumption_admissions.length !== zero.length) invalid();
  const layer = source.layer as Record<string, unknown>;
  for (const [index, raw] of source.restituted_consumption_admissions.entries()) {
    boundedCorrection(raw, 262144, 32768, v4);
    const admission = fields(raw, ["consumption_id", "stock_order_id", "cost_admission_policy", "issue_plan", "valuation_document", "valuation_line", "posting_effect", "physical"]);
    const consumed = zero[index];
    if (admission.consumption_id !== consumed.id || !text(admission.stock_order_id) || admission.cost_admission_policy !== "partial-return-restituted-v1") invalid();
    const issue = fields(admission.issue_plan, ["schema_version", "preparer_actor_id", "preparer_username", "source_digest", "request", "allocations", "total_cost_minor", "policy_id", "inventory_account_id", "cogs_account_id", "entry_id", "entry_number", "journal_id", "currency_policy", "cost_admission_policy", "restitution_cost_snapshot"]);
    const request = fields(issue.request, ["posting_date", "period_id", "policy_code", "reason"]);
    const captured = fields(issue.currency_policy, ["currency_code", "precision", "rounding_policy", "registry_version", "registry_digest"]);
    if (issue.schema_version !== "stock-sales-issue-v2" || issue.cost_admission_policy !== admission.cost_admission_policy || !text(issue.preparer_actor_id) || !text(issue.preparer_username) || !digest(issue.source_digest)
        || !exact(issue.total_cost_minor) || !text(issue.policy_id) || !text(issue.inventory_account_id) || !text(issue.cogs_account_id) || issue.inventory_account_id === issue.cogs_account_id || !text(issue.journal_id)
        || !text(request.period_id) || !text(request.posting_date) || !text(request.policy_code) || !text(request.reason)
        || captured.currency_code !== policy.currency_code || captured.precision !== policy.currency_precision || captured.rounding_policy !== policy.currency_rounding_policy
        || captured.registry_version !== policy.currency_registry_version || captured.registry_digest !== policy.currency_registry_digest
        || issue.entry_number !== `SS1-${(await transferDigest([tenantId, admission.stock_order_id], true)).slice(0, 32).toUpperCase()}`
        || !Array.isArray(issue.allocations) || issue.allocations.length < 1 || issue.allocations.length > 32) invalid();
    // This is retained historical cost evidence, never a re-price using current
    // layers. The bounded original contains the earlier restitution population.
    const before = await cost(issue.restitution_cost_snapshot, scope, tenantId);
    if (before.schema_version !== "inventory-transfer-cost-v3" && !(v4 && before.schema_version === "inventory-transfer-cost-v4") || transferCanonical(before.monetary_policy) !== transferCanonical(policy)) invalid();
    const allocations = new Map<string, Record<string, unknown>>(); let totalQuantity = 0n, totalValue = 0n, needed = false;
    for (const rawAllocation of issue.allocations) {
      const allocation = fields(rawAllocation, ["cost_layer_id", "row_version", "remaining_quantity_scaled", "remaining_value_minor", "quantity_scaled", "value_minor"]);
      if (!text(allocation.cost_layer_id) || allocations.has(allocation.cost_layer_id) || typeof allocation.row_version !== "number" || !Number.isSafeInteger(allocation.row_version) || allocation.row_version < 1
          || !exact(allocation.remaining_quantity_scaled) || allocation.remaining_quantity_scaled === "0" || !exact(allocation.remaining_value_minor) || !exact(allocation.quantity_scaled) || allocation.quantity_scaled === "0" || !exact(allocation.value_minor)) invalid();
      const pool = before.sources.find(row => (row.layer as Record<string, unknown>).id === allocation.cost_layer_id);
      if (!pool || !transferObject(pool.layer)) invalid();
      const retainedLayer = pool.layer;
      if (["row_version", "remaining_quantity_scaled", "remaining_value_minor"].some(key => retainedLayer[key] !== allocation[key])) invalid();
      if (retainedLayer.workspace_id !== scope.workspace_id || retainedLayer.legal_entity_id !== scope.legal_entity_id
          || ["item_id", "uom_id", "quantity_precision"].some(key => retainedLayer[key] !== layer[key])) invalid();
      const q = BigInt(allocation.remaining_quantity_scaled), v = BigInt(allocation.remaining_value_minor), take = BigInt(allocation.quantity_scaled);
      if (take > q) invalid();
      let expected = v;
      if (take !== q) { expected = v * take / q; const rem = v * take % q; if (rem * 2n > q || rem * 2n === q && expected % 2n === 1n) expected += 1n; }
      if (BigInt(allocation.value_minor) !== expected) invalid();
      if (expected === 0n || take < q && expected === v) {
        const active = [...pool.partial_return_corrections as Record<string, unknown>[], ...(before.schema_version === "inventory-transfer-cost-v4" ? pool.monetary_return_corrections as Record<string, unknown>[] : [])].filter(row => Object.hasOwn(row, "allocation_policy"))
          .reduce((sum, row) => sum + BigInt(String((row.restoration as Record<string, unknown>).direction)) * BigInt(String((row.restoration as Record<string, unknown>).quantity_scaled)), 0n);
        if (active <= 0n) invalid(); needed = true;
      }
      allocations.set(allocation.cost_layer_id, allocation); totalQuantity += take; totalValue += expected;
    }
    const selected = allocations.get(String(layer.id));
    if (!needed || totalValue !== BigInt(issue.total_cost_minor) || !selected || selected.quantity_scaled !== consumed.quantity_scaled || selected.value_minor !== "0") invalid();
    if (!transferObject(admission.valuation_document) || !transferObject(admission.valuation_line)) invalid();
    const document = admission.valuation_document, line = admission.valuation_line;
    if (document.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => document[key] !== expected) || !text(document.id) || document.status !== "Approved"
        || document.total_value_minor !== issue.total_cost_minor || document.finance_entry_id !== issue.entry_id || document.policy_id !== issue.policy_id || document.period_id !== request.period_id || document.valuation_date !== request.posting_date || document.valuation_number !== issue.entry_number
        || policyFields.some(key => document[key] !== policy[key]) || line.tenant_id !== tenantId || line.id !== consumed.valuation_line_id || line.valuation_document_id !== document.id || line.flow_direction !== "Outbound" || line.line_number !== 1
        || line.item_id !== layer.item_id || line.uom_id !== layer.uom_id || line.quantity_precision !== layer.quantity_precision || !exact(line.quantity_scaled) || BigInt(line.quantity_scaled) !== totalQuantity || line.value_minor !== issue.total_cost_minor
        || line.inventory_account_id !== issue.inventory_account_id || line.offset_account_id !== issue.cogs_account_id) invalid();
    const physical = fields(admission.physical, ["head", "lines", "audit", "outbox"]);
    if (!transferObject(physical.head) || !Array.isArray(physical.lines) || physical.lines.length !== 1 || !transferObject(physical.lines[0]) || !Array.isArray(physical.audit) || physical.audit.length < 1 || physical.audit.length > 8 || !Array.isArray(physical.outbox) || physical.outbox.length < 1 || physical.outbox.length > 8) invalid();
    const movement = physical.head, detail = physical.lines[0];
    if (movement.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => movement[key] !== expected) || movement.id !== document.movement_id || movement.source_reference !== admission.stock_order_id || movement.movement_number !== issue.entry_number
        || movement.status !== "Posted" || movement.source_type !== "Generated" || movement.movement_type !== "Delivery" || movement.period_id !== request.period_id || movement.movement_date !== request.posting_date
        || detail.tenant_id !== tenantId || detail.movement_id !== movement.id || detail.id !== line.movement_line_id || detail.line_number !== 1 || detail.item_id !== layer.item_id || detail.uom_id !== layer.uom_id || detail.quantity_precision !== layer.quantity_precision
        || detail.inventory_lot_id !== null || detail.quantity_scaled !== line.quantity_scaled || !text(detail.from_location_id) || detail.to_location_id !== null) invalid();
    if (issue.total_cost_minor === "0") {
      if (issue.entry_id !== null || admission.posting_effect !== null) invalid();
    } else {
      if (!text(issue.entry_id) || !transferObject(admission.posting_effect)) invalid();
      const effect = admission.posting_effect;
      if (!text(effect.id) || effect.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => effect[key] !== expected) || effect.entry_id !== issue.entry_id || effect.source_kind !== "Manual" || effect.source_id !== issue.entry_id || effect.purpose !== "operational_posting" || effect.reverses_effect_id !== null
          || effect.validation_contract_version !== "finance-entry-review-v1" || !digest(effect.validation_digest) || policyFields.some(key => effect[key] !== policy[key])) invalid();
      const snapshot = fields(effect.snapshot_json, ["schema_version", "entry", "lines"]);
      if (snapshot.schema_version !== "finance-entry-review-v1" || !transferObject(snapshot.entry) || !Array.isArray(snapshot.lines) || snapshot.lines.length !== 2) invalid();
      const head = snapshot.entry;
      if (head.id !== issue.entry_id || Object.entries(scope).some(([key, expected]) => head[key] !== expected) || head.journal_id !== issue.journal_id || head.period_id !== request.period_id || head.posting_date !== request.posting_date || head.entry_number !== issue.entry_number
          || head.external_reference !== admission.stock_order_id || head.source_type !== "Manual" || head.preparer_actor_id !== issue.preparer_actor_id || head.reverses_posting_id !== null || policyFields.some(key => head[key] !== policy[key])) invalid();
      for (const [position, rawLine] of snapshot.lines.entries()) {
        const value = fields(rawLine, ["line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions"]);
        if (value.line_number !== position + 1 || value.account_id !== (position === 0 ? issue.cogs_account_id : issue.inventory_account_id) || value.debit_minor !== (position === 0 ? issue.total_cost_minor : "0") || value.credit_minor !== (position === 1 ? issue.total_cost_minor : "0") || !transferObject(value.dimensions)) invalid();
      }
      await seal(snapshot, effect.validation_digest);
    }
    result.set(String(consumed.id), admission);
  }
  return result;
}
async function corrections(source: Record<string, unknown>, scope: FinanceScope, tenantId: string, policy: Record<string, unknown>, seen: Set<string>, v3: boolean, protocols: CorrectionProtocols, v4 = false): Promise<[bigint, bigint]> {
  fields(source, ["layer", "valuation_document", "valuation_line", "receipt_plan", "receipt_link", "receipt_review", "finance_entry", "finance_lines", "posting_effect", "receipt_native", "valuation_input", "consumptions", "exposed_amounts_minor", "partial_return_corrections", ...(v4 ? ["monetary_return_corrections"] : []), ...(v3 && Object.hasOwn(source, "restituted_consumption_admissions") ? ["restituted_consumption_admissions"] : [])]);
  const layer = source.layer as Record<string, unknown>, valuation = source.valuation_line as Record<string, unknown>;
  const limit = v4 ? 256 : 200;
  if (!Array.isArray(source.partial_return_corrections) || source.partial_return_corrections.length > limit || v4 && (!Array.isArray(source.monetary_return_corrections) || source.monetary_return_corrections.length + source.partial_return_corrections.length > limit) || !Array.isArray(source.consumptions) || source.consumptions.length > 200
      || !exact(layer.original_quantity_scaled) || layer.original_quantity_scaled === "0" || !exact(layer.original_value_minor) || layer.original_value_minor === "0") invalid();
  let quantity = 0n, value = 0n, consumedQuantity = 0n, consumedValue = 0n;
  const consumptions = new Map<string, Record<string, unknown>>(), net = new Map<string, [bigint, bigint]>();
  const sourceProtocols = new Map<string, boolean>(), sequences = new Map<string, { sequence: number; position: number; plan: string }>();
  let previousSource = "";
  for (const consumed of source.consumptions) {
    if (!transferObject(consumed) || !text(consumed.id) || consumptions.has(consumed.id) || consumed.tenant_id !== tenantId || consumed.cost_layer_id !== layer.id
        || !exact(consumed.quantity_scaled) || consumed.quantity_scaled === "0" || !exact(consumed.value_minor) || !v3 && consumed.value_minor === "0") invalid();
    consumptions.set(consumed.id, consumed); consumedQuantity += BigInt(consumed.quantity_scaled); consumedValue += BigInt(consumed.value_minor);
  }
  const zeroAdmissions = await zeroConsumptionAdmissions(source, consumptions, scope, tenantId, policy, v3, v4);
  if (zeroAdmissions.size) protocols.remainder = true;
  const debitExposures: string[] = [], creditExposures: string[] = [];
  const rows = [...source.partial_return_corrections.map(raw => ({ raw, monetary: false })), ...(v4 ? (source.monetary_return_corrections as unknown[]).map(raw => ({ raw, monetary: true })) : [])];
  if (v4) boundedCorrection(rows.map(({ raw }) => raw), 1048576, 100000, true);
  for (const { raw, monetary } of rows) {
    boundedCorrection(raw, 262144, 32768, v4);
    const remainder = monetary || v3 && transferObject(raw) && Object.hasOwn(raw, "allocation_policy");
    const correction = fields(raw, ["restoration", "source", "plan", "entry", "effect", "lines", "dimensions", "physical", ...(remainder ? ["history_sequence", "allocation_policy", ...(monetary ? [] : ["allocation_witness"])] : [])]);
    const restored = fields(correction.restoration, ["tenant_id", ...(monetary ? [...Object.keys(scope), "origin_id", "before_quantity_scaled", "before_value_minor"] : ["source_id", "offset_quantity_scaled", "original_cogs_effect_id"]), "plan_id", "position", "original_consumption_id", "original_valuation_line_id", "cost_layer_id", "quantity_scaled", "value_minor", "direction", "physical_movement_id", "correction_effect_id", "original_restoration_plan_id", "consumption_count_at_restore"]);
    const factual = monetary || remainder && transferObject(correction.source) && Object.hasOwn(correction.source, "original_cost_minor");
    const original = fields(correction.source, ["id", ...(monetary ? ["source_digest", "stock_order_id"] : ["source_fingerprint"]), ...Object.keys(scope), "item_id", "uom_id", "quantity_precision", "location_id", "original_cogs_effect_id", ...(factual ? ["original_cost_minor", ...(monetary ? [] : ["cost_admission_digest"])] : [])]);
    if (factual && (!exact(original.original_cost_minor) || !monetary && !digest(original.cost_admission_digest))) invalid();
    const absentOriginalCost = factual && original.original_cost_minor === "0";
    const plan = fields(correction.plan, ["id", "source_id", "operation", "phase", "plan_digest", ...(remainder ? [monetary ? "functional_cost_minor" : "cogs_restored_minor"] : [])]);
    const totalCost = plan[monetary ? "functional_cost_minor" : "cogs_restored_minor"];
    if (!Number.isSafeInteger(restored.position) || Number(restored.position) < 1 || Number(restored.position) > 32 || ![1, -1].includes(Number(restored.direction)) || typeof restored.direction !== "number"
        || !Number.isSafeInteger(restored.consumption_count_at_restore) || Number(restored.consumption_count_at_restore) < 1 || Number(restored.consumption_count_at_restore) > 200
        || restored.tenant_id !== tenantId || restored.cost_layer_id !== layer.id || restored[monetary ? "origin_id" : "source_id"] !== original.id || restored.plan_id !== plan.id || plan.source_id !== original.id
        || monetary && Object.entries(scope).some(([key, expected]) => restored[key] !== expected)
        || !text(plan.id) || !new RegExp(`^${monetary ? restored.direction === 1 ? "CR3" : "CR3R" : restored.direction === 1 ? "CR2" : "CR2R"}-[a-f0-9]{32}$`).test(plan.id) || plan.phase !== 2
        || plan.operation !== (restored.direction === 1 ? "Return" : "ReverseReturn") || !digest(plan.plan_digest) || !digest(original[monetary ? "source_digest" : "source_fingerprint"])
        || !text(original.id) || !new RegExp(`^${monetary ? "MSO" : "CRS2"}-[a-f0-9]{32}$`).test(original.id) || monetary && !text(original.stock_order_id) || Object.entries(scope).some(([key, expected]) => original[key] !== expected)
        || original.item_id !== layer.item_id || original.uom_id !== layer.uom_id || original.quantity_precision !== layer.quantity_precision || !text(original.location_id)
        || !monetary && restored.original_cogs_effect_id !== original.original_cogs_effect_id || (absentOriginalCost ? original.original_cogs_effect_id !== null : !text(original.original_cogs_effect_id))
        || !monetary && !exact(restored.offset_quantity_scaled) || !exact(restored.quantity_scaled) || restored.quantity_scaled === "0" || !exact(restored.value_minor) || !remainder && restored.value_minor === "0") invalid();
    if (v3) {
      if (String(original.id) < previousSource || sourceProtocols.has(String(original.id)) && sourceProtocols.get(String(original.id)) !== remainder) invalid();
      previousSource = String(original.id); sourceProtocols.set(previousSource, remainder);
      const sourcePin = transferCanonical({ original, remainder });
      if (protocols.sources.has(previousSource) && protocols.sources.get(previousSource) !== sourcePin) invalid();
      protocols.sources.set(previousSource, sourcePin);
    }
    const key = `${plan.id}:${restored.position}`;
    if (seen.has(key) || seen.size >= limit) invalid(); seen.add(key);
    const consumed = consumptions.get(String(restored.original_consumption_id));
    if (!consumed || consumed.valuation_line_id !== restored.original_valuation_line_id || (monetary ? 0n : BigInt(String(restored.offset_quantity_scaled))) + BigInt(restored.quantity_scaled) > BigInt(String(consumed.quantity_scaled)) || BigInt(restored.value_minor) > BigInt(String(consumed.value_minor))) invalid();
    if (monetary && BigInt(String(consumed.value_minor)) > BigInt(String(original.original_cost_minor))) invalid();
    if (consumed.value_minor === "0") {
      const admission = zeroAdmissions.get(String(consumed.id));
      if (!factual || !admission || !transferObject(admission.issue_plan) || original.original_cost_minor !== admission.issue_plan.total_cost_minor
          || monetary && original.stock_order_id !== admission.stock_order_id
          || (admission.posting_effect === null ? !absentOriginalCost : !transferObject(admission.posting_effect) || admission.posting_effect.id !== original.original_cogs_effect_id)) invalid();
    } else if (absentOriginalCost) invalid();
    const previous = net.get(String(consumed.id)) ?? [0n, 0n];
    if (remainder) {
      protocols.remainder = true;
      const witness = monetary ? { before_quantity_scaled: restored.before_quantity_scaled, before_value_minor: restored.before_value_minor } : fields(correction.allocation_witness, ["before_quantity_scaled", "before_value_minor"]);
      if (correction.allocation_policy !== (monetary ? "remaining-dual-currency-v1" : "remaining-original-v1") || typeof correction.history_sequence !== "number" || !Number.isSafeInteger(correction.history_sequence) || correction.history_sequence < 1 || correction.history_sequence > 256
          || !exact(witness.before_quantity_scaled) || witness.before_quantity_scaled === "0" || !exact(witness.before_value_minor) || !exact(totalCost) || BigInt(totalCost) < BigInt(restored.value_minor)) invalid();
      if (monetary && BigInt(totalCost) > BigInt(String(original.original_cost_minor))) invalid();
      const prior = sequences.get(String(original.id));
      if (prior && (correction.history_sequence < prior.sequence || correction.history_sequence === prior.sequence && (plan.id !== prior.plan || Number(restored.position) <= prior.position))) invalid();
      sequences.set(String(original.id), { sequence: correction.history_sequence, position: Number(restored.position), plan: String(plan.id) });
      const planPin = transferCanonical({ plan, sequence: correction.history_sequence, ...(monetary ? { entry: correction.entry, effect: correction.effect, lines: correction.lines, dimensions: correction.dimensions, physical: correction.physical } : {}) });
      const historyKey = `${original.id}:${correction.history_sequence}`;
      if (protocols.plans.has(String(plan.id)) && protocols.plans.get(String(plan.id)) !== planPin
          || protocols.history.has(historyKey) && protocols.history.get(historyKey) !== plan.id) invalid();
      protocols.plans.set(String(plan.id), planPin); protocols.history.set(historyKey, String(plan.id));
      const beforeQ = BigInt(witness.before_quantity_scaled), beforeV = BigInt(witness.before_value_minor), take = BigInt(restored.quantity_scaled);
      const originalQ = BigInt(String(consumed.quantity_scaled)), originalV = BigInt(String(consumed.value_minor));
      if (beforeQ > originalQ || beforeV > originalV || take > beforeQ || !monetary && BigInt(String(restored.offset_quantity_scaled)) !== originalQ - beforeQ) invalid();
      if (restored.direction === 1) {
        if (beforeQ !== originalQ - previous[0] || beforeV !== originalV - previous[1]) invalid();
        let expected = beforeV;
        if (take !== beforeQ) {
          expected = beforeV * take / beforeQ;
          const residual = beforeV * take % beforeQ;
          if (residual * 2n > beforeQ || residual * 2n === beforeQ && expected % 2n === 1n) expected += 1n;
        }
        if (BigInt(restored.value_minor) !== expected) invalid();
      } else if (previous[0] !== originalQ - beforeQ + take || previous[1] !== originalV - beforeV + BigInt(restored.value_minor)) invalid();
    } else if (BigInt(restored.value_minor) * BigInt(String(consumed.quantity_scaled)) !== BigInt(String(consumed.value_minor)) * BigInt(restored.quantity_scaled)) invalid();
    const delta: [bigint, bigint] = [BigInt(restored.direction) * BigInt(restored.quantity_scaled), BigInt(restored.direction) * BigInt(restored.value_minor)];
    quantity += delta[0]; value += delta[1]; net.set(String(consumed.id), [previous[0] + delta[0], previous[1] + delta[1]]);
    if (restored.direction === 1 ? restored.original_restoration_plan_id !== null : !text(restored.original_restoration_plan_id) || !new RegExp(`^${monetary ? "CR3" : "CR2"}-[a-f0-9]{32}$`).test(restored.original_restoration_plan_id)) invalid();
    if (remainder) {
      const events = protocols.events.get(String(original.id)) ?? new Map();
      const event = { plan: String(plan.id), original: restored.original_restoration_plan_id as string | null, direction: Number(restored.direction) };
      const sequence = correction.history_sequence as number;
      if (events.has(sequence) && transferCanonical(events.get(sequence)) !== transferCanonical(event)) invalid();
      events.set(sequence, event); protocols.events.set(String(original.id), events);
    }
    const zeroCost = remainder && totalCost === "0";
    if (zeroCost) {
      if (restored.correction_effect_id !== null || correction.entry !== null || correction.effect !== null || !Array.isArray(correction.lines) || correction.lines.length || !Array.isArray(correction.dimensions) || correction.dimensions.length) invalid();
    } else {
      if (!transferObject(correction.entry) || !transferObject(correction.effect) || !Array.isArray(correction.lines) || correction.lines.length !== 2 || !Array.isArray(correction.dimensions) || correction.dimensions.length > 200) invalid();
      const entry = correction.entry, effect = correction.effect;
      if (entry.tenant_id !== tenantId || entry.workspace_id !== scope.workspace_id || entry.status !== "Validated" || !text(entry.id) || entry.id !== effect.entry_id || restored.correction_effect_id !== effect.id
          || !text(effect.id) || effect.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => effect[key] !== expected)
          || policyFields.some(key => entry[key] !== policy[key] || effect[key] !== policy[key]) || entry.entry_number !== `${plan.id.toUpperCase()}-C`
          || entry.source_type !== (restored.direction === 1 ? "Manual" : "Generated") || effect.source_kind !== (restored.direction === 1 ? "Manual" : "Reversal")
          || effect.source_id !== (restored.direction === 1 ? entry.id : effect.reverses_effect_id) || effect.purpose !== "operational_posting"
          || (restored.direction === 1 ? entry.external_reference !== plan.id || effect.reverses_effect_id !== null || entry.reverses_posting_id !== null : !text(effect.reverses_effect_id) || entry.external_reference !== effect.reverses_effect_id || entry.reverses_posting_id !== effect.reverses_effect_id)
          || !digest(entry.validation_digest) || entry.validation_digest !== effect.validation_digest || entry.validation_contract_version !== "finance-entry-review-v1" || effect.validation_contract_version !== entry.validation_contract_version
          || !text(entry.preparer_actor_id) || !text(entry.validator_actor_id) || !text(effect.posted_actor_id) || new Set([entry.preparer_actor_id, entry.validator_actor_id, effect.posted_actor_id]).size !== 3
          || !exact(entry.total_debit_minor) || entry.total_debit_minor === "0" || entry.total_debit_minor !== entry.total_credit_minor || BigInt(entry.total_debit_minor) < BigInt(restored.value_minor) || remainder && entry.total_debit_minor !== totalCost) invalid();
      const lineIds = new Set<string>(), dimensions = new Map<string, Record<string, string>>(); let debit = 0n, credit = 0n;
      for (const [index, line] of correction.lines.entries()) {
        if (!transferObject(line) || line.tenant_id !== tenantId || line.entry_id !== entry.id || !text(line.id) || lineIds.has(line.id) || line.line_number !== index + 1 || !text(line.account_id) || line.currency_code !== policy.currency_code
            || !exact(line.debit_minor) || !exact(line.credit_minor) || (line.debit_minor === "0") === (line.credit_minor === "0")) invalid();
        lineIds.add(line.id); debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor); dimensions.set(line.id, Object.create(null) as Record<string, string>);
      }
      if (debit !== BigInt(entry.total_debit_minor) || credit !== debit || !text(valuation.inventory_account_id)) invalid();
      const inventory = correction.lines.filter(line => (line as Record<string, unknown>).account_id === valuation.inventory_account_id);
      if (inventory.length !== 1 || inventory[0][restored.direction === 1 ? "debit_minor" : "credit_minor"] !== entry.total_debit_minor) invalid();
      for (const rawDimension of correction.dimensions) {
        const dimension = fields(rawDimension, ["tenant_id", "entry_line_id", "dimension_id", "dimension_value_id"]);
        if (dimension.tenant_id !== tenantId || !text(dimension.entry_line_id) || !dimensions.has(dimension.entry_line_id) || !text(dimension.dimension_id) || !text(dimension.dimension_value_id)) invalid();
        const bag = dimensions.get(dimension.entry_line_id)!; if (Object.hasOwn(bag, dimension.dimension_id)) invalid(); bag[dimension.dimension_id] = dimension.dimension_value_id;
      }
      const snapshot = fields(effect.snapshot_json, ["schema_version", "entry", "lines"]);
      const expectedHeader = Object.fromEntries(["id", "workspace_id", "journal_id", "period_id", "entry_number", "posting_date", "description", "external_reference", "source_type", ...policyFields, "preparer_actor_id", "reverses_posting_id"].map(key => [key, entry[key]]));
      Object.assign(expectedHeader, { organization_id: scope.organization_id, legal_entity_id: scope.legal_entity_id });
      const expectedLines = correction.lines.map(line => ({ line_number: line.line_number, account_id: line.account_id, description: line.description, debit_minor: line.debit_minor, credit_minor: line.credit_minor, dimensions: dimensions.get(line.id) }));
      if (snapshot.schema_version !== "finance-entry-review-v1") invalid();
      if (transferCanonical(snapshot.entry, true) !== transferCanonical(expectedHeader, true)) invalid();
      if (transferCanonical(snapshot.lines, true) !== transferCanonical(expectedLines, true)) invalid();
      await seal(snapshot, entry.validation_digest);
      debitExposures.push(entry.total_debit_minor); creditExposures.push(entry.total_credit_minor);
    }
    const physical = fields(correction.physical, ["head", "lines", "audit", "outbox"]);
    if (!transferObject(physical.head) || !Array.isArray(physical.lines) || physical.lines.length !== 1 || !Array.isArray(physical.audit) || physical.audit.length < 1 || physical.audit.length > 8 || !Array.isArray(physical.outbox) || physical.outbox.length < 1 || physical.outbox.length > 8) invalid();
    const movement = physical.head, detail = physical.lines[0];
    if (!transferObject(detail) || movement.tenant_id !== tenantId || movement.id !== restored.physical_movement_id || movement.source_reference !== plan.id || movement.movement_number !== plan.id.toUpperCase() || movement.status !== "Posted" || movement.source_type !== "Generated"
        || movement.movement_type !== (restored.direction === 1 ? "Receipt" : "Delivery") || Object.entries(scope).some(([key, expected]) => movement[key] !== expected)
        || detail.tenant_id !== tenantId || detail.movement_id !== movement.id || detail.line_number !== 1 || detail.item_id !== original.item_id || detail.uom_id !== original.uom_id || detail.quantity_precision !== original.quantity_precision || detail.inventory_lot_id !== null
        || !exact(detail.quantity_scaled) || BigInt(detail.quantity_scaled) < BigInt(restored.quantity_scaled) || detail.from_location_id !== (restored.direction === -1 ? original.location_id : null) || detail.to_location_id !== (restored.direction === 1 ? original.location_id : null)) invalid();
  }
  for (const [id, [netQuantity, netValue]] of net) {
    const original = consumptions.get(id)!;
    if (netQuantity < 0n || netValue < 0n || netQuantity > BigInt(String(original.quantity_scaled)) || netValue > BigInt(String(original.value_minor))) invalid();
  }
  const originals = new Map(rows.map(({ raw }) => { const row = raw as Record<string, unknown>, restored = row.restoration as Record<string, unknown>; return [`${restored.plan_id}:${restored.position}`, row]; }));
  const reversed = new Set<string>();
  for (const { raw, monetary } of rows) {
    const row = raw as Record<string, unknown>, restored = row.restoration as Record<string, unknown>;
    if (restored.direction === -1) {
      const key = `${restored.original_restoration_plan_id}:${restored.position}`, previous = originals.get(key);
      if (!previous || !transferObject(previous.restoration) || previous.restoration.direction !== 1 || reversed.has(key)
          || (row.effect === null ? previous.effect !== null : !transferObject(row.effect) || !transferObject(previous.effect) || row.effect.reverses_effect_id !== previous.effect.id)
          || [monetary ? "origin_id" : "source_id", "cost_layer_id", "original_consumption_id", "original_valuation_line_id", ...(monetary ? ["before_quantity_scaled", "before_value_minor"] : ["offset_quantity_scaled", "original_cogs_effect_id"]), "quantity_scaled", "value_minor"].some(name => restored[name] !== (previous.restoration as Record<string, unknown>)[name])) invalid();
      const costField = monetary ? "functional_cost_minor" : "cogs_restored_minor";
      if (Object.hasOwn(row, "allocation_policy") && (previous.allocation_policy !== row.allocation_policy || !monetary && transferCanonical(previous.allocation_witness) !== transferCanonical(row.allocation_witness)
          || !transferObject(row.plan) || !transferObject(previous.plan) || row.plan[costField] !== previous.plan[costField])) invalid();
      reversed.add(key);
    }
  }
  if (BigInt(layer.original_quantity_scaled) - consumedQuantity + quantity !== BigInt(String(layer.remaining_quantity_scaled)) || BigInt(layer.original_value_minor) - consumedValue + value !== BigInt(String(layer.remaining_value_minor))) invalid();
  if (!Array.isArray(source.exposed_amounts_minor) || source.exposed_amounts_minor.length !== 11 + debitExposures.length * 2 || transferCanonical(source.exposed_amounts_minor.slice(11)) !== transferCanonical([...debitExposures, ...creditExposures])) invalid();
  return [quantity, value];
}
async function cost(value: unknown, scope: FinanceScope, tenantId: string): Promise<TransferCost> {
  const v4 = transferObject(value) && value.schema_version === "inventory-transfer-cost-v4";
  const v3 = transferObject(value) && value.schema_version === "inventory-transfer-cost-v3" || v4;
  const v2 = transferObject(value) && value.schema_version === "inventory-transfer-cost-v2" || v3;
  if (!transferObject(value) || value.schema_version !== "inventory-transfer-cost-v1" && !v2 || !transferObject(value.monetary_policy)
      || !/^[A-Z]{3}$/.test(String(value.monetary_policy.currency_code)) || !Number.isInteger(value.monetary_policy.currency_precision)
      || Number(value.monetary_policy.currency_precision) < 0 || Number(value.monetary_policy.currency_precision) > 8
      || !exact(value.remaining_quantity_scaled) || !exact(value.remaining_value_minor) || !Array.isArray(value.sources)
      || value.sources.length < 1 || value.sources.length > 32) invalid();
  if (v2) { fields(value, ["schema_version", "monetary_policy", "remaining_quantity_scaled", "remaining_value_minor", "sources"]); const captured = fields(value.monetary_policy, policyFields); if (typeof captured.currency_code !== "string" || captured.currency_rounding_policy !== "ROUND_HALF_UP" || !text(captured.currency_registry_version) || !digest(captured.currency_registry_digest)) invalid(); }
  const ids = new Set<string>(), seenCorrections = new Set<string>(); let quantity = 0n, minor = 0n;
  const protocols: CorrectionProtocols = { remainder: false, sources: new Map(), plans: new Map(), history: new Map(), events: new Map() };
  for (const source of value.sources) {
    if (transferObject(source) && (!v2 && (Object.hasOwn(source, "partial_return_corrections") || Object.hasOwn(source, "restituted_consumption_admissions")) || !v4 && Object.hasOwn(source, "monetary_return_corrections"))) invalid();
    if (!transferObject(source) || !transferObject(source.layer) || source.layer.tenant_id !== tenantId || !text(source.layer.id) || ids.has(source.layer.id)
        || !transferObject(source.receipt_plan) || source.receipt_plan.operation !== "Receipt" || !transferObject(source.receipt_plan.scope)
        || Object.entries(scope).some(([key, expected]) => (source.receipt_plan as Record<string, Record<string, unknown>>).scope[key] !== expected)
        || !transferObject(source.receipt_link) || source.receipt_link.cost_layer_id !== source.layer.id
        || source.receipt_link.plan_id !== source.receipt_plan.plan_id || !transferObject(source.valuation_document)
        || source.valuation_document.status !== "Approved" || !transferObject(source.valuation_line)
        || source.valuation_line.flow_direction !== "Inbound" || source.valuation_line.id !== source.layer.source_valuation_line_id
        || !transferObject(source.finance_entry) || source.finance_entry.status !== "Validated" || !transferObject(source.posting_effect)
        || source.posting_effect.entry_id !== source.finance_entry.id || source.posting_effect.source_id !== source.receipt_plan.plan_id
        || !Array.isArray(source.finance_lines) || source.finance_lines.length !== 2 || !Array.isArray(source.exposed_amounts_minor)
        || !source.exposed_amounts_minor.every(exact) || !exact(source.layer.remaining_quantity_scaled) || !exact(source.layer.remaining_value_minor)) invalid();
    if (transferCanonical(source.receipt_plan.currency_policy) !== transferCanonical(value.monetary_policy)) invalid();
    if (v2) await corrections(source, scope, tenantId, value.monetary_policy, seenCorrections, v3, protocols, v4);
    ids.add(source.layer.id); quantity += BigInt(source.layer.remaining_quantity_scaled); minor += BigInt(source.layer.remaining_value_minor);
  }
  // Native v4 may be selected by a monetary Stock consumption before any
  // return exists. Its two closed correction arrays can both be empty.
  if (quantity !== BigInt(value.remaining_quantity_scaled) || minor !== BigInt(value.remaining_value_minor) || !v4 && (v2 && !seenCorrections.size || v3 && !protocols.remainder)) invalid();
  // The visible correction pool cannot prove omitted cash events. It can still
  // refuse an inverse that contradicts a later active Return on another layer.
  for (const events of protocols.events.values()) {
    const active: string[] = [];
    for (const [, event] of [...events].sort(([left], [right]) => left - right)) {
      if (event.direction === 1) active.push(event.plan);
      else if (active.pop() !== event.original) invalid();
    }
  }
  return value as TransferCost;
}
export async function parseTransfer(value: unknown, scope: FinanceScope, tenantId: string): Promise<TransferSource> {
  if (!transferObject(value) || value.schema_version !== "inventory-transfer-v1" || !/^IT1-S-[A-F0-9]{32}$/.test(String(value.id))
      || !scoped(value.scope, scope) || !text(value.number) || !text(value.creator_actor_id) || !digest(value.source_digest)
      || ![0, 1, 2, 3].includes(Number(value.phase)) || !Number.isInteger(value.phase) || !Number.isInteger(value.row_version)
      || Number(value.row_version) < 1 || Number(value.row_version) > 3 || !exact(value.quantity_scaled) || value.quantity_scaled === "0"
      || !Number.isInteger(value.quantity_precision) || Number(value.quantity_precision) < 0 || Number(value.quantity_precision) > 6
      || !text(value.item_code) || !text(value.uom_id) || !text(value.native_movement_id) || !text(value.from_location_id)
      || !text(value.to_location_id) || value.from_location_id === value.to_location_id || !transferObject(value.command_request)
      || !transferObject(value.native_response) || !transferObject(value.native_response.head) || !Array.isArray(value.native_response.lines)
      || value.native_response.lines.length !== 1) invalid();
  const dynamic = ["source_digest", "phase", "row_version", "reviewer_actor_id", "poster_actor_id", "review_cost_snapshot", "review_cost_digest", "claim", "release", "native_response"];
  for (const candidate of [value.cost_snapshot, value.review_cost_snapshot]) if (transferObject(candidate) && ["inventory-transfer-cost-v2", "inventory-transfer-cost-v3", "inventory-transfer-cost-v4"].includes(String(candidate.schema_version))) boundedCorrection(candidate, 4194304, 100000, candidate.schema_version === "inventory-transfer-cost-v4");
  await seal(Object.fromEntries(Object.entries(value).filter(([key]) => !dynamic.includes(key))), value.source_digest);
  const originalCost = await cost(value.cost_snapshot, scope, tenantId);
  if (value.phase === 0 && value.row_version !== 1 || value.phase === 1 && value.row_version !== 2
      || value.phase === 2 && value.row_version !== 3 || value.phase === 3 && value.row_version !== (value.reviewer_actor_id === null ? 2 : 3)) invalid();
  if (value.reviewer_actor_id === null) {
    if (![0, 3].includes(Number(value.phase)) || value.review_cost_snapshot !== null || value.review_cost_digest !== null || value.claim !== null || value.release !== null) invalid();
  } else {
    if (value.phase === 0 || !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.creator_actor_id || !digest(value.review_cost_digest)) invalid();
    const reviewed = await cost(value.review_cost_snapshot, scope, tenantId);
    if (transferCanonical(reviewed.monetary_policy) !== transferCanonical(originalCost.monetary_policy)) invalid();
    await seal(reviewed, value.review_cost_digest);
    if (!transferObject(value.claim) || !/^IT1-K-[A-F0-9]{32}$/.test(String(value.claim.id)) || value.claim.tenant_id !== tenantId
        || Object.entries(scope).some(([key, expected]) => (value.claim as Record<string, unknown>)[key] !== expected)
        || value.claim.transfer_id !== value.id || value.claim.quantity_scaled !== value.quantity_scaled
        || value.claim.location_id !== value.from_location_id || value.claim.item_id !== value.item_id || value.claim.uom_id !== value.uom_id
        || value.claim.quantity_precision !== value.quantity_precision || value.claim.created_version !== 2
        || value.claim.state !== (value.phase === 2 ? "Posted" : value.phase === 3 ? "Released" : "Active")) invalid();
    if (value.phase === 1 ? value.release !== null : !transferObject(value.release) || !/^IT1-R-[A-F0-9]{32}$/.test(String(value.release.id))
        || value.release.tenant_id !== tenantId || value.release.transfer_id !== value.id || value.release.created_version !== 3
        || Object.entries(scope).some(([key, expected]) => (value.release as Record<string, unknown>)[key] !== expected) || value.release.claim_id !== value.claim.id
        || value.release.purpose !== (value.phase === 2 ? "Post" : "Cancel") || value.release.target_movement_id !== (value.phase === 2 ? value.native_movement_id : null)) invalid();
  }
  const head = value.native_response.head, line = value.native_response.lines[0];
  if (!transferObject(line) || line.tenant_id !== tenantId || line.movement_id !== value.native_movement_id || !text(line.id)
      || head.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => head[key] !== expected)
      || head.id !== value.native_movement_id || head.source_reference !== value.id || head.movement_type !== "Transfer"
      || head.source_type !== "Generated" || head.created_by !== value.creator_actor_id || head.status !== (value.phase === 2 ? "Posted" : "Draft")
      || line.item_id !== value.item_id || line.uom_id !== value.uom_id || line.quantity_scaled !== value.quantity_scaled
      || head.movement_number !== `IT1-${String(value.id).slice(-32)}` || head.period_id !== value.period_id || head.movement_date !== value.posting_date
      || head.row_version !== (value.phase === 2 ? 2 : 1) || line.inventory_lot_id !== null || line.line_number !== 1
      || line.quantity_precision !== value.quantity_precision || line.from_location_id !== value.from_location_id || line.to_location_id !== value.to_location_id) invalid();
  if (value.phase === 2 ? !text(value.poster_actor_id) || [value.creator_actor_id, value.reviewer_actor_id].includes(value.poster_actor_id)
      || head.posted_by !== value.poster_actor_id : value.poster_actor_id !== null) invalid();
  if (value.original !== null && (!transferObject(value.original) || !/^IT1-S-[A-F0-9]{32}$/.test(String(value.original.id)) || !digest(value.original.source_digest))) invalid();
  return value as TransferSource;
}
export interface TransferCommandBinding { actorId: string; tenantId: string; previousVersion: number | null; originalId?: string; }
export async function parseTransferAck(value: unknown, command: PreparedScopedCommand, scope: FinanceScope, binding: TransferCommandBinding): Promise<TransferSource> {
  if (!transferObject(value) || !transferObject(value.command_ack) || !transferObject(value.submitted_request)
      || transferCanonical(value.submitted_request) !== transferCanonical(command.body)) invalid();
  const ack = value.command_ack, source = await parseTransfer(value.source, scope, binding.tenantId);
  await seal(value.submitted_request, value.submitted_request_digest, false);
  await seal({ source: value.source, native_response: value.native_response }, ack.response_digest, false);
  if (transferCanonical(value.native_response) !== transferCanonical(source.native_response) || ack.schema_version !== "inventory-transfer-command-ack-v1"
      || ack.command_id !== command.body.command_id || ack.actor_id !== binding.actorId || ack.transfer_id !== source.id
      || ack.source_digest !== source.source_digest || ack.version !== source.row_version || !scoped(ack.scope, scope)
      || ack.native_movement_id !== source.native_movement_id || !transferObject(ack.request_json)
      || ack.request_json.actor_id !== binding.actorId || ack.request_json.operation !== ack.operation) invalid();
  await seal(ack.request_json, ack.request_digest);
  const body = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "command_id"));
  const normalized = Object.fromEntries(Object.entries(body).map(([key, part]) => [key, typeof part === "string" ? part.trim() : part]));
  const create = command.path === `${transferRoot}/transfers`, subject = /^\/transfers\/(IT1-S-[A-F0-9]{32})\/(review|post|cancel|inverse)$/.exec(command.path.slice(transferRoot.length));
  if (!create && !subject) invalid();
  const operation = create ? "create" : subject![2] === "inverse" ? "inverse-create" : subject![2];
  const phase = ["create", "inverse-create"].includes(operation) ? 0 : operation === "review" ? 1 : operation === "post" ? 2 : 3;
  if (ack.operation !== operation || source.phase !== phase || source.row_version !== (["create", "inverse-create"].includes(operation) ? 1 : (binding.previousVersion ?? -2) + 1)) invalid();
  if (create) {
    const expected = { schema_version: "inventory-transfer-v1", ...normalized, scope };
    if (source.creator_actor_id !== binding.actorId || source.original !== null || transferCanonical(source.command_request) !== transferCanonical(expected)
        || transferCanonical(ack.request_json.request) !== transferCanonical(expected)) invalid();
  } else if (operation === "inverse-create") {
    const expected = { original_id: subject![1], ...normalized };
    if (binding.originalId !== subject![1] || source.creator_actor_id !== binding.actorId || source.original?.id !== subject![1]
        || source.original.source_digest !== body.expected_digest || source.original.version !== body.expected_version
        || transferCanonical(source.command_request) !== transferCanonical(expected) || transferCanonical(ack.request_json.request) !== transferCanonical(expected)) invalid();
  } else {
    if (subject![1] !== source.id || body.expected_digest !== source.source_digest || body.expected_version !== binding.previousVersion
        || transferCanonical(ack.request_json.request) !== transferCanonical({ id: source.id, ...normalized })) invalid();
    if (operation === "review" && source.reviewer_actor_id !== binding.actorId || operation === "post" && source.poster_actor_id !== binding.actorId) invalid();
    if (["post", "cancel"].includes(operation) && transferObject(source.release) && source.release.actor_id !== binding.actorId) invalid();
  }
  return source;
}
export function transferRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) {
  return financeRequest(session, scope, path, command?.body, signal);
}
export function transferMoney(minor: string, precision: number): string {
  if (!exact(minor) || !Number.isInteger(precision) || precision < 0 || precision > 8) invalid();
  const digits = minor.padStart(precision + 1, "0"); return precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits;
}
