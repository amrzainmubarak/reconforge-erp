import type { FinanceScope } from "./enterprise-finance-data";
import { manufacturingRequest } from "./manufacturing-execution-data";
export { manufacturingRequest as manufacturingV2Request } from "./manufacturing-execution-data";

export const manufacturingV2Root = "/api/v1/manufacturing-execution-v2";
export const manufacturingV2Read = ["manufacturing_execution.read", "manufacturing_execution_v2.read", "inventory.read", "finance_core.read"];
export const manufacturingV2Permissions = {
  create: [...manufacturingV2Read, "manufacturing_execution.manage", "manufacturing_execution_v2.manage", "inventory.manage"],
  prepare: [...manufacturingV2Read, "manufacturing_execution.manage", "manufacturing_execution_v2.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"],
  approve: [...manufacturingV2Read, "manufacturing_execution.approve", "manufacturing_execution_v2.approve"],
  review: [...manufacturingV2Read, "manufacturing_execution.approve", "manufacturing_execution_v2.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"],
  post: [...manufacturingV2Read, "manufacturing_execution.post", "manufacturing_execution_v2.post", "inventory.post", "inventory.valuation.approve", "finance_core.post"],
  cancel: [...manufacturingV2Read, "manufacturing_execution.approve", "manufacturing_execution_v2.approve"],
};
export type ManufacturingV2Source = Record<string, unknown> & FinanceScope & {
  id: string; source_digest: string; phase: number; kind?: string; creator_id?: string; preparer_id?: string; reviewer_id?: string | null;
  number?: string; code?: string; order_id?: string; production_id?: string; order_digest?: string; production_digest?: string;
  total_cost_minor?: string; produced_quantity_scaled?: string; produced_cost_minor?: string;
  disposed_quantity_scaled?: string; released_cost_minor?: string; wip_minor?: string; held_cost_minor?: string; held_quantity_scaled?: string;
  material?: Record<string, unknown>; productions?: ManufacturingV2Source[]; inspections?: ManufacturingV2Source[];
  operations?: Array<{ sequence: number; minutes_per_batch?: number; minutes?: number; name?: string; workcenter_id?: string; evidence_reference?: string }>;
};
export const me2Object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
export const me2Integer = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9_000_000_000_000_000_000n;
function invalid(): never { throw new Error("manufacturing_v2_evidence_invalid"); }
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && !/[\x00-\x1f\x7f]/.test(value);
const digest = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const numerical = (key: string) => key.endsWith("_minor") || key.endsWith("_scaled") || ["rate_minor_per_hour", "minutes", "minutes_per_batch", "version"].includes(key);
export function manufacturingV2Canonical(value: unknown, key = ""): string {
  if (numerical(key) && typeof value === "string" && me2Integer(value)) return value;
  if (Array.isArray(value)) return `[${value.map(part => manufacturingV2Canonical(part)).join(",")}]`;
  if (me2Object(value)) return `{${Object.keys(value).sort().map(name => `${JSON.stringify(name)}:${manufacturingV2Canonical(value[name], name)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
export async function manufacturingV2Digest(value: unknown): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(manufacturingV2Canonical(value))))].map(part => part.toString(16).padStart(2, "0")).join("");
}
async function seal(value: unknown, expected: unknown) { if (!digest(expected) || await manufacturingV2Digest(value) !== expected) invalid(); }
function scalar(value: Record<string, unknown>, keys: string[]) { for (const key of keys) if (!me2Integer(value[key])) invalid(); }
function parentScope(value: Record<string, unknown>, scope: FinanceScope) { for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid(); }
async function draft(value: unknown) {
  if (!me2Object(value) || !text(value.entry_id) || !me2Object(value.snapshot)) invalid();
  await seal(value.snapshot, value.validation_digest);
}
export async function parseManufacturingV2(raw: unknown, scope: FinanceScope): Promise<ManufacturingV2Source> {
  if (!me2Object(raw) || !/^ME2(?:W|R|P|C)?-[A-F0-9]{32}$/.test(String(raw.id)) || !digest(raw.source_digest) || typeof raw.phase !== "number" || !Number.isSafeInteger(raw.phase)) invalid();
  parentScope(raw, scope);
  const identifier = String(raw.id), definition = identifier.startsWith("ME2W-") || identifier.startsWith("ME2R-"), production = identifier.startsWith("ME2P-"), inspection = identifier.startsWith("ME2C-");
  const dynamic = definition ? ["phase", "source_digest", "kind", "reviewer_id", ...(identifier.startsWith("ME2W-") ? ["number"] : [])] : production ? ["phase", "source_digest", "reviewer_id"] : inspection ? ["phase", "source_digest", "reviewer_id", "receipt_effect", "loss_effect_id"] :
    ["phase", "source_digest", "cost_entry", "total_cost_minor", "reviewer_id", "cost_effect_id", "produced_quantity_scaled", "produced_cost_minor", "disposed_quantity_scaled", "released_cost_minor", "productions", "inspections", "material", "wip_minor", "held_cost_minor", "held_quantity_scaled"];
  if (raw.phase < 0 || raw.phase > (definition ? 1 : production ? 4 : inspection ? 3 : 5) || !text(definition || !production && !inspection ? raw.creator_id : raw.preparer_id)) invalid();
  await seal(Object.fromEntries(Object.entries(raw).filter(([key]) => !dynamic.includes(key))), raw.source_digest);
  const preparer = definition ? raw.creator_id : production || inspection ? raw.preparer_id : me2Object(raw.cost_entry) && me2Object(raw.cost_entry.snapshot) && me2Object(raw.cost_entry.snapshot.entry) ? raw.cost_entry.snapshot.entry.preparer_actor_id : raw.creator_id;
  if ((definition && raw.phase === 1 || production && [1, 2, 3].includes(raw.phase) || inspection && [1, 2].includes(raw.phase) || !definition && !production && !inspection && [2, 3, 4].includes(raw.phase)) && (!text(raw.reviewer_id) || raw.reviewer_id === preparer)) invalid();
  if (production) {
    scalar(raw, ["quantity_scaled", "held_cost_minor", "produced_before_scaled", "produced_cost_before_minor"]);
    if (!text(raw.order_id) || !digest(raw.order_digest) || !Array.isArray(raw.operations) || !raw.operations.length || raw.operations.length > 50) invalid();
  } else if (inspection) {
    scalar(raw, ["accepted_quantity_scaled", "rejected_quantity_scaled", "accepted_cost_minor", "rejected_cost_minor", "released_cost_minor"]);
    if (!text(raw.order_id) || !text(raw.production_id) || !digest(raw.order_digest) || !digest(raw.production_digest) || BigInt(String(raw.accepted_cost_minor)) + BigInt(String(raw.rejected_cost_minor)) !== BigInt(String(raw.released_cost_minor))) invalid();
    if (raw.receipt_plan !== null) {
      if (!me2Object(raw.receipt_plan) || !me2Object(raw.receipt_plan.source) || raw.receipt_plan.source.number !== raw.id || raw.receipt_plan.source.total_value_minor !== raw.accepted_cost_minor) invalid();
      await seal(Object.fromEntries(Object.entries(raw.receipt_plan).filter(([key]) => !["plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"].includes(key))), raw.receipt_plan.plan_digest);
    }
    if (raw.loss_entry !== null) await draft(raw.loss_entry);
    if (raw.phase === 2 && BigInt(String(raw.accepted_quantity_scaled)) > 0n) {
      if (!me2Object(raw.receipt_effect) || !me2Object(raw.receipt_plan) || raw.receipt_effect.plan_id !== raw.receipt_plan.plan_id || raw.receipt_effect.plan_digest !== raw.receipt_plan.plan_digest || !text(raw.receipt_effect.posted_actor_id) || [preparer, raw.reviewer_id].includes(raw.receipt_effect.posted_actor_id)) invalid();
      await seal(Object.fromEntries(Object.entries(raw.receipt_effect).filter(([key]) => key !== "effect_digest")), raw.receipt_effect.effect_digest);
    } else if (raw.receipt_effect !== null) invalid();
    if (raw.phase !== 2 && raw.loss_effect_id !== null || raw.phase === 2 && (BigInt(String(raw.rejected_quantity_scaled)) > 0n ? !text(raw.loss_effect_id) : raw.loss_effect_id !== null)) invalid();
  } else if (!definition) {
    scalar(raw, ["total_cost_minor", "produced_quantity_scaled", "produced_cost_minor", "disposed_quantity_scaled", "released_cost_minor"]);
    if (raw.cost_entry !== null) await draft(raw.cost_entry);
    if (BigInt(String(raw.released_cost_minor)) > BigInt(String(raw.produced_cost_minor)) || BigInt(String(raw.produced_cost_minor)) > BigInt(String(raw.total_cost_minor)) || BigInt(String(raw.disposed_quantity_scaled)) > BigInt(String(raw.produced_quantity_scaled))) invalid();
    if (raw.material !== undefined) {
      if (!me2Object(raw.material) || raw.material.execution_version !== 2 || !me2Object(raw.material.execution_owner) || raw.material.execution_owner.id !== raw.id || raw.material.execution_owner.source_digest !== raw.source_digest || raw.material.id !== raw.material_order_id || raw.material.source_digest !== raw.material_source_digest || !me2Integer(raw.material.output_quantity_scaled)) invalid();
      if (BigInt(String(raw.produced_quantity_scaled)) > BigInt(raw.material.output_quantity_scaled)) invalid();
      const materialDynamic = ["phase", "source_digest", "issue_plan", "issue_digest", "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor", "completions", "wip_minor", "execution_version", "execution_owner", "material_cost_minor"];
      await seal(Object.fromEntries(Object.entries(raw.material).filter(([key]) => !materialDynamic.includes(key))), raw.material.source_digest);
      if (raw.material.issue_plan !== null) await seal(raw.material.issue_plan, raw.material.issue_digest);
      scalar(raw, ["wip_minor", "held_cost_minor", "held_quantity_scaled"]);
      if (BigInt(String(raw.held_quantity_scaled)) !== BigInt(String(raw.produced_quantity_scaled)) - BigInt(String(raw.disposed_quantity_scaled)) || BigInt(String(raw.held_cost_minor)) !== BigInt(String(raw.produced_cost_minor)) - BigInt(String(raw.released_cost_minor)) || BigInt(String(raw.wip_minor)) !== ([3, 4].includes(raw.phase) ? BigInt(String(raw.total_cost_minor)) - BigInt(String(raw.released_cost_minor)) : 0n)) invalid();
    }
    if (raw.productions !== undefined || raw.inspections !== undefined) {
      if (!Array.isArray(raw.productions) || !Array.isArray(raw.inspections) || raw.productions.length > 200 || raw.inspections.length > 40000) invalid();
      raw.productions = await Promise.all(raw.productions.map(value => parseManufacturingV2(value, scope)));
      raw.inspections = await Promise.all(raw.inspections.map(value => parseManufacturingV2(value, scope)));
      const holds = raw.productions as ManufacturingV2Source[], choices = raw.inspections as ManufacturingV2Source[];
      if (new Set(holds.map(row => row.id)).size !== holds.length || new Set(choices.map(row => row.id)).size !== choices.length || [...holds, ...choices].some(row => row.order_id !== raw.id || row.order_digest !== raw.source_digest)) invalid();
      for (const choice of choices) { const hold = holds.find(row => row.id === choice.production_id); if (!hold || choice.production_digest !== hold.source_digest) invalid(); }
      const posted = choices.filter(row => row.phase === 2);
      if (new Set(posted.map(row => row.production_id)).size !== posted.length || posted.reduce((sum, row) => sum + BigInt(String(row.released_cost_minor)), 0n) !== BigInt(String(raw.released_cost_minor))) invalid();
    }
  }
  return raw as ManufacturingV2Source;
}
export async function parseManufacturingV2Page(value: Record<string, unknown>, scope: FinanceScope) {
  if (!Array.isArray(value.orders) || !Array.isArray(value.definitions) || value.orders.length > 200 || value.definitions.length > 200) invalid();
  return { orders: await Promise.all(value.orders.map(row => parseManufacturingV2(row, scope))), definitions: await Promise.all(value.definitions.map(row => parseManufacturingV2(row, scope))) };
}
export type ManufacturingV2Request = typeof manufacturingRequest;
