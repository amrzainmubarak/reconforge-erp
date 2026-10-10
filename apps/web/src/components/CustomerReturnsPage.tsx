import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { parseReturnPlan, parseRefundBalance, returnRequest, type ReturnPlan, type RefundBalance } from "../customer-returns-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { financeMoney, type FinanceScope } from "../enterprise-finance-data";
import { formatExactDecimal } from "../locale-format";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

const words = {
  title: ["Original customer returns and partial refunds", "إرجاع العميل الأصلي وردّ النقد على دفعات"],
  boundary: ["Return the complete original delivered tranche, in functional currency with zero tax. Original invoice, FIFO consumption and collection evidence remain retained.", "إرجاع كامل الدفعة المسلّمة الأصلية بالعملة الوظيفية ودون ضريبة. تظل الفاتورة واستهلاكات FIFO وأدلة التحصيل الأصلية محفوظة."],
  duties: ["Preparation, review and posting require three distinct authorized humans.", "الإعداد والمراجعة والترحيل تتطلب ثلاثة أشخاص مختلفين لديهم الصلاحيات."],
  tenant: ["Tenant", "المؤسسة"], username: ["Username", "المستخدم"], password: ["Password", "كلمة المرور"],
  signIn: ["Sign in", "تسجيل الدخول"], signOut: ["Sign out", "تسجيل الخروج"], stepUp: ["Verify financial authority", "تأكيد الصلاحية المالية"],
  workspace_id: ["Workspace ID", "معرّف مساحة العمل"], organization_id: ["Organization ID", "معرّف المنظمة"], legal_entity_id: ["Legal entity ID", "معرّف الكيان القانوني"],
  apply: ["Apply scope", "تطبيق النطاق"], refresh: ["Refresh native evidence", "تحديث الأدلة الأصلية"], select: ["Retained credit or refund", "مذكرة الائتمان أو الردّ المحفوظ"],
  source_order_id: ["Original delivered stock order ID", "معرّف أمر المخزون المسلّم الأصلي"], period_id: ["Open fiscal period ID", "معرّف الفترة المالية المفتوحة"],
  posting_date: ["Posting date", "تاريخ الترحيل"], journal_code: ["Cash journal code", "رمز يومية النقد"],
  refund_liability_account_code: ["Customer refund liability account", "حساب التزام ردّ النقد للعميل"], cash_account_code: ["Original collected cash account", "حساب النقد المحصّل الأصلي"],
  reason: ["Reason", "السبب"], amount_minor: ["Refund in exact minor units", "مبلغ الردّ بالوحدات النقدية الصغرى الدقيقة"],
  prepare: ["Prepare whole original return", "إعداد الإرجاع الأصلي الكامل"], refund: ["Prepare partial cash refund", "إعداد ردّ نقدي جزئي"],
  review: ["Review source inverse", "مراجعة عكس المصدر"], post: ["Post complete native effect", "ترحيل الأثر الأصلي الكامل"], cancel: ["Cancel unposted plan", "إلغاء الخطة غير المرحّلة"],
  evidence: ["Original source and native financial evidence", "دليل المصدر الأصلي والأثر المالي"], credit: ["Original invoice credit", "ائتمان الفاتورة الأصلية"],
  cogs: ["Original FIFO cost restored", "تكلفة FIFO الأصلية المستعادة"], entitlement: ["Collected refund entitlement", "استحقاق ردّ التحصيل"], due: ["Refund liability remaining", "التزام الردّ المتبقي"],
  invalid: ["Request or financial evidence is invalid.", "الطلب أو الدليل المالي غير صالح."], denied: ["Current authority or scope refused this action.", "الصلاحية الحالية أو النطاق رفضا الإجراء."],
  unavailable: ["Native evidence is unavailable. Refresh before a new action.", "الأدلة الأصلية غير متاحة. حدّثها قبل إجراء جديد."], conflict: ["Source changed or another command owns its pending effect.", "تغيّر المصدر أو يوجد أمر آخر يحجز الأثر المعلّق."],
  unknown: ["Response was lost. Retry the exact retained command to learn its committed result.", "فُقد الرد. أعد الأمر المحفوظ نفسه لمعرفة النتيجة المعتمدة."],
  retry: ["Retry retained command", "إعادة الأمر المحفوظ"], empty: ["No retained return plans in this scope.", "لا توجد خطط إرجاع محفوظة في هذا النطاق."],
} as const;
type Word = keyof typeof words;
const READ = ["sales.read", "receivables.read", "inventory.read", "finance_core.read"];
const permissions = {
  prepare: [...READ, "sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"],
  review: [...READ, "sales.approve", "inventory.valuation.approve", "finance_core.validate", "finance_core.reverse"],
  post: [...READ, "sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse"],
  cancel: [...READ, "sales.approve", "finance_core.validate"],
};
const root = "/api/v1/customer-returns/plans";
export default function CustomerReturnsPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(); return <ReturnSession key={auth.revision} locale={locale} />;
}
function ReturnSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: Word) => words[key][locale === "ar" ? 1 : 0];
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [plans, setPlans] = useState<ReturnPlan[]>([]), [plan, setPlan] = useState<ReturnPlan | null>(null), [balance, setBalance] = useState<RefundBalance | null>(null);
  const [fields, setFields] = useState({ source_order_id: "", period_id: "", posting_date: "", journal_code: "", refund_liability_account_code: "", cash_account_code: "", reason: "" });
  const [refund, setRefund] = useState({ amount_minor: "", period_id: "", posting_date: "", reason: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<Word | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), alert = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending);
  const has = (names: readonly string[]) => Boolean(identity?.human && names.every(name => identity.permissions.includes(name)));
  const allowed = (action: keyof typeof permissions) => Boolean(scope && identity?.stepUp && has(permissions[action]));
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
  }
  useEffect(() => {
    if (!auth.session) return; const controller = new AbortController();
    loadBudgetIdentity(auth.session, controller.signal).then(value => { if (current() && !controller.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !has(READ)) return; const controller = new AbortController();
    returnRequest(auth.session, scope, root, undefined, controller.signal).then(async response => {
      if (!Array.isArray(response.plans) || response.plans.length > 200) throw new Error("invalid_return_page");
      const values = await Promise.all(response.plans.map(row => parseReturnPlan(row, scope)));
      if (!current() || controller.signal.aborted) return; setPlans(values);
      setPlan(old => old ? values.find(row => row.id === old.id) ?? old : null);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, identity, refresh]);
  useEffect(() => {
    setBalance(null); if (!auth.session || !scope || plan?.operation !== "Return" || plan.phase !== 2) return; const controller = new AbortController();
    returnRequest(auth.session, scope, `${root}/${encodeURIComponent(plan.id)}/balance`, undefined, controller.signal).then(raw => {
      const value = parseRefundBalance(raw.balance, plan); if (current() && !controller.signal.aborted) setBalance(value);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); }); return () => controller.abort();
  }, [plan, auth.session, scope, refresh]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try {
      if (stepUp && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, auth.revision); }
    } catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  function apply(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    for (const [key, grants] of [["workspace_id", identity.workspaces], ["organization_id", identity.organizations], ["legal_entity_id", identity.entities]] as const)
      if (!scopeInput[key].trim() || (grants.length && !grants.includes(scopeInput[key]))) { setError("denied"); return; }
    setPlans([]); setPlan(null); setBalance(null); setScope({ ...scopeInput }); setError(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null);
    try {
      const raw = await returnRequest(auth.session, scope, command.path, command), value = await parseReturnPlan(raw.plan, scope);
      if (command.body.expected_plan_digest !== undefined && value.plan_digest !== command.body.expected_plan_digest) throw new Error("return_digest_mismatch");
      if (command.body.source_order_id !== undefined && value.source_order_id !== command.body.source_order_id) throw new Error("return_source_mismatch");
      if (command.path.endsWith("/refunds") && (value.operation !== "Refund" || value.amount_minor !== command.body.amount_minor || command.path !== `${root}/${value.return_id}/refunds`)) throw new Error("return_refund_mismatch");
      for (const [action, stage] of [["review", 1], ["post", 2], ["cancel", 3]] as const) if (command.path.endsWith(`/${action}`) && (value.phase !== stage || command.path !== `${root}/${value.id}/${action}`)) throw new Error("return_phase_mismatch");
      if (!current()) return;
      setPlan(value); setPlans(old => [value, ...old.filter(row => row.id !== value.id)]); setBalance(null); setPending(null); setReason(""); setRefresh(old => old + 1);
    } catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent) { event.preventDefault(); if (locked || !allowed("prepare")) return; try { void send(prepareScopedCommand(root, fields)); } catch { setError("invalid"); } }
  function prepareRefund(event: FormEvent) {
    event.preventDefault(); if (locked || !allowed("prepare") || !plan || !balance) return;
    if (!/^[1-9]\d{0,18}$/.test(refund.amount_minor) || BigInt(refund.amount_minor) > BigInt(balance.refund_due_minor)) { setError("invalid"); return; }
    void send(prepareScopedCommand(`${root}/${plan.id}/refunds`, refund));
  }
  const input = (label: Word, value: string, change: (value: string) => void, type = "text") => <label>{t(label)}<input required disabled={locked} maxLength={label === "reason" ? 500 : 160} type={type} value={value} onChange={event => change(event.target.value)} /></label>;
  const money = (value: string | undefined) => value !== undefined && plan ? `${formatExactDecimal(financeMoney(value, plan.currency_precision), locale)} ${plan.currency_code}` : "—";
  const independent = Boolean(plan && identity?.id !== plan.preparer_actor_id), third = independent && identity?.id !== plan?.reviewer_actor_id;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("duties")}</p></header>
    {error && <p role="alert" ref={alert} tabIndex={-1}>{t(error)}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("signIn")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin({ ...login, [key]: value }), key === "password" ? "password" : "text")}</div>)}<button disabled={locked}>{t("signIn")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => { if (!auth.session) return; setBusy(true); void endBrowserAdminSession(auth.session).then(() => { if (current()) auth.clear(auth.revision); }).catch(fail).finally(() => { if (current()) setBusy(false); }); }}>{t("signOut")}</button></section>
      {!identity?.stepUp && identity?.human && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin({ ...login, password: value }), "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={apply}>{(["workspace_id", "organization_id", "legal_entity_id"] as const).map(key => <div key={key}>{input(key, scopeInput[key], value => { setScopeInput({ ...scopeInput, [key]: value }); setScope(null); setPlans([]); setPlan(null); })}</div>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && has(READ) && <>
        <section className="panel"><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("select")}<select disabled={locked} value={plan?.id ?? ""} onChange={event => { setPlan(plans.find(row => row.id === event.target.value) ?? null); setError(null); }}><option value="">—</option>{plans.map(row => <option key={row.id} value={row.id}>{row.operation} · {row.status} · {row.id}</option>)}</select></label>{!plans.length && <p>{t("empty")}</p>}</section>
        {has(permissions.prepare) && <form className="panel reporting-form" aria-label={t("prepare")} onSubmit={prepare}>{(Object.keys(fields) as (keyof typeof fields)[]).map(key => <div key={key}>{input(key, fields[key], value => setFields({ ...fields, [key]: value }), key === "posting_date" ? "date" : "text")}</div>)}<button disabled={locked || !allowed("prepare")}>{t("prepare")}</button></form>}
        {plan && <section className="panel" aria-label={t("evidence")}><h2>{t("evidence")}</h2><p><bdi>{plan.operation} · {plan.status}</bdi> · <code dir="ltr">{plan.id}</code></p><p>{t("source_order_id")}: <code dir="ltr">{plan.source_order_id}</code> · <code dir="ltr">{plan.invoice_id}</code></p>
          {plan.operation === "Return" && <><p>{t("credit")}: <bdi>{money(plan.credit_minor)}</bdi></p><p>{t("cogs")}: <bdi>{money(plan.cogs_restored_minor)}</bdi></p><p>{t("entitlement")}: <bdi>{money(plan.refund_entitlement_minor)}</bdi></p>{balance && <p>{t("due")}: <bdi>{money(balance.refund_due_minor)}</bdi></p>}</>}
          <p><code dir="ltr">{plan.plan_digest}</code></p><p><bdi>{plan.preparer_actor_id} / {plan.reviewer_actor_id ?? "—"} / {plan.posted_actor_id ?? plan.cancelled_actor_id ?? "—"}</bdi></p>
          {plan.entries.map((entry, index) => <p key={entry.entry_id}><code dir="ltr">{entry.original_effect_id ?? "—"} → {entry.entry_id} → {plan.posting_effect_ids[index] ?? "—"}</code></p>)}
          {Object.entries(plan.evidence).filter(([, value]) => value).map(([key, value]) => <p key={key}><code dir="ltr">{key}: {value}</code></p>)}
          <details><summary>{t("evidence")}</summary><pre dir="ltr">{plan.canonical_plan_json}</pre></details>
          {[0, 1].includes(plan.phase) && <form aria-label={t(plan.phase === 0 ? "review" : "post")} onSubmit={event => { event.preventDefault(); const action = plan.phase === 0 ? "review" : "post"; if (!locked && allowed(action) && (action === "review" ? independent : third)) void send(prepareScopedCommand(`${root}/${plan.id}/${action}`, { expected_plan_digest: plan.plan_digest, reason })); }}>{input("reason", reason, setReason)}<button disabled={locked || !reason.trim() || !allowed(plan.phase === 0 ? "review" : "post") || !(plan.phase === 0 ? independent : third)}>{t(plan.phase === 0 ? "review" : "post")}</button><button type="button" disabled={locked || !reason.trim() || !allowed("cancel") || !third} onClick={() => void send(prepareScopedCommand(`${root}/${plan.id}/cancel`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("cancel")}</button></form>}
          {plan.phase === 3 && <p>{plan.cancellation_reason}</p>}
          {plan.operation === "Return" && plan.phase === 2 && balance && BigInt(balance.refund_due_minor) > 0n && has(permissions.prepare) && <form className="reporting-form" aria-label={t("refund")} onSubmit={prepareRefund}>{(Object.keys(refund) as (keyof typeof refund)[]).map(key => <div key={key}>{input(key, refund[key], value => setRefund({ ...refund, [key]: value }), key === "posting_date" ? "date" : "text")}</div>)}<button disabled={locked || !allowed("prepare")}>{t("refund")}</button></form>}
        </section>}
      </>}
    </>}
  </main>;
}
