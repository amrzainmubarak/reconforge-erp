import { useState } from "react";
import type { ScopedJsonValue } from "../scoped-command";
import type { BillingPlan } from "../project-time-billing-data";
import { billingWords } from "../project-time-billing-i18n";

export type BillingRow = Record<string, unknown> & { id: string };
export type BillingWord = keyof typeof billingWords;
export interface BillingFormsProps {
  t: (key: BillingWord) => string; locked: boolean; allowed: (action: string) => boolean;
  projects: BillingRow[]; times: BillingRow[]; prices: BillingRow[]; plan: BillingPlan | null;
  submit: (path: string, body: Record<string, ScopedJsonValue>) => void;
}
export function ProjectTimeBillingForms({ t, locked, allowed, projects, times, prices, plan, submit }: BillingFormsProps) {
  const [price, setPrice] = useState({ customer_code: "", project_id: "", valid_from: "", valid_through: "", currency_code: "", hourly_price_minor: "", reason: "" });
  const [invoice, setInvoice] = useState({ customer_code: "", invoice_number: "", period_id: "", posting_date: "", due_date: "", journal_code: "", receivable_account_code: "", revenue_account_code: "", cash_account_code: "" });
  const [collection, setCollection] = useState({ amount_minor: "", period_id: "", posting_date: "" });
  const [selectedTimes, setSelectedTimes] = useState<string[]>([]), [selectedPrices, setSelectedPrices] = useState<string[]>([]);
  const text = (key: BillingWord, value: string, change: (value: string) => void) => <label>{t(key)}<input required disabled={locked} value={value} maxLength={key === "reason" ? 500 : 160}
    type={["valid_from", "valid_through", "posting_date", "due_date"].includes(key) ? "date" : "text"} inputMode={key.endsWith("_minor") ? "numeric" : undefined} onChange={event => change(event.target.value)} /></label>;
  const choose = (rows: BillingRow[], ids: string[], change: (ids: string[]) => void, word: BillingWord) => <fieldset><legend>{t(word)}</legend>{rows.length ? rows.map(row => <label key={row.id}><input type="checkbox" disabled={locked} checked={ids.includes(row.id)} onChange={event => change(event.target.checked ? [...ids, row.id] : ids.filter(id => id !== row.id))} /><bdi>{String(row.project_code ?? row.project_id ?? row.employee_id ?? row.id)}</bdi><code>{row.id}</code></label>) : <p role="status">{t("empty")}</p>}</fieldset>;
  return <>
    {allowed("manage") && <form className="panel reporting-form" aria-label={t("registerPrice")} onSubmit={event => { event.preventDefault(); if (!locked && allowed("manage") && /^[1-9]\d{0,18}$/.test(price.hourly_price_minor)) submit("/prices", price); }}>
      {text("customer_code", price.customer_code, value => setPrice(old => ({ ...old, customer_code: value })))}
      <label>{t("project_id")}<select required disabled={locked} value={price.project_id} onChange={event => setPrice(old => ({ ...old, project_id: event.target.value }))}><option value="">—</option>{projects.map(row => <option key={row.id} value={row.id}>{String(row.project_code ?? row.id)}</option>)}</select></label>
      {(["valid_from", "valid_through", "currency_code", "hourly_price_minor", "reason"] as const).map(key => <div key={key}>{text(key, price[key], value => setPrice(old => ({ ...old, [key]: value })))}</div>)}
      <button disabled={locked}>{t("registerPrice")}</button>
    </form>}
    {allowed("prepare") && <form className="panel" aria-label={t("prepare")} onSubmit={event => { event.preventDefault(); if (!locked && selectedTimes.length && selectedPrices.length && allowed("prepare")) submit("/invoices", { ...invoice, time_ids: selectedTimes, price_ids: selectedPrices }); }}>
      {choose(times.filter(row => row.approver_id), selectedTimes, setSelectedTimes, "selectTimes")}
      {choose(prices.filter(row => row.approver_id && row.customer_code === invoice.customer_code), selectedPrices, setSelectedPrices, "selectPrices")}
      <div className="reporting-form">{(Object.keys(invoice) as (keyof typeof invoice)[]).map(key => <div key={key}>{text(key, invoice[key], value => { if (key === "customer_code") setSelectedPrices([]); setInvoice(old => ({ ...old, [key]: value })); })}</div>)}</div>
      <button disabled={locked || !selectedTimes.length || !selectedPrices.length}>{t("prepare")}</button>
    </form>}
    {plan?.schema_version === "project-invoice-v1" && plan.phase === 2 && allowed("collect") && <form className="panel reporting-form" aria-label={t("collect")} onSubmit={event => { event.preventDefault(); if (!locked && allowed("collect") && /^[1-9]\d{0,18}$/.test(collection.amount_minor)) submit(`/invoices/${plan.id}/collections`, collection); }}>
      {(Object.keys(collection) as (keyof typeof collection)[]).map(key => <div key={key}>{text(key, collection[key], value => setCollection(old => ({ ...old, [key]: value })))}</div>)}
      <button disabled={locked}>{t("collect")}</button>
    </form>}
  </>;
}
