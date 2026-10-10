import { useEffect, useRef, useState, type FormEvent } from "react";
import { AdminApiError } from "../data";
import { executeCollectionCommand, prepareCollectionCommand, type CollectionCommand, type CollectionPlan } from "../commercial-collections-data";
import type { ScopedJsonValue } from "../scoped-command";
import type { SalesIdentity, SalesScope } from "../sales-revenue-data";
import type { CommerceTranche } from "../stock-commerce-data";
import type { StockOptions } from "../stock-sales-data";
import type { BrowserAdminSession, Locale } from "../types";

const words = {
  title: ["Collect this invoice in installments", "تحصيل هذه الفاتورة على دفعات"], amount: ["Collection in minor units", "الدفعة بالوحدات النقدية الصغرى"],
  balance: ["Invoice outstanding in minor units", "متبقي الفاتورة بالوحدات النقدية الصغرى"], prepare: ["Prepare invoice installment", "إعداد دفعة الفاتورة"],
  review: ["Review invoice installment", "مراجعة دفعة الفاتورة"], post: ["Post invoice installment", "ترحيل دفعة الفاتورة"],
  receipt: ["Unique receipt number", "رقم إيصال فريد"], date: ["Collection date", "تاريخ التحصيل"], journal: ["Cash journal", "يومية التحصيل"],
  period: ["Open period", "الفترة المفتوحة"], cash: ["Cash asset account", "حساب أصل النقد"], reason: ["Collection reason", "سبب التحصيل"],
  error: ["Collection refused. Reload the invoice before changing the request.", "رُفض التحصيل. أعد تحميل الفاتورة قبل تغيير الطلب."],
  unknown: ["Response was lost. Retry the retained command to learn its committed result.", "فُقد الرد. أعد إرسال الأمر المحفوظ لمعرفة نتيجته المعتمدة."],
  retry: ["Retry retained collection command", "إعادة أمر التحصيل المحفوظ"], duties: ["Preparation, review and posting require three distinct authorized people.", "الإعداد والمراجعة والترحيل تتطلب ثلاثة أشخاص مختلفين لديهم الصلاحيات."],
  posted: ["Native receipt and cash effect posted", "تم ترحيل الإيصال وأثر النقد"], evidence: ["Receipt and financial evidence", "دليل الإيصال والقيد المالي"],
} as const;

export function CommercialCollectionsPanel({ locale, session, scope, identity, tranche, options, disabled, onPendingChange, onCommitted }: {
  locale: Locale; session: BrowserAdminSession; scope: SalesScope; identity: SalesIdentity; tranche: CommerceTranche; options: StockOptions | null;
  disabled: boolean; onPendingChange: (value: boolean) => void; onCommitted: () => void;
}) {
  const t = (key: keyof typeof words) => words[key][locale === "ar" ? 1 : 0];
  const [fields, setFields] = useState({ amount_minor: "", receipt_number: "", posting_date: "", journal_code: "", period_id: "", debit_account_code: "", reason: "" });
  const [pending, setPending] = useState<CollectionCommand | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<"error" | "unknown" | null>(null), [posted, setPosted] = useState<CollectionPlan | null>(null);
  const lock = useRef(false), mounted = useRef(true), alert = useRef<HTMLDivElement>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  const plan = tranche.pending_collection, writable = !disabled && !busy && !pending && identity.human && identity.stepUp;
  const has = (...permissions: string[]) => permissions.every((permission) => identity.permissions.includes(permission));
  const action = plan?.phase === 0 ? "review" : plan?.phase === 1 ? "post" : "prepare";
  const duties = Boolean(plan && (plan.preparer_actor_id === identity.id || (action === "post" && (!plan.reviewer_actor_id || plan.reviewer_actor_id === identity.id))));
  const permitted = action === "prepare" ? has("sales.manage", "finance_core.manage", "receivables.manage") : action === "review" ? has("sales.approve", "finance_core.validate", "receivables.manage") : has("sales.manage", "receivables.manage", "finance_core.post");
  async function send(command: CollectionCommand) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setPending(command); setError(null); onPendingChange(true);
    try {
      const result = await executeCollectionCommand(session, command);
      if (mounted.current) { setPending(null); onPendingChange(false); setError(null); setPosted(result.status === "Posted" ? result : null); onCommitted(); }
    } catch (caught) {
      if (mounted.current) {
        const unknown = !(caught instanceof AdminApiError) || caught.status >= 500;
        setError(unknown ? "unknown" : "error");
        if (!unknown) { setPending(null); onPendingChange(false); onCommitted(); }
      }
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault(); if (!writable || !permitted || duties || !fields.reason.trim() || !tranche.invoice_id) return;
    if (!plan && (!/^[1-9]\d{0,18}$/.test(fields.amount_minor) || BigInt(fields.amount_minor) > BigInt(tranche.outstanding_minor || "0"))) { setError("error"); return; }
    const path = plan ? `/api/v1/commercial-collections/plans/${encodeURIComponent(plan.id)}/${action}` : "/api/v1/commercial-collections/plans";
    const body: Record<string, ScopedJsonValue> = plan ? { expected_plan_digest: plan.plan_digest, reason: fields.reason } : { ...fields, source_id: tranche.invoice_id, source_kind: "ARReceipt", credit_account_code: tranche.receivable_account_code || "" };
    void send(prepareCollectionCommand(scope, path, body));
  }
  const input = (key: "amount_minor" | "receipt_number" | "posting_date" | "reason", label: keyof typeof words, type = "text") => <label>{t(label)}<input required type={type} value={fields[key]} disabled={!writable} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} maxLength={key === "reason" ? 500 : 64} /></label>;
  const select = (key: "journal_code" | "period_id" | "debit_account_code", label: keyof typeof words, choices: { code: string; name: string }[]) => <label>{t(label)}<select required value={fields[key]} disabled={!writable} onChange={(event) => setFields({ ...fields, [key]: event.target.value })}><option value="">—</option>{choices.map((choice) => <option key={choice.code} value={choice.code}>{choice.name}</option>)}</select></label>;
  return <section aria-label={t("title")} dir={locale === "ar" ? "rtl" : "ltr"}>
    <h4>{t("title")}</h4><p>{t("balance")}: <strong>{tranche.outstanding_minor}</strong></p>
    {error && <div role="alert" tabIndex={-1} ref={alert}>{t(error)}</div>}
    {pending && !busy && <button disabled={busy} onClick={() => void send(pending)}>{t("retry")}</button>}
    {posted && <p role="status">{t("posted")} · <code>{posted.receipt_id}</code> · <code>{posted.posting_effect_id}</code></p>}
    {(plan || tranche.outstanding_minor !== "0") && <form onSubmit={submit} aria-label={t(action)}>
      {!plan && <>{input("amount_minor", "amount")}{input("receipt_number", "receipt")}{input("posting_date", "date", "date")}
        {select("period_id", "period", options?.periods.map((row) => ({ code: row.id, name: row.name })) || [])}
        {select("journal_code", "journal", options?.journals.map((row) => ({ code: row.journal_code, name: row.name })) || [])}
        {select("debit_account_code", "cash", options?.accounts.filter((row) => row.account_type === "Asset" && row.account_code !== tranche.receivable_account_code).map((row) => ({ code: row.account_code, name: row.name })) || [])}</>}
      {plan && <p>{t("amount")}: <strong>{plan.amount_minor}</strong> · <code>{plan.id}</code></p>}
      {input("reason", "reason")}<p>{t("duties")}</p><button disabled={!writable || !permitted || duties}>{t(action)}</button>
    </form>}
  </section>;
}
