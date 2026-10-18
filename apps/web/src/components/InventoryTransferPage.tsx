import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { parseTransfer, parseTransferAck, transferMoney, transferObject, transferPermissions, transferRead, transferRequest, transferRoot, type TransferCommandBinding, type TransferSource } from "../inventory-transfer-data";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

const words = {
  title: ["Warehouse transfer", "تحويل بين المستودعات"], boundary: ["Move approved original stock between two warehouses in one entity. Independent review reserves stock; a third human posts. Original pooled FIFO cost and GL stay attached to their sources.", "نقل المخزون الأصلي المعتمد بين مستودعين في كيان واحد. المراجعة المستقلة تحجز المخزون، وشخص ثالث يرحّل النقل. تبقى تكلفة FIFO وقيود الأستاذ مرتبطة بمصادرها الأصلية."],
  tenant: ["Tenant", "المؤسسة"], username: ["Username", "المستخدم"], password: ["Password", "كلمة المرور"], login: ["Sign in", "تسجيل الدخول"], logout: ["Sign out", "تسجيل الخروج"], stepup: ["Verify transfer authority", "تأكيد صلاحية التحويل"],
  workspace_id: ["Workspace ID", "معرّف مساحة العمل"], organization_id: ["Organization ID", "معرّف المنظمة"], legal_entity_id: ["Legal entity ID", "معرّف الكيان القانوني"], apply: ["Apply scope", "تطبيق النطاق"], refresh: ["Refresh original transfers", "تحديث التحويلات الأصلية"], select: ["Retained transfer", "التحويل المحفوظ"], empty: ["No transfers in this scope.", "لا توجد تحويلات في هذا النطاق."],
  create: ["Prepare warehouse transfer", "إعداد تحويل المستودع"], number: ["Transfer number", "رقم التحويل"], item_code: ["Item code", "رمز الصنف"], quantity: ["Exact base-unit quantity", "الكمية الدقيقة بوحدة الصنف"], from_location: ["Source warehouse/location", "المستودع والموقع المصدر"], to_location: ["Destination warehouse/location", "المستودع والموقع الوجهة"], period_id: ["Open fiscal period ID", "معرّف الفترة المالية المفتوحة"], posting_date: ["Business date", "تاريخ العملية"], reason: ["Reason", "السبب"],
  review: ["Review and reserve original stock", "مراجعة وحجز المخزون الأصلي"], post: ["Post reviewed transfer", "ترحيل التحويل المراجع"], cancel: ["Cancel unposted transfer", "إلغاء التحويل غير المرحّل"], inverse: ["Prepare independent inverse", "إعداد تحويل عكسي مستقل"], inverseNumber: ["Inverse number", "رقم التحويل العكسي"],
  cost: ["Original approved entity cost", "تكلفة الكيان الأصلية المعتمدة"], layer: ["Original FIFO layer", "طبقة FIFO الأصلية"], remaining: ["Remaining quantity / value", "الكمية والقيمة المتبقية"], original: ["Complete original value", "القيمة الأصلية الكاملة"], movement: ["Original native movement", "حركة المخزون الأصلية"], evidence: ["Retained original source evidence", "أدلة المصدر الأصلي المحفوظة"],
  unknown: ["Outcome unknown. Keep this exact command and retry under the original human and scope.", "نتيجة الطلب غير معروفة. احتفظ بنفس الأمر وأعد المحاولة بالمستخدم والنطاق الأصليين."], retry: ["Retry original command", "إعادة الأمر الأصلي"], invalid: ["The request or original evidence is invalid.", "الطلب أو الدليل الأصلي غير صالح."], denied: ["Current authority refused this source. Displayed financial evidence was cleared.", "الصلاحية الحالية رفضت هذا المصدر. تم مسح الأدلة المالية المعروضة."], reload: ["Reload current source authority before another command.", "حدّث صلاحية المصدر الحالية قبل تنفيذ أمر آخر."], refused: ["The command was refused without a new effect.", "تم رفض الأمر دون أثر جديد."], discard: ["Discard refused command", "ترك الأمر المرفوض"],
} as const;
type Word = keyof typeof words;
const phases = [["Draft", "مسودة"], ["Reviewed", "مراجع"], ["Posted", "مرحّل"], ["Cancelled", "ملغى"]];
interface Pending { command: PreparedScopedCommand; scope: FinanceScope; binding: TransferCommandBinding; unknown: boolean; refused: boolean; }

