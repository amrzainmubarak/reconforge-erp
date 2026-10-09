import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadExceptionReviewIdentity, type ExceptionReviewIdentity } from "../exception-review-data";
import { procurementOptions, procurementScopes, type ProcurementOption, type ProcurementOptions, type ProcurementScope } from "../procurement-data";
import { procurementTranslate, type ProcurementMessage } from "../procurement-i18n";
import { distinctPartialPoster, installmentCommand, partialCommand, partialGet, partialList, partialRoot, type InstallmentPlan, type PartialDetail, type PartialInvoice, type PartialReceipt } from "../procurement-partial-data";
import { partialTranslate, type PartialMessage } from "../procurement-partial-i18n";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./ProcurementPartialPage.css";

export function ProcurementPartialPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <PartialSession key={auth.revision} locale={locale} />;
}

function PartialSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: ProcurementMessage) => procurementTranslate(locale, key), p = (key: PartialMessage) => partialTranslate(locale, key);
  const [tenant, setTenant] = useState(""), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<ExceptionReviewIdentity | null>(null), [workspace, setWorkspace] = useState("");
  const [scopes, setScopes] = useState<ProcurementScope[]>([]), [scope, setScope] = useState<ProcurementScope | null>(null);
  const [options, setOptions] = useState<ProcurementOptions | null>(null), [orders, setOrders] = useState<PartialDetail[]>([]), [detail, setDetail] = useState<PartialDetail | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({ number: "", supplier_code: "", item_code: "", quantity: "", unit_price_minor: "", posting_date: "", period_id: "", location_code: "", policy_code: "", journal_code: "", ap_account_code: "", cash_account_code: "" });
  const [part, setPart] = useState({ quantity: "", posting_date: "", period_id: "" }), [reason, setReason] = useState("");
  const [paymentInvoice, setPaymentInvoice] = useState(""), [paymentAmount, setPaymentAmount] = useState(""), [pendingInvoice, setPendingInvoice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<ProcurementMessage | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), errorRef = useRef<HTMLDivElement>(null), savedRef = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && caught.status === 403 ? "denied" : caught instanceof AdminApiError && caught.status < 500 ? "conflict" : "unavailable");
    if (caught instanceof AdminApiError && caught.status === 403) { setDetail(null); setOrders([]); }
  }
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    loadExceptionReviewIdentity(auth.session, controller.signal).then((value) => { if (!controller.signal.aborted && current()) { setIdentity(value); setWorkspace(value.workspaces[0] ?? ""); } }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !workspace) return;
    const controller = new AbortController(); setScope(null); setScopes([]); setDetail(null); setOptions(null); setOrders([]);
    procurementScopes(auth.session, workspace, controller.signal).then((value) => { if (!controller.signal.aborted && current()) setScopes(value); }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, workspace]);
  useEffect(() => {
    if (!auth.session || !scope) return;
    const controller = new AbortController();
    Promise.all([procurementOptions(auth.session, scope, controller.signal), partialList(auth.session, scope, controller.signal)]).then(([references, records]) => {
      if (!controller.signal.aborted && current()) { setOptions(references); setOrders(records); }
    }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, refresh]);
  const locked = busy || pending !== null;
  async function login(event: FormEvent) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || lock.current || pending) return; lock.current = true; setBusy(true); setError(null);
    try { const expiry = await stepUpBrowserAdminSession(auth.session, password); if (current()) auth.elevate(expiry, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function logout() {
    if (!auth.session || locked) return; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); } catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  async function inspect(id: string) {
    if (!auth.session || !scope || locked) return; setBusy(true); setError(null); setDetail(null);
    try { const value = await partialGet(auth.session, scope, id); if (current()) { setDetail(value); setPart({ quantity: "", posting_date: value.order.request.posting_date, period_id: value.order.request.period_id }); } }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand, invoiceId: string | null = null) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setError(null); setPending(command);
    setPendingInvoice(invoiceId);
    try {
      let value: PartialDetail;
      if (invoiceId) {
        const invoice = detail?.invoices.find((item) => item.id === invoiceId);
        if (!invoice || !detail) throw new Error("procurement_partial_contract_invalid");
        await installmentCommand(auth.session, scope, invoice, command);
        value = await partialGet(auth.session, scope, detail.order.id);
      } else value = await partialCommand(auth.session, scope, command);
      if (current()) { setDetail(value); setPending(null); setPendingInvoice(null); setReason(""); setPaymentAmount(""); setPart({ quantity: "", posting_date: value.order.request.posting_date, period_id: value.order.request.period_id }); setRefresh((value) => value + 1); requestAnimationFrame(() => savedRef.current?.focus()); }
    }
    catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown");
      else { setPending(null); setPendingInvoice(null); setDetail(null); setRefresh((value) => value + 1); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault(); if (!scope || locked) return;
    void send(prepareScopedCommand(partialRoot + "/orders", { ...draft, currency_code: scope.currency_code, workspace: scope.workspace_id, organization_code: scope.organization_code, entity_code: scope.entity_code }));
  }
  function act(operation: string, documentId?: string) {
    if (!detail || locked || !reason.trim()) return;
    if (operation === "receive" || operation === "review-receipt") {
      const receipt = detail.receipts.find((item) => item.id === documentId);
      if (!receipt || !receiptEligible(receipt)) return;
    }
    if (["review-accrual", "post-accrual"].includes(operation)) {
      const invoice = detail.invoices.find((item) => item.id === documentId);
      if (!invoice || !accrualEligible(invoice)) return;
    }
    void send(prepareScopedCommand(`${partialRoot}/orders/${encodeURIComponent(detail.order.id)}/commands/${operation}`, { expected_version: detail.order.row_version, reason, ...(documentId ? { document_id: documentId } : {}) }));
  }
  function preparePart(operation: "prepare-receipt" | "match-invoice") {
    if (!detail || locked || !reason.trim() || !part.quantity || !part.posting_date || !part.period_id) return;
    void send(prepareScopedCommand(`${partialRoot}/orders/${encodeURIComponent(detail.order.id)}/commands/${operation}`, { ...part, reason, expected_version: detail.order.row_version }));
  }
  function preparePayment(event: FormEvent) {
    event.preventDefault(); if (!detail || locked || !reason.trim()) return;
    const invoice = detail.invoices.find((item) => item.id === paymentInvoice);
    if (!invoice || invoice.stage !== "Accrued" || !/^[1-9][0-9]{0,18}$/.test(paymentAmount) || BigInt(paymentAmount) > BigInt(invoice.outstanding_minor)) { setError("conflict"); return; }
    void send(prepareScopedCommand("/api/v1/financial-installments/plans", { source_kind: "APPayment", source_id: invoice.native_invoice_id, amount_minor: paymentAmount,
      journal_code: detail.order.request.journal_code, period_id: part.period_id, posting_date: part.posting_date, debit_account_code: detail.order.request.ap_account_code,
      credit_account_code: detail.order.request.cash_account_code, reason }), invoice.id);
  }
  function paymentPhase(plan: InstallmentPlan, invoiceId: string) {
    if (locked || !reason.trim() || plan.phase === 2 || !paymentEligible(plan)) return;
    void send(prepareScopedCommand(`/api/v1/financial-installments/plans/${encodeURIComponent(plan.id)}/${plan.phase === 0 ? "review" : "post"}`,
      { expected_plan_digest: plan.plan_digest, reason }), invoiceId);
  }
  const permitted = (permission: string) => Boolean(identity?.human && identity.permissions.includes(permission) && auth.stepUpExpiresAt);
  const actorId = identity?.id ?? null;
  function receiptEligible(item: PartialReceipt) {
    const permissions = item.stage === "Prepared" ? ["payables.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"] : ["payables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"];
    return permissions.every(permitted) && (item.stage === "Prepared" ? actorId !== item.preparer_actor_id : distinctPartialPoster(item.preparer_actor_id, item.reviewer_actor_id, actorId));
  }
  function accrualEligible(item: PartialInvoice) {
    if (item.stage === "Matched") return permitted("payables.approve");
    if (item.stage === "Approved") return permitted("payables.manage") && permitted("finance_core.manage");
    if (item.stage === "AccrualPrepared") return permitted("payables.approve") && permitted("finance_core.validate") && actorId !== item.accrual_preparer_actor_id;
    return permitted("payables.approve") && permitted("finance_core.post") && distinctPartialPoster(item.accrual_preparer_actor_id, item.accrual_reviewer_actor_id, actorId);
  }
  function paymentEligible(plan: InstallmentPlan) {
    return permitted("payables.settle") && permitted(plan.phase === 0 ? "finance_core.validate" : "finance_core.post") &&
      (plan.phase === 0 ? actorId !== plan.preparer_actor_id : distinctPartialPoster(plan.preparer_actor_id, plan.reviewer_actor_id, actorId));
  }
  const input = (label: string, value: string, change: (value: string) => void, type = "text") => <label>{label}<input required type={type} maxLength={500} disabled={locked} value={value} onChange={(event) => change(event.target.value)} /></label>;
  const choose = (label: ProcurementMessage, field: string, values: ProcurementOption[]) => <label>{t(label)}<select required disabled={locked} value={draft[field]} onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}><option value="">—</option>{values.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name ?? item.currency_code ?? ""}</option>)}</select></label>;
  const chart = options?.journals.find((item) => item.code === draft.journal_code)?.chart_code;
  const accounts = options?.accounts.filter((item) => chart && item.chart_code === chart) ?? [];
  const stageName = (stage: string) => ["Draft", "Submitted", "Approved"].includes(stage) ? t(stage as ProcurementMessage) : p(stage as PartialMessage);
  return <main id="main-content" className="procurement-partial-page" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{p("title")}</h1><p>{p("intro")}</p><p>{p("bounds")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={errorRef}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending, pendingInvoice)}>{t("retry")}</button><code>{String(pending.body.command_id)}</code></aside>}
    {!auth.session ? <form onSubmit={(event) => void login(event)} aria-label={t("signIn")}>{input(t("tenant"), tenant, setTenant)}{input(t("username"), username, setUsername)}{input(t("password"), password, setPassword, "password")}<button disabled={busy}>{t("signIn")}</button></form> : <>
      <div className="partial-toolbar"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => void logout()}>{t("signOut")}</button></div>
      {!auth.stepUpExpiresAt && <form onSubmit={(event) => void stepUp(event)} aria-label={t("stepUp")}>{input(t("password"), password, setPassword, "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <div className="partial-toolbar"><label>{t("workspace")}<select disabled={locked} value={workspace} onChange={(event) => setWorkspace(event.target.value)}><option value="">—</option>{identity?.workspaces.map((value) => <option key={value}>{value}</option>)}</select></label><label>{t("scope")}<select disabled={locked} value={scope?.legal_entity_id ?? ""} onChange={(event) => { setScope(scopes.find((item) => item.legal_entity_id === event.target.value) ?? null); setOptions(null); setOrders([]); setDetail(null); }}><option value="">—</option>{scopes.map((item) => <option key={item.legal_entity_id} value={item.legal_entity_id}>{item.organization_name} · {item.entity_name} · {item.currency_code}</option>)}</select></label></div>
      {scope && <><section><h2>{t("cycles")}</h2><ul className="partial-order-list">{orders.map((item) => <li key={item.order.id}><bdi>{item.order.number}</bdi><span>{stageName(item.order.stage)}</span><button disabled={locked} onClick={() => void inspect(item.order.id)}>{t("open")} {item.order.number}</button></li>)}</ul>{orders.length === 0 && <p>{t("empty")}</p>}</section>
        {options && permitted("payables.manage") && <details><summary>{t("newOrder")}</summary><form onSubmit={create} aria-label={t("newOrder")}><fieldset disabled={locked}><legend>{t("newOrder")}</legend>
          {input(t("number"), draft.number, (value) => setDraft({ ...draft, number: value }))}{choose("supplier", "supplier_code", options.suppliers.filter((item) => item.currency_code === scope.currency_code))}{choose("item", "item_code", options.items)}{input(t("quantity"), draft.quantity, (value) => setDraft({ ...draft, quantity: value }))}{input(t("unitPrice"), draft.unit_price_minor, (value) => setDraft({ ...draft, unit_price_minor: value }))}{input(t("date"), draft.posting_date, (value) => setDraft({ ...draft, posting_date: value }), "date")}
          <label>{t("period")}<select required value={draft.period_id} onChange={(event) => setDraft({ ...draft, period_id: event.target.value })}><option value="">—</option>{options.periods.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {choose("location", "location_code", options.locations)}{choose("policy", "policy_code", options.policies)}{choose("journal", "journal_code", options.journals)}{choose("ap", "ap_account_code", accounts.filter((item) => item.account_type === "Liability"))}{choose("cash", "cash_account_code", accounts.filter((item) => item.account_type === "Asset"))}<button>{t("create")}</button>
        </fieldset></form></details>}
        {detail && <section aria-label={t("evidence")}><h2>{detail.order.number}</h2><p tabIndex={-1} role="status" ref={savedRef}>{p("completed")} {stageName(detail.order.stage)} · {detail.order.row_version}</p><button disabled={locked} onClick={() => void inspect(detail.order.id)}>{p("refreshDetail")}</button><p>{t("independent")}</p>
          <dl className="partial-totals">{([ ["reserved_receipt_quantity", "reserved"], ["received_quantity", "received"], ["invoiced_quantity", "invoiced"], ["accrued_minor", "accrued"], ["paid_minor", "paid"], ["outstanding_minor", "outstanding"] ] as const).map(([key, label]) => <div key={key}><dt>{p(label)}</dt><dd><bdi>{detail.totals[key]}</bdi></dd></div>)}</dl>
          {input(t("reason"), reason, setReason)}
          {detail.order.stage !== "Approved" && <button disabled={locked || !auth.stepUpExpiresAt || !reason.trim()} onClick={() => act(detail.order.stage === "Draft" ? "submit-order" : "approve-order")}>{t(detail.order.stage === "Draft" ? "submit-order" : "approve-order")}</button>}
          {detail.order.stage === "Approved" && options && permitted("payables.manage") && <fieldset disabled={locked}><legend>{p("newPart")}</legend>{input(t("quantity"), part.quantity, (value) => setPart({ ...part, quantity: value }))}{input(t("date"), part.posting_date, (value) => setPart({ ...part, posting_date: value }), "date")}<label>{t("period")}<select value={part.period_id} onChange={(event) => setPart({ ...part, period_id: event.target.value })}><option value="">—</option>{options.periods.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={!reason.trim()} onClick={() => preparePart("prepare-receipt")}>{p("prepareReceipt")}</button><button disabled={!reason.trim()} onClick={() => preparePart("match-invoice")}>{p("matchInvoice")}</button></fieldset>}
          <h3>{p("receipts")}</h3><ul className="partial-document-list">{detail.receipts.map((item) => <li key={item.id}><h4>{item.number}</h4><p>{stageName(item.stage)} · {t("quantity")}: {item.quantity_text} · {t("amount")}: {item.total_minor} {detail.order.request.currency_code}</p><code>{item.receipt_plan_id}</code>{item.goods_receipt_id && <code>{item.goods_receipt_id}</code>}<p>{p("preparer")}: <bdi>{item.preparer_actor_id}</bdi> · {p("reviewer")}: <bdi>{item.reviewer_actor_id ?? "—"}</bdi> · {p("poster")}: <bdi>{item.posted_actor_id ?? "—"}</bdi></p>{item.stage === "Reviewed" && <p>{p("threePeople")}</p>}{item.stage !== "Posted" && <button disabled={locked || !receiptEligible(item) || !reason.trim()} onClick={() => act(item.stage === "Prepared" ? "review-receipt" : "receive", item.id)}>{t(item.stage === "Prepared" ? "review-receipt" : "receive")}</button>}</li>)}</ul>
          <h3>{p("invoices")}</h3><ul className="partial-document-list">{detail.invoices.map((item) => <li key={item.id}><h4>{item.number}</h4><p>{stageName(item.stage)} · {t("quantity")}: {item.quantity_text} · {t("amount")}: {item.total_minor} {detail.order.request.currency_code}</p><p>{p("paid")}: {item.paid_minor} · {p("outstanding")}: {item.outstanding_minor}</p><code>{item.native_invoice_id}</code>{item.accrual_effect_id && <code>{item.accrual_effect_id}</code>}<p>{p("preparer")}: <bdi>{item.accrual_preparer_actor_id ?? "—"}</bdi> · {p("reviewer")}: <bdi>{item.accrual_reviewer_actor_id ?? "—"}</bdi> · {p("poster")}: <bdi>{item.accrual_posted_actor_id ?? "—"}</bdi></p>{item.stage === "AccrualReviewed" && <p>{p("threePeople")}</p>}{item.stage !== "Accrued" && <button disabled={locked || !accrualEligible(item) || !reason.trim()} onClick={() => act({ Matched: "approve-invoice", Approved: "prepare-accrual", AccrualPrepared: "review-accrual", AccrualReviewed: "post-accrual", Accrued: "" }[item.stage], item.id)}>{t({ Matched: "approve-invoice", Approved: "prepare-accrual", AccrualPrepared: "review-accrual", AccrualReviewed: "post-accrual", Accrued: "" }[item.stage] as ProcurementMessage)}</button>}{item.payment_links.map((link) => <p key={link.id}><code>{link.id}</code> · {p("paid")}: {link.amount_minor} · <code>{link.finance_effect_id}</code></p>)}</li>)}</ul>
          <h3>{p("payments")}</h3>
          <ul className="partial-document-list">{detail.invoices.flatMap((invoice) => invoice.installment_plans.filter((plan) => plan.phase < 2).map((plan) => <li key={plan.id}><h4>{invoice.number}</h4><p>{p(plan.status)} · {p("amount")}: {plan.amount_minor} {plan.currency_code}</p><code>{plan.id}</code><p>{p("preparer")}: <bdi>{plan.preparer_actor_id}</bdi> · {p("reviewer")}: <bdi>{plan.reviewer_actor_id ?? "—"}</bdi></p>{plan.phase === 1 && <p>{p("threePeople")}</p>}<button disabled={locked || !paymentEligible(plan) || !reason.trim()} onClick={() => paymentPhase(plan, invoice.id)}>{p(plan.phase === 0 ? "reviewPayment" : "postPayment")}</button></li>))}</ul>
          {options && permitted("payables.settle") && <form onSubmit={preparePayment} aria-label={p("preparePayment")}><fieldset disabled={locked}><legend>{p("preparePayment")}</legend><label>{t("invoice")}<select required value={paymentInvoice} onChange={(event) => setPaymentInvoice(event.target.value)}><option value="">—</option>{detail.invoices.filter((invoice) => invoice.stage === "Accrued" && invoice.outstanding_minor !== "0" && !invoice.installment_plans.some((plan) => plan.phase < 2)).map((invoice) => <option key={invoice.id} value={invoice.id}>{invoice.number} · {invoice.outstanding_minor} {detail.order.request.currency_code}</option>)}</select></label>{input(p("amount"), paymentAmount, setPaymentAmount)}{input(t("date"), part.posting_date, (value) => setPart({ ...part, posting_date: value }), "date")}<label>{t("period")}<select required value={part.period_id} onChange={(event) => setPart({ ...part, period_id: event.target.value })}><option value="">—</option>{options.periods.map((period) => <option key={period.id} value={period.id}>{period.name}</option>)}</select></label><button disabled={!reason.trim()}>{p("preparePayment")}</button></fieldset></form>}
        </section>}
      </>}
    </>}
  </main>;
}
