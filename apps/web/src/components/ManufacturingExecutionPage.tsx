import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { applyManufacturingCompletion, manufacturingRequest, parseManufacturing, type ManufacturingSource } from "../manufacturing-execution-data";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

const words = {
  title: ["Actual manufacturing execution", "التنفيذ الصناعي بالتكلفة الفعلية"],
  boundary: ["Versioned base-UOM recipes, whole component issue, native WIP, partial finished output and explicit abnormal material scrap. One functional currency; no routing, labor, overhead or MRP.", "وصفات بإصدارات ووحدات أصلية دقيقة، إصدار كامل للمكونات، إنتاج تحت التشغيل، إنتاج جيد جزئي وهالك مواد غير عادي صريح. عملة وظيفية واحدة؛ دون مسارات أو أجور أو تحميل أو MRP."],
  duties: ["An independent BOM approver and three distinct authorized humans for each material issue or output posting.", "مراجع مستقل للوصفة وثلاثة أشخاص مختلفين لديهم الصلاحيات لكل إصدار مواد أو ترحيل إنتاج."],
  tenant: ["Tenant", "المؤسسة"], username: ["Username", "المستخدم"], password: ["Password", "كلمة المرور"], signIn: ["Sign in", "تسجيل الدخول"], signOut: ["Sign out", "تسجيل الخروج"], stepUp: ["Verify financial authority", "تأكيد الصلاحية المالية"],
  workspace_id: ["Workspace ID", "معرّف مساحة العمل"], organization_id: ["Organization ID", "معرّف المنظمة"], legal_entity_id: ["Legal entity ID", "معرّف الكيان القانوني"], apply: ["Apply scope", "تطبيق النطاق"], refresh: ["Refresh native production evidence", "تحديث أدلة الإنتاج الأصلية"],
  bom: ["Retained BOM version", "إصدار الوصفة المحفوظ"], order: ["Retained production order", "أمر الإنتاج المحفوظ"], child: ["Retained output disposition", "توزيع الإنتاج المحفوظ"],
  number: ["Document number", "رقم المستند"], version: ["BOM version", "إصدار الوصفة"], output_item_code: ["Finished item code", "رمز المنتج النهائي"], output_quantity: ["Exact planned output quantity", "كمية الإنتاج المخططة الدقيقة"], item_code: ["Component item code", "رمز المكوّن"], quantity: ["Exact base-UOM component quantity", "كمية المكوّن الدقيقة بوحدته الأصلية"], add: ["Add component", "إضافة مكوّن"],
  prepareBom: ["Prepare versioned BOM", "إعداد وصفة بإصدار"], approveBom: ["Approve exact BOM", "اعتماد الوصفة الدقيقة"], createOrder: ["Reserve whole material order", "حجز أمر المواد بالكامل"],
  component_location_code: ["Component location code", "رمز موقع المكونات"], finished_location_code: ["Finished location code", "رمز موقع المنتج"], component_policy_code: ["Component FIFO policy", "سياسة FIFO للمكونات"], finished_policy_code: ["Finished FIFO policy with WIP offset", "سياسة FIFO للمنتج بمقابل إنتاج تحت التشغيل"], journal_code: ["Native journal code", "رمز اليومية الأصلية"], wip_account_code: ["WIP asset account", "حساب أصل الإنتاج تحت التشغيل"], scrap_account_code: ["Abnormal scrap expense account", "حساب مصروف الهالك غير العادي"], period_id: ["Open fiscal period ID", "معرّف الفترة المالية المفتوحة"], posting_date: ["Posting date", "تاريخ الترحيل"], reason: ["Reason", "السبب"],
  prepare: ["Prepare original FIFO material issue", "إعداد إصدار FIFO الأصلي للمكونات"], review: ["Review complete native source", "مراجعة المصدر الأصلي الكامل"], post: ["Post complete native effects", "ترحيل الآثار الأصلية بالكامل"], cancel: ["Cancel unposted source", "إلغاء المصدر غير المرحّل"], completion: ["Prepare partial good output and abnormal scrap", "إعداد إنتاج جيد جزئي وهالك غير عادي"], good_quantity: ["Exact good output quantity", "كمية الإنتاج الجيد الدقيقة"], scrap_quantity: ["Exact abnormal scrap quantity", "كمية الهالك غير العادي الدقيقة"],
  evidence: ["Original production and native financial evidence", "أدلة الإنتاج الأصلي والآثار المالية"], retry: ["Retry retained command", "إعادة الأمر المحفوظ"], unknown: ["Response was lost. Retry the same retained command with the same human.", "فُقد الرد. أعد الأمر المحفوظ نفسه بالشخص نفسه."], invalid: ["The request or native production evidence is invalid.", "الطلب أو دليل الإنتاج الأصلي غير صالح."], denied: ["Current authority refused this operation.", "الصلاحية الحالية رفضت العملية."], unavailable: ["Native production evidence is unavailable.", "أدلة الإنتاج الأصلية غير متاحة."],
} as const;
type Word = keyof typeof words;
const READ = ["manufacturing_execution.read", "inventory.read", "finance_core.read"], root = "/api/v1/manufacturing-execution";
const permissions = { create: [...READ, "manufacturing_execution.manage", "inventory.manage"], prepare: [...READ, "manufacturing_execution.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"], review: [...READ, "manufacturing_execution.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"], post: [...READ, "manufacturing_execution.post", "inventory.post", "inventory.valuation.approve", "finance_core.post"], cancel: [...READ, "manufacturing_execution.approve"] };
export function ManufacturingExecutionPage({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <ProductionSession key={auth.revision} locale={locale} />; }
function ProductionSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: Word) => words[key][locale === "ar" ? 1 : 0];
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [boms, setBoms] = useState<ManufacturingSource[]>([]), [orders, setOrders] = useState<ManufacturingSource[]>([]), [bom, setBom] = useState<ManufacturingSource | null>(null), [order, setOrder] = useState<ManufacturingSource | null>(null), [child, setChild] = useState<ManufacturingSource | null>(null);
  const orderRef = useRef<ManufacturingSource | null>(null); orderRef.current = order;
  const [recipe, setRecipe] = useState({ number: "", version: "1", output_item_code: "", output_quantity: "", reason: "" }), [components, setComponents] = useState([{ item_code: "", quantity: "" }]);
  const [fields, setFields] = useState({ number: "", output_quantity: "", component_location_code: "", finished_location_code: "", component_policy_code: "", finished_policy_code: "", journal_code: "", wip_account_code: "", scrap_account_code: "", period_id: "", posting_date: "", reason: "" });
  const [output, setOutput] = useState({ good_quantity: "", scrap_quantity: "0", period_id: "", posting_date: "", reason: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<"invalid" | "denied" | "unavailable" | "unknown" | null>(null), [refresh, setRefresh] = useState(0);
  const lock = useRef(false), generation = auth.revision, current = () => auth.isCurrent(generation), locked = busy || pending !== null;
  const has = (required: string[]) => required.every(value => identity?.permissions.includes(value));
  const allowed = (operation: keyof typeof permissions) => Boolean(scope && identity?.human && identity.stepUp && has(permissions[operation]));
  function fail(caught: unknown) { if (current()) setError(caught instanceof AdminApiError && [401, 403].includes(caught.status) ? "denied" : caught instanceof AdminApiError ? "unavailable" : "invalid"); }
  useEffect(() => {
    if (!auth.session) return; const abort = new AbortController();
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current() && !abort.signal.aborted) { setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); setIdentity(value); } }).catch(caught => { if (!abort.signal.aborted) fail(caught); });
    return () => abort.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !has(READ)) return; const abort = new AbortController();
    manufacturingRequest(auth.session, scope, `${root}/orders`, undefined, abort.signal).then(async raw => {
      if (!Array.isArray(raw.boms) || !Array.isArray(raw.orders) || raw.boms.length > 200 || raw.orders.length > 200) throw new Error("invalid_page");
      const [recipes, sources] = await Promise.all([Promise.all(raw.boms.map(row => parseManufacturing(row, scope))), Promise.all(raw.orders.map(row => parseManufacturing(row, scope)))]);
      if (!current() || abort.signal.aborted) return; setBoms(recipes); setOrders(sources); setBom(old => recipes.find(row => row.id === old?.id) ?? null); setOrder(old => sources.find(row => row.id === old?.id) ?? null); setChild(old => sources.flatMap(row => row.completions ?? []).find(row => row.id === old?.id) ?? null);
    }).catch(caught => { if (!abort.signal.aborted) fail(caught); }); return () => abort.abort();
  }, [auth.session, scope, identity, refresh]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { if (stepUp && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, generation); }
    } catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  async function signOut() {
    if (!auth.session || locked || lock.current) return;
    lock.current = true; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(generation); }
    catch (caught) { fail(caught); }
    finally { lock.current = false; if (current()) setBusy(false); }
  }
  function apply(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    for (const [key, grants] of [["workspace_id", identity.workspaces], ["organization_id", identity.organizations], ["legal_entity_id", identity.entities]] as const) if (!scopeInput[key] || grants.length && !grants.includes(scopeInput[key])) { setError("denied"); return; }
    setScope({ ...scopeInput }); setBoms([]); setOrders([]); setBom(null); setOrder(null); setChild(null); setError(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null);
    try {
      const raw = await manufacturingRequest(auth.session, scope, command.path, command), value = await parseManufacturing(raw.bom ?? raw.order ?? raw.completion, scope);
      if (command.body.expected_digest !== undefined && command.body.expected_digest !== value.source_digest) throw new Error("digest_mismatch");
      for (const action of ["prepare", "review", "post", "cancel", "approve"] as const) if (command.path.endsWith(`/${action}`) && !command.path.includes(`/${value.id}/`)) throw new Error("owner_mismatch");
      const childResponse = value.id.startsWith("ME1C-");
      for (const [action, expected] of [["prepare", 1], ["review", childResponse ? 1 : 2], ["post", childResponse ? 2 : 3], ["cancel", childResponse ? 3 : 5], ["approve", 1]] as const)
        if (command.path.endsWith(`/${action}`) && value.phase !== expected) throw new Error("phase_mismatch");
      if (!current()) return;
      if (value.id.startsWith("ME1B-")) { setBom(value); setBoms(old => [value, ...old.filter(row => row.id !== value.id)]); }
      else if (value.id.startsWith("ME1C-")) {
        if (!orderRef.current) throw new Error("parent_missing");
        const parent = applyManufacturingCompletion(orderRef.current, value);
        setChild(parent.completions?.find(row => row.id === value.id) ?? value);
        setOrder(old => old?.id === parent.id ? applyManufacturingCompletion(old, value) : old);
        setOrders(old => old.some(row => row.id === parent.id) ? old.map(row => row.id === parent.id ? applyManufacturingCompletion(row, value) : row) : [parent, ...old]);
      }
      else { setOrder(value); setOrders(old => [value, ...old.filter(row => row.id !== value.id)]); }
      setPending(null); setReason(""); setRefresh(old => old + 1);
    } catch (caught) { if (current()) { if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught); } } }
    finally { lock.current = false; if (current()) setBusy(false); }
  }
  function submit(path: string, values: Record<string, ScopedJsonValue>) { try { void send(prepareScopedCommand(path, values)); } catch { setError("invalid"); } }
  const input = (key: Word, value: string, change: (v: string) => void, disabled = false) => <label>{t(key)}<input required disabled={locked || disabled} value={value} maxLength={key === "reason" ? 500 : 160} type={key === "password" ? "password" : key === "posting_date" ? "date" : "text"} onChange={event => change(event.target.value)} /></label>;
  const selected = child ?? order, canReview = selected && identity?.id !== (child?.preparer_actor_id ?? order?.issue_plan?.preparer_actor_id), canPost = canReview && identity?.id !== (child?.reviewer_id ?? order?.issue_reviewer_id);
  const phaseAction = selected ? child ? selected.phase === 0 ? "review" : selected.phase === 1 ? "post" : null : selected.phase === 0 ? "prepare" : selected.phase === 1 ? "review" : selected.phase === 2 ? "post" : null : null;
  const sourcePath = child ? `${root}/completions/${child.id}` : order ? `${root}/orders/${order.id}` : "";
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("duties")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("signIn")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked}>{t("signIn")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => void signOut()}>{t("signOut")}</button></section>
      {!identity?.stepUp && identity?.human && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin(old => ({ ...old, password: value })))}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={apply}>{(["workspace_id", "organization_id", "legal_entity_id"] as const).map(key => <div key={key}>{input(key, scopeInput[key], value => { setScopeInput(old => ({ ...old, [key]: value })); setScope(null); setOrder(null); setChild(null); }, !identity)}</div>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && has(READ) && <>
        <section className="panel"><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("bom")}<select disabled={locked} value={bom?.id ?? ""} onChange={event => setBom(boms.find(row => row.id === event.target.value) ?? null)}><option value="">—</option>{boms.map(row => <option key={row.id} value={row.id}>{String(row.number)} v{String(row.version)} · {row.phase}</option>)}</select></label><label>{t("order")}<select disabled={locked} value={order?.id ?? ""} onChange={event => { setOrder(orders.find(row => row.id === event.target.value) ?? null); setChild(null); }}><option value="">—</option>{orders.map(row => <option key={row.id} value={row.id}>{String(row.number)} · {row.phase} · {row.id}</option>)}</select></label></section>
        {has(permissions.create) && <form className="panel reporting-form" aria-label={t("prepareBom")} onSubmit={event => { event.preventDefault(); if (allowed("create") && /^[1-9]\d{0,14}$/.test(recipe.version)) submit(`${root}/boms`, { ...recipe, version: Number(recipe.version), components }); }}>{(Object.keys(recipe) as (keyof typeof recipe)[]).map(key => <div key={key}>{input(key, recipe[key], value => setRecipe(old => ({ ...old, [key]: value })))}</div>)}{components.map((line, index) => <fieldset key={index}><legend>{index + 1}</legend>{(["item_code", "quantity"] as const).map(key => <div key={key}>{input(key, line[key], value => setComponents(old => old.map((item, position) => position === index ? { ...item, [key]: value } : item)))}</div>)}</fieldset>)}<button type="button" disabled={locked || components.length >= 100} onClick={() => setComponents(old => [...old, { item_code: "", quantity: "" }])}>{t("add")}</button><button disabled={locked || !allowed("create")}>{t("prepareBom")}</button></form>}
        {bom?.phase === 0 && <form className="panel reporting-form" aria-label={t("approveBom")} onSubmit={event => { event.preventDefault(); submit(`${root}/boms/${bom.id}/approve`, { expected_digest: bom.source_digest, reason }); }}>{input("reason", reason, setReason)}<button disabled={locked || !reason.trim() || identity?.id === bom.creator_id || !identity?.human || !identity.stepUp || !has([...READ, "manufacturing_execution.approve"])}>{t("approveBom")}</button></form>}
        {bom?.phase === 1 && has(permissions.create) && <form className="panel reporting-form" aria-label={t("createOrder")} onSubmit={event => { event.preventDefault(); if (allowed("create")) submit(`${root}/orders`, { ...fields, bom_version_id: bom.id }); }}>{(Object.keys(fields) as (keyof typeof fields)[]).map(key => <div key={key}>{input(key, fields[key], value => setFields(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked || !allowed("create")}>{t("createOrder")}</button></form>}
        {order && <section className="panel" aria-label={t("evidence")}><h2>{t("evidence")}</h2><code dir="ltr">{order.id} · {order.source_digest}</code><p>WIP: <bdi>{order.issue_plan && [3, 4].includes(order.phase) ? (BigInt(order.issue_plan.total_cost_minor) - BigInt(order.released_cost_minor ?? "0")).toString() : "0"}</bdi> · {order.currency_code} · <code>{order.issue_effect_id}</code></p><label>{t("child")}<select disabled={locked} value={child?.id ?? ""} onChange={event => setChild(order.completions?.find(row => row.id === event.target.value) ?? null)}><option value="">—</option>{order.completions?.map(row => <option key={row.id} value={row.id}>{row.id} · {row.phase}</option>)}</select></label><pre dir="ltr">{JSON.stringify(child ?? order, null, 2)}</pre>
          {(phaseAction || child && child.phase < 2 || !child && order.phase < 3) && <form className="reporting-form" aria-label={t(phaseAction ?? "cancel")} onSubmit={event => { event.preventDefault(); if (phaseAction && allowed(phaseAction)) submit(`${sourcePath}/${phaseAction}`, { expected_digest: selected!.source_digest, reason }); }}>{input("reason", reason, setReason)}{phaseAction && <button disabled={locked || !reason.trim() || !allowed(phaseAction) || phaseAction === "review" && !canReview || phaseAction === "post" && !canPost}>{t(phaseAction)}</button>}<button type="button" disabled={locked || !reason.trim() || !allowed("cancel") || identity?.id === (child?.preparer_actor_id ?? order.creator_id)} onClick={() => submit(`${sourcePath}/cancel`, { expected_digest: selected!.source_digest, reason })}>{t("cancel")}</button></form>}
        </section>}
        {order?.phase === 3 && !order.completions?.some(row => row.phase < 2) && has(permissions.prepare) && <form className="panel reporting-form" aria-label={t("completion")} onSubmit={event => { event.preventDefault(); if (allowed("prepare")) submit(`${root}/orders/${order.id}/completions`, output); }}>{(Object.keys(output) as (keyof typeof output)[]).map(key => <div key={key}>{input(key, output[key], value => setOutput(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked || !allowed("prepare")}>{t("completion")}</button></form>}
      </>}
    </>}
  </main>;
}
