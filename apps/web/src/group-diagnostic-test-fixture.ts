/** Test-only projection of one byte-exact historical native two-source capture.
 * Original download handling never parses or reserializes native integer bytes. */
import original from "../../../tests/fixtures/intercompany-group-diagnostic-native-v1.json";
import { cashflowSha, type CashflowView } from "./intercompany-cashflow-data";
import { displayFixture } from "./intercompany-cashflow-test-fixture";
import { parseFxDetail, type FxDetail, type FxEvidence, type FxReport } from "./intercompany-fx-data";
import type { GroupOriginal, GroupPin, GroupView } from "./group-diagnostic-data";

export async function groupFixture() {
  const scope = { workspace_id: original.diagnostic.qualified_scope.workspace_id, organization_id: original.diagnostic.qualified_scope.organization_id }, tenant = original.diagnostic.qualified_scope.tenant_id;
  const originals: GroupOriginal[] = [];
  const sources: { detail: FxDetail; stages: FxEvidence[]; report: FxReport; cashflowView: CashflowView }[] = [];
  for (const [index, capture] of original.source_captures.entries()) {
    const stages = displayFixture(capture.stages) as FxEvidence[], report = displayFixture(capture.report) as FxReport;
    const paid = stages.filter(row => row.plan.kind === "settle").reduce((sum, row) => sum + BigInt(row.plan.equation.transaction_minor as string), 0n);
    const detail = parseFxDetail({ ...displayFixture(capture.source) as object, plans: stages.map(row => row.plan), state: { sequence: stages.length, recognized: true, closed: true, transaction_paid_minor: paid.toString(), active_revaluation_id: stages.find(row => row.plan.kind === "revalue")?.plan.id ?? null } }, scope);
    const bytes = new TextEncoder().encode(JSON.stringify(capture));
    const cashflowView = { cashflow: displayFixture(capture.cashflow), qualified_scope: capture.qualified_scope, evidence_digest: capture.evidence_digest, evidence_sha256: await cashflowSha(bytes), evidence_bytes: bytes.length } as CashflowView;
    originals.push({ detail, report, cashflowView, pin: original.selection.pins[index] as GroupPin }); sources.push({ detail, stages, report, cashflowView });
  }
  const bytes = new TextEncoder().encode(JSON.stringify(original));
  const view = { diagnostic: displayFixture(original.diagnostic), evidence_digest: original.evidence_digest, evidence_sha256: await cashflowSha(bytes), evidence_bytes: bytes.length } as GroupView;
  return { originals, sources, bytes, view, scope, tenant };
}
