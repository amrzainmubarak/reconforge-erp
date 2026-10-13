/** The committed fixture is an authorized synthetic historical native capture.
 * Projection here is test-only; original raw byte handling never uses this. */
import original from "../../../tests/fixtures/intercompany-source-cashflow-native-v1.json";
import { cashflowSha, type CashflowView } from "./intercompany-cashflow-data";
import { parseFxDetail, type FxDetail, type FxEvidence, type FxReport } from "./intercompany-fx-data";
export function displayFixture(value: unknown, key = ""): unknown {
  if (typeof value === "number" && key.endsWith("_minor")) return String(value);
  if (Array.isArray(value)) return value.map(item => displayFixture(item));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, displayFixture(item, name)]));
  return value;
}
export async function cashflowFixture() {
  const source = displayFixture(original.source) as object, stages = displayFixture(original.stages) as FxEvidence[];
  const scope = { workspace_id: original.qualified_scope.workspace_id, organization_id: original.qualified_scope.organization_id };
  const paid = stages.filter(row => row.plan.kind === "settle").reduce((sum, row) => sum + BigInt(row.plan.equation.transaction_minor as string), 0n);
  const detail: FxDetail = parseFxDetail({ ...source, plans: stages.map(row => row.plan), state: { sequence: stages.length, recognized: true, closed: true, transaction_paid_minor: paid.toString(), active_revaluation_id: stages.filter(row => row.plan.kind === "revalue").at(-1)?.plan.id ?? null } }, scope);
  const report = displayFixture(original.report) as FxReport, bytes = new TextEncoder().encode(JSON.stringify(original));
  const view: CashflowView = { cashflow: displayFixture(original.cashflow) as CashflowView["cashflow"], evidence_digest: original.evidence_digest, evidence_sha256: await cashflowSha(bytes), evidence_bytes: bytes.length, qualified_scope: original.qualified_scope };
  return { detail, report, stages, view, bytes, scope, tenant: original.qualified_scope.tenant_id };
}
