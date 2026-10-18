/** Actual historical synthetic native export, projected through the exact API text contract.
 * Prepared/reviewed variants are explicitly synthetic UI fixtures, not native runs.
 */
import native from "../../../tests/fixtures/accrual-deferral-native-v1.json";
import { adHash, type AdRecord } from "./accrual-deferral-data";
export function adFixture(): AdRecord {
  function wire(value: unknown, key = ""): unknown { if (Array.isArray(value)) return value.map(item => wire(item)); if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([field, item]) => [field, wire(item, field)])); return typeof value === "number" && (key.endsWith("_minor") || key === "weight") ? String(value) : value; }
  return wire(structuredClone(native)) as AdRecord;
}
export async function adUiFixture(phase: 0 | 1 | 2): Promise<AdRecord> {
  const proof = adFixture(), source = proof.source as AdRecord, original = (source.plans as AdRecord[]).find(row => row.kind === "source")!;
  source.plans = [{ ...original, phase, status: ["Prepared", "Reviewed", "Posted"][phase], reviewer_actor_id: phase > 0 ? "checker" : null, posted_actor_id: phase === 2 ? "poster" : null, posting_effect_id: phase === 2 ? original.posting_effect_id : null }];
  source.claims = (source.claims as AdRecord[]).map(row => ({ ...row, sequence: 1, plan_id: original.id, state: "Available" }));
  proof.native_effects = phase === 2 ? (proof.native_effects as AdRecord[]).filter(row => row.id === original.posting_effect_id) : [];
  proof.claims = (proof.claims as AdRecord[]).filter(row => row.plan_id === original.id && row.operation === "Initialize");
  for (const field of ["commands", "phases"]) proof[field] = (proof[field] as AdRecord[]).filter(row => row.plan_id === original.id && ["prepare", "review", "post"].indexOf(String(row.operation)) <= phase);
  proof.evidence_digest = await adHash(Object.fromEntries(Object.entries(proof).filter(([key]) => key !== "evidence_digest")));
  return proof;
}