export function InventoryTransferPage({ locale }: { locale: Locale }) {
  const t = (key: Word) => words[key][locale === "ar" ? 1 : 0], auth = useBrowserSession(), revision = auth.revision;
  const current = () => auth.isCurrent(revision), lock = useRef(false);
  const [login, setLogin] = useState({ tenant: "", username: "", password: "" }), [identity, setIdentity] = useState<BudgetIdentity | null>(null);
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [sources, setSources] = useState<TransferSource[]>([]), [selected, setSelected] = useState<TransferSource | null>(null);
  const [busy, setBusy] = useState(false), [needsRead, setNeedsRead] = useState(true), [error, setError] = useState<Word | null>(null), [pending, setPending] = useState<Pending | null>(null);
  const [draft, setDraft] = useState({ number: "", item_code: "", quantity: "", from_location: "", to_location: "", period_id: "", posting_date: "", reason: "" });
  const [reason, setReason] = useState(""), [inverse, setInverse] = useState({ number: "", period_id: "", posting_date: "", reason: "" });
  const has = (permissions: string[]) => identity?.human && permissions.every(permission => identity.permissions.includes(permission));
  const ready = !!scope && !!identity?.stepUp && has(transferRead) && !busy && !needsRead && !pending;
  const allowed = (operation: string) => has(transferPermissions[operation]);
  const clearFinancial = () => { setSources([]); setSelected(null); setNeedsRead(true); };
  function fail(caught: unknown) {
    if (!current()) return;
    if (caught instanceof AdminApiError && [401, 403, 404].includes(caught.status)) { clearFinancial(); setError("denied"); auth.recover(caught, revision); }
    else setError(caught instanceof AdminApiError && caught.status < 500 ? "refused" : "invalid");
  }
  useEffect(() => {
    setIdentity(null); setScope(null); clearFinancial(); setError(null); setBusy(false);
    if (auth.session) void loadBudgetIdentity(auth.session).then(value => { if (current()) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(fail);
  // The captured revision owns every async response; financial data never crosses sessions.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);
  async function load(nextScope: FinanceScope, expected?: TransferSource) {
    if (!auth.session) return;
    const raw = await transferRequest(auth.session, nextScope, `${transferRoot}/transfers`);
    if (!transferObject(raw) || !Array.isArray(raw.transfers) || raw.transfers.length > 100) throw new Error("inventory_transfer_evidence_invalid");
    const parsed = await Promise.all(raw.transfers.map(row => parseTransfer(row, nextScope, auth.session!.tenantId)));
    if (new Set(parsed.map(row => row.id)).size !== parsed.length) throw new Error("inventory_transfer_evidence_invalid");
    const retained = expected ?? selected, next = retained ? parsed.find(row => row.id === retained.id) ?? null : null;
    if (retained && (!next || next.source_digest !== retained.source_digest || next.row_version < retained.row_version)) throw new Error("inventory_transfer_evidence_invalid");
    if (current()) { setSources(parsed); setSelected(next); setNeedsRead(false); setError(null); }
  }
  useEffect(() => { if (scope && auth.session && !lock.current) { lock.current = true; setBusy(true); void load(scope).catch(caught => { clearFinancial(); fail(caught); }).finally(() => { lock.current = false; if (current()) setBusy(false); }); } }, [scope]); // eslint-disable-line react-hooks/exhaustive-deps
  async function authenticate(event: FormEvent, stepup = false) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true);
    try { if (stepup && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, revision); }
    } catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  async function refresh() {
    if (!scope || !auth.session || lock.current) return; lock.current = true; setBusy(true);
    try { const latest = await loadBudgetIdentity(auth.session); if (current()) setIdentity(latest); await load(scope); }
    catch (caught) { setNeedsRead(true); fail(caught); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  async function send(retained: Pending) {
    if (!auth.session || auth.session.tenantId !== retained.binding.tenantId || !identity || lock.current || identity.id !== retained.binding.actorId || !identity.stepUp
        || !identity.workspaces.includes(retained.scope.workspace_id) || !identity.organizations.includes(retained.scope.organization_id) || !identity.entities.includes(retained.scope.legal_entity_id)) return;
    lock.current = true; setBusy(true); setPending(retained); setError(null);
    try { const raw = await transferRequest(auth.session, retained.scope, retained.command.path, retained.command);
      const source = await parseTransferAck(raw, retained.command, retained.scope, retained.binding);
      if (!current()) return; setSelected(source); setPending(null); setNeedsRead(true); setReason("");
      try { await load(retained.scope, source); } catch (caught) { if (current()) { fail(caught); setError(caught instanceof AdminApiError && [401, 403, 404].includes(caught.status) ? "denied" : "reload"); } }
    } catch (caught) { if (current()) { const refused = caught instanceof AdminApiError && [400, 409, 422].includes(caught.status) && !retained.unknown;
      setPending({ ...retained, unknown: !refused, refused }); fail(caught); setError(refused ? "refused" : "unknown"); } }
    finally { lock.current = false; if (current()) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>, originalId?: string) {
    if (!scope || !identity || !auth.session || !ready) return;
    try { void send({ command: prepareScopedCommand(path, body), scope: { ...scope }, binding: { actorId: identity.id, tenantId: auth.session.tenantId,
      previousVersion: selected?.row_version ?? null, ...(originalId ? { originalId } : {}) }, unknown: false, refused: false }); } catch { setError("invalid"); }
  }
  const input = (key: Word, value: string, change: (value: string) => void, disabled = false) => <label>{t(key)}<input required value={value} disabled={busy || (!!pending && !["tenant", "username", "password"].includes(key)) || disabled}
    maxLength={key === "reason" ? 500 : 160} type={key === "password" ? "password" : key === "posting_date" ? "date" : "text"} onChange={event => change(event.target.value)} /></label>;
  const reviewedCost = selected?.review_cost_snapshot ?? selected?.cost_snapshot;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}><header><h1>{t("title")}</h1><p>{t("boundary")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{pending && !busy && <aside role="status" className="panel"><p>{t(pending.refused ? "refused" : "unknown")}</p><code dir="ltr">{pending.command.body.command_id}</code>
      <button disabled={!identity?.stepUp || identity.id !== pending.binding.actorId} onClick={() => void send(pending)}>{t("retry")}</button>{pending.refused && <button onClick={() => { setPending(null); setNeedsRead(true); }}>{t("discard")}</button>}</aside>}
    {!auth.session ? <form aria-label={t("login")} className="panel reporting-form" onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin(old => ({ ...old, [key]: value })), false)}</div>)}<button disabled={busy}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={busy} onClick={() => { if (auth.session && !lock.current) void endBrowserAdminSession(auth.session).then(() => { if (current()) auth.clear(revision); }).catch(fail); }}>{t("logout")}</button>{identity?.human && !identity.stepUp && <form aria-label={t("stepup")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, password => setLogin(old => ({ ...old, password })))}<button disabled={busy}>{t("stepup")}</button></form>}</section>
      <form aria-label={t("apply")} className="panel reporting-form" onSubmit={event => { event.preventDefault(); if (identity && !busy && !pending) { clearFinancial(); setScope({ ...scopeInput }); } }}>{(["workspace_id", "organization_id", "legal_entity_id"] as const).map(key => <div key={key}>{input(key, scopeInput[key], value => setScopeInput(old => ({ ...old, [key]: value })), !identity)}</div>)}<button disabled={busy || !!pending || !has(transferRead)}>{t("apply")}</button></form>
      {scope && <><section className="panel"><button disabled={busy || !!pending} onClick={() => void refresh()}>{t("refresh")}</button><label>{t("select")}<select disabled={busy || !!pending} value={selected?.id ?? ""} onChange={event => setSelected(sources.find(row => row.id === event.target.value) ?? null)}><option value="">{t("empty")}</option>{sources.map(row => <option key={row.id} value={row.id}>{row.number} · {phases[row.phase][locale === "ar" ? 1 : 0]}</option>)}</select></label></section>
        {allowed("create") && <form aria-label={t("create")} className="panel reporting-form" onSubmit={event => { event.preventDefault(); submit(`${transferRoot}/transfers`, draft); }}>{Object.entries(draft).map(([key, value]) => <div key={key}>{input(key as Word, value, next => setDraft(old => ({ ...old, [key]: next })))}</div>)}<button disabled={!ready}>{t("create")}</button></form>}
        {selected && <><section className="panel"><h2>{selected.number} · {phases[selected.phase][locale === "ar" ? 1 : 0]}</h2><p>{selected.item_code} · {selected.quantity} · <bdi>{selected.from_location} → {selected.to_location}</bdi></p><p>{t("movement")}: <code dir="ltr">{selected.native_movement_id}</code></p></section>
          {reviewedCost && <section className="panel reporting-table" tabIndex={0}><table><caption>{t("cost")}</caption><thead><tr>{(["layer", "remaining", "original"] as const).map(key => <th key={key} scope="col">{t(key)}</th>)}</tr></thead><tbody>{reviewedCost.sources.map(original => { const layer = original.layer as Record<string, string>; return <tr key={layer.id}><th scope="row"><code dir="ltr">{layer.id}</code></th><td><bdi>{layer.remaining_quantity_scaled} / {transferMoney(layer.remaining_value_minor, reviewedCost.monetary_policy.currency_precision)} {reviewedCost.monetary_policy.currency_code}</bdi></td><td><bdi>{transferMoney(layer.original_value_minor, reviewedCost.monetary_policy.currency_precision)} {reviewedCost.monetary_policy.currency_code}</bdi></td></tr>; })}</tbody></table></section>}
          {selected.phase < 2 && <form aria-label={t("review")} className="panel reporting-form" onSubmit={event => event.preventDefault()}>{input("reason", reason, setReason)}{selected.phase === 0 && allowed("review") && <button disabled={!ready || !reason || identity?.id === selected.creator_actor_id} onClick={() => submit(`${transferRoot}/transfers/${selected.id}/review`, { expected_digest: selected.source_digest, expected_version: selected.row_version, reason })}>{t("review")}</button>}{selected.phase === 1 && allowed("post") && <button disabled={!ready || !reason || [selected.creator_actor_id, selected.reviewer_actor_id].includes(identity?.id ?? "")} onClick={() => submit(`${transferRoot}/transfers/${selected.id}/post`, { expected_digest: selected.source_digest, expected_version: selected.row_version, reason })}>{t("post")}</button>}{allowed("cancel") && <button disabled={!ready || !reason || identity?.id === selected.creator_actor_id} onClick={() => submit(`${transferRoot}/transfers/${selected.id}/cancel`, { expected_digest: selected.source_digest, expected_version: selected.row_version, reason })}>{t("cancel")}</button>}</form>}
          {selected.phase === 2 && selected.original === null && allowed("inverse-create") && <form aria-label={t("inverse")} className="panel reporting-form" onSubmit={event => { event.preventDefault(); submit(`${transferRoot}/transfers/${selected.id}/inverse`, { ...inverse, expected_digest: selected.source_digest, expected_version: selected.row_version }, selected.id); }}>{Object.entries(inverse).map(([key, value]) => <div key={key}>{input(key === "number" ? "inverseNumber" : key as Word, value, next => setInverse(old => ({ ...old, [key]: next })))}</div>)}<button disabled={!ready}>{t("inverse")}</button></form>}
          <details className="panel"><summary>{t("evidence")}</summary><code dir="ltr">{selected.source_digest}</code><pre dir="ltr" tabIndex={0} aria-label={t("evidence")}>{JSON.stringify(selected, null, 2)}</pre></details></>}
      </>}
    </>}
  </main>;
}
