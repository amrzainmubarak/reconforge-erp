import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { manufacturingV2Digest } from "./manufacturing-execution-v2-data";
type Row = Record<string, any>;
export const scopeV2 = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
export function manufacturingV2Wire(value: any, key = ""): any {
  if (typeof value === "number" && (key.endsWith("_minor") || key.endsWith("_scaled") || key === "rate_minor_per_hour" || !Number.isSafeInteger(value))) return String(value);
  if (Array.isArray(value)) return value.map(part => manufacturingV2Wire(part));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([name, part]) => [name, manufacturingV2Wire(part, name)]));
  return value;
}
export function actualManufacturingV2Page(held = false) {
  const path = resolve(dirname(fileURLToPath(import.meta.url)), "../../../tests/fixtures", `manufacturing_v2_original_${held ? "quality_hold" : "golden"}.json`);
  const proof = JSON.parse(readFileSync(path, "utf8"));
  const tables = proof.populations as Record<string, Row[]>;
  const flat = (row: Row) => ({ ...row.payload, ...Object.fromEntries(Object.entries(row).filter(([key]) => !["payload", "tenant_id", "created_at"].includes(key))) });
  const source = flat(tables.manufacturing_execution_v2_orders[0]), materialRow = tables.manufacturing_execution_orders[0];
  const material = { ...materialRow.payload, ...Object.fromEntries(["phase", "source_digest", "issue_plan", "issue_digest", "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor"].map(key => [key, materialRow[key]])),
    completions: [], execution_version: 2, execution_owner: Object.fromEntries(["id", "phase", "source_digest", "total_cost_minor", "produced_quantity_scaled", "disposed_quantity_scaled", "released_cost_minor"].map(key => [key, source[key]])),
    material_cost_minor: materialRow.issue_plan.total_cost_minor, wip_minor: source.total_cost_minor - source.released_cost_minor };
  return manufacturingV2Wire({ definitions: tables.manufacturing_execution_v2_definitions.map(flat), orders: [{ ...source, material,
    productions: tables.manufacturing_execution_v2_productions.map(flat), inspections: tables.manufacturing_execution_v2_inspections.map(flat),
    wip_minor: source.total_cost_minor - source.released_cost_minor, held_cost_minor: source.produced_cost_minor - source.released_cost_minor,
    held_quantity_scaled: source.produced_quantity_scaled - source.disposed_quantity_scaled }] });
}
export async function definitionV2(approved = false) {
  const body = { ...scopeV2, organization_code: "ORG", entity_code: "ENTITY", schema_version: "manufacturing-workcenter-v2",
    id: "ME2W-" + "A".repeat(32), creator_id: "maker", code: "ASSEMBLY", version: 1, name: "Actual assembly", effective_from: "2026-10-01", effective_until: "2026-10-31",
    reason: "Original engineering source", command_request: { ...scopeV2, organization_code: "ORG", entity_code: "ENTITY", schema_version: "manufacturing-workcenter-v2", code: "ASSEMBLY", version: 1,
      name: "Actual assembly", effective_from: "2026-10-01", effective_until: "2026-10-31", reason: "Original engineering source" } };
  return { ...body, source_digest: await manufacturingV2Digest(body), kind: "Workcenter", number: "ASSEMBLY", phase: approved ? 1 : 0, reviewer_id: approved ? "checker" : null };
}
