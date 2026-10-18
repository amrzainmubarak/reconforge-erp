import { useEffect, useRef, useState } from "react";
import { financeMoney, type FinanceScope } from "../enterprise-finance-data";
import { assetRequest, verifyAssetEvidence, type AssetEvidence, type AssetPlan } from "../fixed-assets-data";
import { formatExactDecimal } from "../locale-format";
import type { BrowserAdminSession, Locale } from "../types";

const labels = {
  en: { title: "Verified source to ledger evidence", verify: "Verify source and ledger evidence", verified: "Source definition, retained operation and native journal hashes verified in this browser.", asset: "Source definition digest", plan: "Operation digest", journal: "Native journal digest", effect: "Native posting effect", debit: "Verified debit", credit: "Verified credit", phase: "Evidence action", actor: "Human actor", audit: "Audit event", outbox: "Outbox event", prepared: "Preparation", reviewed: "Independent review", posted: "Asset posting", native: "Native GL posting", download: "Download verified evidence", pending: "This operation has no posted financial effect." },
  ar: { title: "أدلة موثقة من المصدر إلى دفتر الأستاذ", verify: "التحقق من أدلة المصدر والقيد", verified: "تم التحقق من بصمات تعريف المصدر والعملية المحفوظة والقيد الأصلي داخل هذا المتصفح.", asset: "بصمة تعريف المصدر", plan: "بصمة العملية", journal: "بصمة القيد الأصلي", effect: "أثر القيد الأصلي", debit: "المدين المتحقق منه", credit: "الدائن المتحقق منه", phase: "إجراء الدليل", actor: "المستخدم البشري", audit: "حدث التدقيق", outbox: "حدث صندوق الإرسال", prepared: "الإعداد", reviewed: "المراجعة المستقلة", posted: "ترحيل الأصل", native: "ترحيل دفتر الأستاذ الأصلي", download: "تنزيل الأدلة المتحقق منها", pending: "لا يوجد أثر مالي مُرحل لهذه العملية." },
};
interface Props { locale: Locale; session: BrowserAdminSession; scope: FinanceScope; plan: AssetPlan; locked: boolean; isCurrent: () => boolean; onError: (error: unknown) => void }

export default function FixedAssetEvidencePanel({ locale, session, scope, plan, locked, isCurrent, onError }: Props) {
  const t = labels[locale], mounted = useRef(true), active = useRef(false);
  const [busy, setBusy] = useState(false), [evidence, setEvidence] = useState<AssetEvidence | null>(null);
  const downloadUrl = useRef<string | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current); }; }, []);
  async function verify() {
    if (active.current || locked) return;
    active.current = true; setBusy(true); setEvidence(null);
    try {
      const raw = await assetRequest(session, scope, `/api/v1/fixed-assets/plans/${encodeURIComponent(plan.id)}/evidence`);
      const proof = await verifyAssetEvidence(raw.evidence, scope, plan);
      if (mounted.current && isCurrent()) setEvidence(proof);
    } catch (error) { if (mounted.current && isCurrent()) onError(error); }
    finally { active.current = false; if (mounted.current && isCurrent()) setBusy(false); }
  }
  function download() {
    if (!evidence || !isCurrent()) return;
    if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    downloadUrl.current = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2) + "\n"], { type: "application/json" }));
    const link = document.createElement("a"); link.href = downloadUrl.current; link.download = `${plan.id}-evidence.json`; link.click();
  }
  const money = (value: string) => `${formatExactDecimal(financeMoney(value, plan.currency_precision), locale)} ${plan.currency_code}`;
  return <section aria-label={t.title}>
    <h3>{t.title}</h3><button disabled={busy || locked} onClick={() => void verify()}>{t.verify}</button>
    {evidence && <>
      <p role="status">{t.verified}</p>
      <dl>{([[t.asset, evidence.asset_definition.asset_digest], [t.plan, evidence.plan.plan_digest], [t.journal, evidence.plan.validation_digest], [t.effect, evidence.native_effect?.id ?? "—"]] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code dir="ltr">{String(value)}</code></dd></div>)}</dl>
      <p>{t.debit}: <bdi>{money(evidence.totals.debit_minor)}</bdi></p><p>{t.credit}: <bdi>{money(evidence.totals.credit_minor)}</bdi></p>
      {!evidence.native_effect && <p>{t.pending}</p>}
      <div className="reporting-table" role="region" tabIndex={0} aria-label={t.audit}><table><caption>{t.title}</caption><thead><tr><th>{t.phase}</th><th>{t.actor}</th><th>{t.audit}</th><th>{t.outbox}</th></tr></thead><tbody>{evidence.phases.map((row, index) => <tr key={row.action}><td>{[t.prepared, t.reviewed, t.posted, t.native][index]}</td><td><code dir="ltr">{row.actor_id}</code></td><td><code dir="ltr">{row.audit_event_id}</code></td><td><code dir="ltr">{row.outbox_event_id}</code></td></tr>)}</tbody></table></div>
      <button disabled={busy || locked} onClick={download}>{t.download}</button>
    </>}
  </section>;
}
