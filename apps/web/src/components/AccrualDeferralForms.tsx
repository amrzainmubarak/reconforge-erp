import { useState } from "react";
import { adMinor, type AdCatalog, type AdPlan, type AdRecord, type AdSource } from "../accrual-deferral-data";
import type { AdWord } from "../accrual-deferral-i18n";
import type { ScopedJsonValue } from "../scoped-command";

interface Props { t: (key: AdWord) => string; locked: boolean; allowed: (action: string) => boolean; catalog: AdCatalog; source: AdSource | null; plan: AdPlan | null; submit: (path: string, body: Record<string, ScopedJsonValue>) => void }
interface Tranche { id: string; period_id: string; posting_date: string; weight: string; reversal_period_id: string; reversal_date: string }
const emptyTranche = (id: string): Tranche => ({ id, period_id: "", posting_date: "", weight: "1", reversal_period_id: "", reversal_date: "" });
export function AccrualDeferralForms({ t, locked, allowed, catalog, source, plan, submit }: Props) {
  const [request, setRequest] = useState({ mode: "new_prepaid_voucher", reference: "", amount_minor: "", journal_code: "", period_id: "", posting_date: "", original_effect_id: "", reason: "" });
  const [accounts, setAccounts] = useState({ prepaid: "", expense: "", accrued_liability: "", cash: "" });
  const [tranches, setTranches] = useState<Tranche[]>([emptyTranche("T1")]), [selectedTranche, setSelectedTranche] = useState("");
  const [inverse, setInverse] = useState({ period_id: "", posting_date: "", reason: "" }), [cancelReason, setCancelReason] = useState("");
  const text = (key: AdWord, value: string, change: (value: string) => void, prefix = "") => <label>{prefix + t(key)}<input aria-label={prefix + t(key)} required disabled={locked} value={value} maxLength={key === "reason" ? 500 : 160} type={key.includes("date") ? "date" : "text"} inputMode={key.endsWith("_minor") || key === "weight" ? "numeric" : undefined} onChange={event => change(event.target.value)} /></label>;
  const choose = (key: AdWord, value: string, change: (value: string) => void, rows: AdRecord[], field: string, prefix = "") => <label>{prefix + t(key)}<select aria-label={prefix + t(key)} required disabled={locked} value={value} onChange={event => change(event.target.value)}><option value="">—</option>{rows.map(row => <option key={String(row[field])} value={String(row[field])}>{String(row.account_code ?? row.journal_code ?? row.name ?? row.id)}{row.status ? ` · ${row.status}` : ""}</option>)}</select></label>;
  return <>
    {allowed("prepare") && <form className="panel" aria-label={t("prepare")} onSubmit={event => { event.preventDefault(); if (locked || !allowed("prepare") || !adMinor(request.amount_minor) || BigInt(request.amount_minor) <= 0n || tranches.some(row => !adMinor(row.weight) || BigInt(row.weight) <= 0n)) return;
      const body: Record<string, ScopedJsonValue> = { ...request, currency_code: catalog.entity.currency_code, accounts, tranches: tranches.map(row => request.mode === "expense_accrual" ? { ...row } : { id: row.id, period_id: row.period_id, posting_date: row.posting_date, weight: row.weight }) };
      if (!request.mode.startsWith("attach_")) body.original_effect_id = null;
      submit("/sources", body);
    }}>
      <h2>{t("prepare")}</h2><div className="reporting-form">
        <label>{t("mode")}<select aria-label={t("mode")} disabled={locked} value={request.mode} onChange={event => setRequest(old => ({ ...old, mode: event.target.value }))}>{(["new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"] as const).map(mode => <option key={mode} value={mode}>{t(mode)}</option>)}</select></label>
        <label>{t("currency_code")}<output><bdi>{catalog.entity.currency_code}</bdi></output></label>
        {(["reference", "amount_minor", "posting_date", "reason"] as const).map(key => <div key={key}>{text(key, request[key], value => setRequest(old => ({ ...old, [key]: value })))}</div>)}
        {choose("journal_code", request.journal_code, value => setRequest(old => ({ ...old, journal_code: value })), catalog.journals, "journal_code")}
        {choose("period_id", request.period_id, value => setRequest(old => ({ ...old, period_id: value })), catalog.periods, "id", t("source") + " · ")}
        {request.mode.startsWith("attach_") && text("original_effect_id", request.original_effect_id, value => setRequest(old => ({ ...old, original_effect_id: value })))}
        {(Object.keys(accounts) as (keyof typeof accounts)[]).map(role => <div key={role}>{choose(role, accounts[role], value => setAccounts(old => ({ ...old, [role]: value })), catalog.accounts.filter(row => row.account_type === ({ prepaid: "Asset", expense: "Expense", accrued_liability: "Liability", cash: "Asset" }[role])), "account_code")}</div>)}
      </div>
      <fieldset><legend>{t("schedule")}</legend>{tranches.map((row, index) => { const prefix = `${t("tranche")} ${index + 1} · `, change = (key: keyof Tranche, value: string) => setTranches(old => old.map((item, at) => at === index ? { ...item, [key]: value } : item)); return <section key={index} className="ad-tranche"><div className="reporting-form">
        {(["id", "posting_date", "weight"] as const).map(key => <div key={key}>{text(key, row[key], value => change(key, value), prefix)}</div>)}
        {choose("period_id", row.period_id, value => change("period_id", value), catalog.periods, "id", prefix)}
        {request.mode === "expense_accrual" && <>{choose("reversal_period_id", row.reversal_period_id, value => change("reversal_period_id", value), catalog.periods, "id", prefix)}{text("reversal_date", row.reversal_date, value => change("reversal_date", value), prefix)}</>}
      </div><button type="button" disabled={locked || tranches.length === 1} onClick={() => setTranches(old => old.filter((_, at) => at !== index))}>{t("remove")} {index + 1}</button></section>; })}
      <button type="button" disabled={locked || tranches.length >= 36} onClick={() => setTranches(old => [...old, emptyTranche("T" + (old.length + 1))])}>{t("add")}</button></fieldset>
      <button disabled={locked}>{t("prepare")}</button>
    </form>}
    {source && !source.cancelled && source.plans.some(row => row.kind === "source" && row.phase === 2) && allowed("prepare") && <form className="panel reporting-form" aria-label={t("prepareTranche")} onSubmit={event => { event.preventDefault(); if (!locked && selectedTranche && source.claims.some(row => row.tranche_id === selectedTranche && row.state === "Available") && allowed("prepare")) submit(`/sources/${source.id}/tranches`, { tranche_id: selectedTranche }); }}>
      {choose("tranche", selectedTranche, setSelectedTranche, source.request.tranches.filter(row => source.claims.some(claim => claim.tranche_id === row.id && claim.state === "Available")), "id")}<button disabled={locked || !selectedTranche || !source.claims.some(row => row.tranche_id === selectedTranche && row.state === "Available")}>{t("prepareTranche")}</button>
    </form>}
    {source && plan && plan.phase === 2 && ["release", "accrue"].includes(plan.kind) && allowed("reverse") && <form className="panel reporting-form" aria-label={t("prepareInverse")} onSubmit={event => { event.preventDefault(); if (!locked && allowed("reverse")) submit(`/sources/${source.id}/reversals`, { ...inverse, original_plan_id: plan.id }); }}>
      {choose("period_id", inverse.period_id, value => setInverse(old => ({ ...old, period_id: value })), catalog.periods, "id", t("prepareInverse") + " · ")}
      {text("posting_date", inverse.posting_date, value => setInverse(old => ({ ...old, posting_date: value })), t("prepareInverse") + " · ")}{text("reason", inverse.reason, value => setInverse(old => ({ ...old, reason: value })), t("prepareInverse") + " · ")}
      <button disabled={locked}>{t("prepareInverse")}</button>
    </form>}
    {source && !source.cancelled && source.plans.every(row => row.phase !== 2 || !row.equation.native_effect_required) && allowed("prepare") && <form className="panel reporting-form" aria-label={t("cancel")} onSubmit={event => { event.preventDefault(); if (!locked && allowed("prepare")) submit(`/sources/${source.id}/cancellations`, { reason: cancelReason }); }}>{text("reason", cancelReason, setCancelReason, t("cancel") + " · ")}<button disabled={locked}>{t("cancel")}</button></form>}
  </>;
}
