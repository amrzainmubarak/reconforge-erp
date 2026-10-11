import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadExceptionReviewIdentity, type ExceptionReviewIdentity } from "../exception-review-data";
import { loadBudgetPage, loadBudgetDetail, type BudgetEnvelope } from "../budget-control-data";
import { procurementOptions, procurementScopes, type ProcurementScope, type ProcurementOptions } from "../procurement-data";
import { sourcingRoot, sourcingGet, sourcingList, sourcingCommand, verifySourcingCommandDetail, type SourcingDetail, type SourcingHead } from "../procurement-sourcing-data";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./ProcurementSourcingPage.css";

export function ProcurementSourcingPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <SourcingSession key={auth.revision} locale={locale} />;
}
function SourcingSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), ar = locale === "ar", say = (en: string, arabic: string) => ar ? arabic : en;
  const [tenant, setTenant] = useState(""), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<ExceptionReviewIdentity | null>(null), [workspace, setWorkspace] = useState("");
  const [scopes, setScopes] = useState<ProcurementScope[]>([]), [scope, setScope] = useState<ProcurementScope | null>(null);
  const [options, setOptions] = useState<ProcurementOptions | null>(null), [budgets, setBudgets] = useState<BudgetEnvelope[]>([]), [budgetId, setBudgetId] = useState("");
  const [records, setRecords] = useState<SourcingHead[]>([]), [detail, setDetail] = useState<SourcingDetail | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({ number: "", supplier_code: "", posting_date: "", period_id: "", journal_code: "", ap_account_code: "", cash_account_code: "" });
  const [lines, setLines] = useState([{ item_code: "", quantity: "", unit_price_minor: "", location_code: "", policy_code: "", requirement_id: "", requirement_digest: "" }]);
  const [reason, setReason] = useState(""), [supplier, setSupplier] = useState(""), [expiry, setExpiry] = useState(""), [prices, setPrices] = useState<string[]>([]);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState(""), [refresh, setRefresh] = useState(0);
  const alive = useRef(true), lock = useRef(false), current = () => alive.current && auth.isCurrent(auth.revision);
  const locked = busy || pending !== null, permitted = (name: string) => !!identity?.human && identity.permissions.includes(name) && !!auth.stepUpExpiresAt;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    if (caught instanceof AdminApiError && caught.status === 403) { setDetail(null); setRecords([]); setBudgets([]); setOptions(null); }
    setError(caught instanceof AdminApiError && caught.status < 500 ? say("Current authority or retained version refused the request. Refresh the source before another action.", "رفضت الصلاحية الحالية أو الإصدار المحفوظ الطلب. حدّث المصدر قبل إجراء آخر.") : say("The result is unconfirmed. Retry the retained exact command and inspect its evidence.", "لم تتأكد النتيجة. أعد الأمر المحفوظ نفسه وافحص أدلته."));
  }
  useEffect(() => {
    if (!auth.session) return;
    const c = new AbortController();
    loadExceptionReviewIdentity(auth.session, c.signal).then(value => { if (!c.signal.aborted && current()) { setIdentity(value); setWorkspace(value.workspaces[0] ?? ""); } }).catch(e => { if (!c.signal.aborted) fail(e); });
    return () => c.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    setScope(null); setScopes([]); setDetail(null); setRecords([]); setOptions(null); setBudgets([]); setBudgetId("");
    if (!auth.session || !workspace) return;
    const c = new AbortController();
    procurementScopes(auth.session, workspace, c.signal).then(value => { if (!c.signal.aborted && current()) setScopes(value); }).catch(e => { if (!c.signal.aborted) fail(e); });
    return () => c.abort();
  }, [workspace, auth.session]);
  useEffect(() => {
    if (!auth.session || !scope) return;
    const c = new AbortController();
    const budgetScope = { workspace_id: scope.workspace_id, organization_id: scope.organization_id, legal_entity_id: scope.legal_entity_id };
    Promise.all([procurementOptions(auth.session, scope, c.signal), sourcingList(auth.session, scope, c.signal), loadBudgetPage(auth.session, budgetScope, 0, c.signal)]).then(([refs, sources, budgetPage]) => {
      if (!c.signal.aborted && current()) { setOptions(refs); setRecords(sources); setBudgets(budgetPage.envelopes.filter(b => b.status === "Approved" && b.currency_code === scope.currency_code)); }
    }).catch(e => { if (!c.signal.aborted) fail(e); });
    return () => c.abort();
  }, [auth.session, scope, refresh]);
  async function authentication(event: FormEvent, elevated = false) {
    event.preventDefault(); if (lock.current || pending) return; lock.current = true; setBusy(true); setError("");
    try {
      if (elevated && auth.session) { const expiry = await stepUpBrowserAdminSession(auth.session, password); if (current()) auth.elevate(expiry, auth.revision); }
      else { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    } catch (e) { fail(e); } finally { lock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function inspect(id: string) {
    if (!auth.session || !scope || locked || lock.current) return;
    lock.current = true; setBusy(true); setError(""); setDetail(null);
    try { const value = await sourcingGet(auth.session, scope, id); if (current()) { setDetail(value); setPrices(value.source.request.order.lines.map(l => l.unit_price_minor)); setExpiry(value.source.request.order.posting_date); } }
    catch (e) { fail(e); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return;
    lock.current = true; setBusy(true); setPending(command); setError("");
    try {
      const head = await sourcingCommand(auth.session, scope, command);
      if (!current()) return;
      const value = await sourcingGet(auth.session, scope, head.id);
      verifySourcingCommandDetail(value, head, command);
      if (current()) { setDetail(value); setPrices(value.source.request.order.lines.map(l => l.unit_price_minor)); setExpiry(value.source.request.order.posting_date); setPending(null); setRefresh(v => v + 1); }
    } catch (e) {
      if (!current()) return;
      if (e instanceof AdminApiError && e.status < 500) { setPending(null); setDetail(null); setRefresh(v => v + 1); }
      fail(e);
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault(); if (!scope || locked || !budgetId || !reason.trim()) return;
    const requirements = lines.map(l => l.requirement_id || l.requirement_digest ? { requirement_id: l.requirement_id, requirement_digest: l.requirement_digest } : null);
    void send(prepareScopedCommand(sourcingRoot, { ...draft, workspace: scope.workspace_id, organization_code: scope.organization_code, entity_code: scope.entity_code,
      currency_code: scope.currency_code, budget_id: budgetId, reason, lines: lines.map(({ requirement_id: _id, requirement_digest: _digest, ...line }) => line), requirements }));
  }
  async function act(operation: string) {
    if (!detail || !scope || !auth.session || locked || !reason.trim()) return;
    if (operation !== "award") {
      void send(prepareScopedCommand(sourcingRoot + "/" + encodeURIComponent(detail.head.id) + "/" + operation, { expected_version: detail.head.row_version, reason })); return;
    }
    lock.current = true; setBusy(true); setError("");
    try {
      const budget = await loadBudgetDetail(auth.session, { workspace_id: scope.workspace_id, organization_id: scope.organization_id, legal_entity_id: scope.legal_entity_id }, detail.head.budget_id);
      if (current()) {
        lock.current = false; setBusy(false);
        await send(prepareScopedCommand(sourcingRoot + "/" + encodeURIComponent(detail.head.id) + "/award", { expected_version: detail.head.row_version, expected_budget_version: budget.row_version, reason }));
      }
    } catch (e) { fail(e); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function quote(event: FormEvent) {
    event.preventDefault(); if (!detail || locked || !reason.trim()) return;
    void send(prepareScopedCommand(sourcingRoot + "/" + encodeURIComponent(detail.head.id) + "/quotes", {
      expected_version: detail.head.row_version, supplier_code: supplier, unit_prices_minor: prices, valid_until: expiry, reason,
    }));
  }
  const select = (label: string, value: string, choices: { code: string; name?: string }[], update: (v: string) => void) =>
    <label>{label}<select required value={value} onChange={e => update(e.target.value)}><option value="">{say("Select", "اختر")}</option>{choices.map(o => <option key={o.code} value={o.code}>{o.code} {o.name ?? ""}</option>)}</select></label>;
  const independent = !!detail && identity?.id !== detail.head.creator_actor_id;
  const reviewer = independent && !detail?.quotations.some(q => q.payload.registrar_actor_id === identity?.id);
  const awarder = independent && ![detail?.head.rfq_approver_actor_id, detail?.head.selection_reviewer_actor_id, detail?.quotations.find(q => q.id === detail.head.selected_quote_id)?.payload.registrar_actor_id].includes(identity?.id);
  return <section className="procurement-sourcing-page" aria-label={say("Procurement sourcing", "طلبات الشراء والمنافسات")}>
    <h2>{say("Procurement sourcing", "طلبات الشراء والمنافسات")}</h2>
    <p>{say("Retain exact demand, supplier offers and an independently reviewed lowest-cost selection. A third human publishes the existing budget-backed purchase order.", "احفظ الاحتياج وعروض الموردين واختيار أقل تكلفة بمراجعة مستقلة. ينشر شخص ثالث أمر الشراء المرتبط بالاعتماد القائم.")}</p>
    <p>{say("Scope: functional currency, zero tax, base units, 128 lines and 32 retained suppliers. Sourcing creates no stock or payable until native receiving and accrual. Manufacturing links refer to original requirements, without asserting a net shortage.", "النطاق: العملة الوظيفية وضريبة صفر والوحدات الأساسية و١٢٨ بندًا و٣٢ موردًا. لا ينشأ مخزون أو التزام مورد قبل الاستلام والاستحقاق القائمين. تشير روابط التصنيع إلى الاحتياجات الأصلية دون ادعاء عجز صافٍ.")}</p>
    {error && <p role="alert">{error}</p>}
    {!auth.session ? <form onSubmit={e => void authentication(e)} aria-label={say("Sign in to sourcing", "دخول المشتريات")}>
      <label>{say("Tenant ID", "المستأجر")}<input required value={tenant} onChange={e => setTenant(e.target.value)} /></label>
      <label>{say("Username", "المستخدم")}<input required autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label>
      <label>{say("Password", "كلمة المرور")}<input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
      <button disabled={busy}>{say("Sign in", "دخول")}</button>
    </form> : <>
      <p>{auth.username}</p>
      {!auth.stepUpExpiresAt && <form onSubmit={e => void authentication(e, true)} aria-label={say("Confirm privileged access", "تأكيد الوصول المميز")}><label>{say("Password", "كلمة المرور")}<input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label><button disabled={locked}>{say("Confirm access", "تأكيد الوصول")}</button></form>}
      <button disabled={locked} onClick={() => { if (auth.session) void endBrowserAdminSession(auth.session).then(() => { if (current()) auth.clear(auth.revision); }).catch(fail); }}>{say("Sign out", "خروج")}</button>
      <fieldset disabled={locked}><legend>{say("Current enterprise scope", "النطاق المؤسسي الحالي")}</legend>
        <label>{say("Workspace", "مساحة العمل")}<select value={workspace} onChange={e => setWorkspace(e.target.value)}><option value="">{say("Select", "اختر")}</option>{identity?.workspaces.map(w => <option key={w}>{w}</option>)}</select></label>
        <label>{say("Organization and legal entity", "المؤسسة والكيان القانوني")}<select value={scope?.legal_entity_id ?? ""} onChange={e => { setDetail(null); setRecords([]); setOptions(null); setBudgets([]); setBudgetId(""); setScope(scopes.find(s => s.legal_entity_id === e.target.value) ?? null); }}><option value="">{say("Select", "اختر")}</option>{scopes.map(s => <option key={s.legal_entity_id} value={s.legal_entity_id}>{s.organization_name} · {s.entity_name} · {s.currency_code}</option>)}</select></label>
      </fieldset>
      {scope && <button disabled={locked} onClick={() => { setError(""); setRefresh(v => v + 1); }}>{say("Refresh requisitions", "تحديث طلبات الشراء")}</button>}
      <ul>{records.map(head => <li key={head.id}><button disabled={locked} onClick={() => void inspect(head.id)}>{say("Open ", "فتح ")}{head.number}</button> <bdi>{head.status} · {head.ceiling_minor} {head.currency_code}</bdi></li>)}</ul>
      {pending && !busy && <aside role="status"><code>{pending.body.command_id}</code><button onClick={() => void send(pending)}>{say("Retry exact sourcing command", "إعادة أمر الشراء نفسه")}</button></aside>}
      {scope && options && <details><summary>{say("New purchase requisition", "طلب شراء جديد")}</summary>
        <form aria-label={say("New purchase requisition", "طلب شراء جديد")} onSubmit={create}><fieldset disabled={locked || !permitted("procurement_sourcing.manage")}><legend>{say("Retained original demand", "الاحتياج الأصلي المحفوظ")}</legend>
          <label>{say("Requisition number", "رقم الطلب")}<input required maxLength={30} pattern="SRC5-.+" value={draft.number} onChange={e => setDraft({ ...draft, number: e.target.value })} /></label>
          <label>{say("Posting date", "تاريخ الترحيل")}<input required type="date" value={draft.posting_date} onChange={e => setDraft({ ...draft, posting_date: e.target.value })} /></label>
          <label>{say("Approved appropriation", "الاعتماد الموافق عليه")}<select required value={budgetId} onChange={e => { setBudgetId(e.target.value); const b = budgets.find(b => b.id === e.target.value); if (b) setDraft({ ...draft, period_id: b.period_id }); }}><option value="">{say("Select", "اختر")}</option>{budgets.map(b => <option key={b.id} value={b.id}>{b.budget_code} · {b.available_minor} {b.currency_code}</option>)}</select></label>
          {select(say("Reference supplier", "المورد المرجعي"), draft.supplier_code, options.suppliers, v => setDraft({ ...draft, supplier_code: v }))}
          {select(say("Open fiscal period", "الفترة المفتوحة"), draft.period_id, options.periods.map(p => ({ code: p.id, name: p.name })), v => setDraft({ ...draft, period_id: v }))}
          {select(say("Accrual and payment journal", "دفتر الاستحقاق والسداد"), draft.journal_code, options.journals, v => setDraft({ ...draft, journal_code: v }))}
          {select(say("Accounts payable", "حساب الموردين"), draft.ap_account_code, options.accounts, v => setDraft({ ...draft, ap_account_code: v }))}
          {select(say("Cash account", "الحساب النقدي"), draft.cash_account_code, options.accounts, v => setDraft({ ...draft, cash_account_code: v }))}
          {lines.map((line, index) => {
            const update = (key: string, value: string) => setLines(lines.map((row, n) => n === index ? { ...row, [key]: value } : row));
            return <fieldset key={index}><legend>{say("Demand line ", "بند الاحتياج ")}{index + 1}</legend>
              {select(say("Item ", "الصنف ") + (index + 1), line.item_code, options.items, v => update("item_code", v))}
              <label>{say("Quantity ", "الكمية ") + (index + 1)}<input required inputMode="decimal" pattern="[0-9]+(\.[0-9]+)?" value={line.quantity} onChange={e => update("quantity", e.target.value)} /></label>
              <label>{say("Ceiling unit price in minor units ", "سعر الوحدة الأقصى بأصغر وحدة نقدية ") + (index + 1)}<input required inputMode="numeric" pattern="[1-9][0-9]*" value={line.unit_price_minor} onChange={e => update("unit_price_minor", e.target.value)} /></label>
              {select(say("Receiving location ", "موقع الاستلام ") + (index + 1), line.location_code, options.locations, v => update("location_code", v))}
              {select(say("FIFO valuation policy ", "سياسة FIFO ") + (index + 1), line.policy_code, options.policies, v => update("policy_code", v))}
              <details><summary>{say("Original manufacturing requirement", "احتياج التصنيع الأصلي")}</summary><label>{say("Requirement ID ", "معرف الاحتياج ") + (index + 1)}<input value={line.requirement_id} onChange={e => update("requirement_id", e.target.value)} /></label><label>{say("Requirement digest ", "بصمة الاحتياج ") + (index + 1)}<input maxLength={64} value={line.requirement_digest} onChange={e => update("requirement_digest", e.target.value)} /></label></details>
            </fieldset>;
          })}
          <button type="button" disabled={lines.length >= 128} onClick={() => setLines([...lines, { item_code: "", quantity: "", unit_price_minor: "", location_code: "", policy_code: "", requirement_id: "", requirement_digest: "" }])}>{say("Add demand line", "إضافة بند")}</button>
          <label>{say("Creation reason", "سبب الإنشاء")}<input required maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label>
          <button>{say("Create requisition", "إنشاء طلب الشراء")}</button>
        </fieldset></form>
      </details>}
      {detail && <section aria-label={say("Original sourcing evidence", "أدلة مصدر الشراء")}><h3>{detail.head.number}</h3>
        <p role="status">{say(detail.head.status, { Draft: "مسودة", OpenRFQ: "المنافسة مفتوحة", SelectionReviewed: "تمت مراجعة الاختيار", Awarded: "تمت الترسية", Cancelled: "ملغى" }[detail.head.status])}</p>
        <dl><div><dt>{say("Original ceiling in minor units", "السقف الأصلي بأصغر وحدة نقدية")}</dt><dd><bdi>{detail.head.ceiling_minor} {detail.head.currency_code}</bdi></dd></div><div><dt>{say("Original source digest", "بصمة المصدر الأصلي")}</dt><dd><code>{detail.head.source_digest}</code></dd></div><div><dt>{say("Audit event", "حدث المراجعة")}</dt><dd><code>{detail.head.evidence.audit_event_id}</code></dd></div><div><dt>{say("Outbox event", "حدث النشر")}</dt><dd><code>{detail.head.evidence.outbox_event_id}</code></dd></div></dl>
        <button disabled={locked} onClick={() => void inspect(detail.head.id)}>{say("Refresh this requisition", "تحديث هذا الطلب")}</button>
        <label>{say("Review or award reason", "سبب المراجعة أو الترسية")}<input disabled={locked} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label>
        {detail.head.status === "Draft" && <button disabled={locked || !reason.trim() || !independent || !permitted("procurement_sourcing.approve")} onClick={() => void act("open-rfq")}>{say("Open RFQ independently", "فتح المنافسة بمراجعة مستقلة")}</button>}
        {detail.head.status === "OpenRFQ" && <form aria-label={say("Retain supplier quotation", "حفظ عرض المورد")} onSubmit={quote}><fieldset disabled={locked || !permitted("procurement_sourcing.manage")}><legend>{say("Original supplier offer", "عرض المورد الأصلي")}</legend>
          {select(say("Quotation supplier", "مورد العرض"), supplier, options?.suppliers.filter(s => !detail.quotations.some(q => q.payload.order.supplier_code === s.code)) ?? [], setSupplier)}
          <label>{say("Offer valid until", "صلاحية العرض")}<input required type="date" value={expiry} onChange={e => setExpiry(e.target.value)} /></label>
          {detail.source.request.order.lines.map((line, index) => <label key={index}>{say("Quoted unit price in minor units ", "سعر الوحدة بالعرض بأصغر وحدة نقدية ") + (index + 1)} · {line.item_code}<input required inputMode="numeric" pattern="[1-9][0-9]*" value={prices[index] ?? ""} onChange={e => setPrices(prices.map((p, n) => n === index ? e.target.value : p))} /></label>)}
          <button disabled={!reason.trim() || detail.quotations.length >= 32}>{say("Retain exact supplier offer", "حفظ العرض الأصلي")}</button>
        </fieldset></form>}
        <ul aria-label={say("Retained quotation set", "العروض المحفوظة")}>{detail.quotations.map(q => <li key={q.id}><bdi>{q.payload.order.supplier_code} · {q.payload.total_minor} {detail.head.currency_code}</bdi> {detail.head.selected_quote_id === q.id && <strong>{say("Reviewed winner", "العرض المختار بالمراجعة")}</strong>}<code>{q.quote_digest}</code></li>)}</ul>
        {detail.head.status === "OpenRFQ" && <button disabled={locked || !reason.trim() || !reviewer || !detail.quotations.length || !permitted("procurement_sourcing.approve")} onClick={() => void act("review-selection")}>{say("Review deterministic lowest-cost selection", "مراجعة اختيار أقل تكلفة")}</button>}
        {detail.head.status === "SelectionReviewed" && <button disabled={locked || !reason.trim() || !awarder || !permitted("procurement_sourcing.award") || !permitted("budget_control.manage") || !permitted("payables.manage")} onClick={() => void act("award")}>{say("Award native budget-backed purchase", "ترسية أمر الشراء المرتبط بالاعتماد")}</button>}
        {!["Awarded", "Cancelled"].includes(detail.head.status) && <button disabled={locked || !reason.trim() || !independent || !permitted("procurement_sourcing.approve")} onClick={() => void act("cancel")}>{say("Cancel retained requisition", "إلغاء الطلب مع حفظ الأدلة")}</button>}
        {detail.head.order_id && <p>{say("Native purchase order", "أمر الشراء القائم")}: <code>{detail.head.order_id}</code> · <bdi>{"BPC1-" + detail.head.number}</bdi><br />{say("Open Partial procurement to submit, approve, receive, accrue, consume the appropriation and settle this original order.", "افتح المشتريات الجزئية لإرسال الأمر والموافقة والاستلام والترحيل واستهلاك الاعتماد وتسوية الأمر الأصلي.")}</p>}
      </section>}
    </>}
  </section>;
}

