import { useState } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import { EnterpriseResult, EnterpriseScopeFields, requireCount, requireRecord, requireText, useEnterpriseWorkflow } from "./enterpriseWorkflow";
import type { ResultField } from "./enterpriseWorkflow";
import "./FinancialReportingPage.css";

export interface CrmSubscriptionWorkspaceProps { locale: Locale }
export function CrmSubscriptionWorkspace({ locale }: CrmSubscriptionWorkspaceProps) {
  const isAr = locale === "ar", label = (en: string, ar: string) => isAr ? ar : en;
  const [scope, setScope] = useState({ workspace: "", organization: "", entity: "" });
  const workflow = useEnterpriseWorkflow(locale, scope);
  const [opportunityId, setOpportunityId] = useState("");
  const [quoteId, setQuoteId] = useState("");
  const [contractId, setContractId] = useState("");
  const [approverRole, setApproverRole] = useState("sales_rep");
  const [reason, setReason] = useState("");
  const [newEndDate, setNewEndDate] = useState("");
  const [adjustment, setAdjustment] = useState("0");
  const [oldPlanId, setOldPlanId] = useState("");
  const [newPlanId, setNewPlanId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [changeDate, setChangeDate] = useState("");
  const disabled = workflow.loading || !workflow.signedIn || !scope.workspace.trim();
  const path = "crm/contracts";
  const contractPath = `${path}/contracts/${encodeURIComponent(contractId.trim())}`;
  const quotePath = `${path}/quotations/${encodeURIComponent(quoteId.trim())}`;
  function contractMutation(value: unknown, expected: string): ResultField[] {
    const record = requireRecord(value); requireText(record, "status", "success");
    return [{ label: label("Contract ID", "رقم العقد"), value: requireText(record, "contract_id", contractId.trim()) }, { label: label("Persisted contract status", "حالة العقد المحفوظة"), value: requireText(record, "contract_status", expected) }];
  }
  return <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
    <header className="panel"><h1>{translate(locale, "crmSubscriptionTitle")}</h1><p>{label("Load source records before reviewing business decisions. The server verifies approval authority and persists each accepted action.", "اعرض السجلات المصدرية لمراجعة القرارات. يتحقق الخادم من صلاحية الاعتماد ويحفظ كل إجراء مقبول.")}</p></header>
    <EnterpriseScopeFields locale={locale} scope={scope} onChange={setScope} />
    <section className="panel" aria-labelledby="crm-opportunity-heading"><h2 id="crm-opportunity-heading">{label("Opportunity", "الفرصة البيعية")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${path}/opportunities/${encodeURIComponent(opportunityId.trim())}`, value => {
        const record = requireRecord(value); return [{ label: label("Opportunity ID", "رقم الفرصة"), value: requireText(record, "opportunity_id", opportunityId.trim()) }, { label: label("Title", "العنوان"), value: requireText(record, "title") }, { label: label("Stage", "المرحلة"), value: requireText(record, "stage") }, { label: label("Currency", "العملة"), value: requireText(record, "currency") }, { label: label("Projected amount (minor units)", "القيمة المتوقعة (وحدات صغرى)"), value: requireCount(record, "projected_amount_minor") }, { label: label("Weighted amount (minor units)", "القيمة المرجحة (وحدات صغرى)"), value: requireCount(record, "weighted_pipeline_value_minor") }];
      }); }}><label>{label("Opportunity ID", "رقم الفرصة")}<input required maxLength={64} value={opportunityId} onChange={event => { workflow.clear(); setOpportunityId(event.target.value); }} /></label><button disabled={disabled}>{label("Load opportunity", "عرض الفرصة")}</button></form>
    </section>
    <section className="panel" aria-labelledby="crm-quotation-heading"><h2 id="crm-quotation-heading">{label("Quotation approval", "اعتماد عرض السعر")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(quotePath, value => {
        const record = requireRecord(value); return [{ label: label("Quotation ID", "رقم العرض"), value: requireText(record, "quote_id", quoteId.trim()) }, { label: label("Customer", "العميل"), value: requireText(record, "customer_id") }, { label: label("Submitter", "مقدم العرض"), value: requireText(record, "submitter_user_id") }, { label: label("Status", "الحالة"), value: requireText(record, "status") }, { label: label("Currency", "العملة"), value: requireText(record, "currency") }, { label: label("Total (minor units)", "الإجمالي (وحدات صغرى)"), value: requireCount(record, "total_net_minor") }, { label: label("Discount (basis points)", "الخصم (نقاط أساس)"), value: requireCount(record, "effective_discount_bps") }];
      }); }}><label>{label("Quotation ID", "رقم العرض")}<input required maxLength={64} value={quoteId} onChange={event => { workflow.clear(); setQuoteId(event.target.value); }} /></label><button disabled={disabled}>{label("Load quotation", "عرض عرض السعر")}</button></form>
      <label>{label("Requested approval role", "دور الاعتماد المطلوب")}<select value={approverRole} onChange={event => { workflow.clear(); setApproverRole(event.target.value); }}>{["sales_rep", "sales_manager", "commercial_director", "vp_sales", "cfo", "admin"].map(role => <option key={role}>{role}</option>)}</select></label>
      <p>{label("Your current server-assigned roles determine authority. A role selection does not grant permission.", "تحدد الأدوار المسندة إليك على الخادم صلاحياتك. اختيار الدور لا يمنح صلاحية.")}</p>
      <button type="button" disabled={disabled || !quoteId.trim()} onClick={() => void workflow.execute(`${quotePath}/approve`, value => {
        const record = requireRecord(value); requireText(record, "status", "success"); return [{ label: label("Quotation ID", "رقم العرض"), value: requireText(record, "quote_id", quoteId.trim()) }, { label: label("Persisted quotation status", "حالة العرض المحفوظة"), value: requireText(record, "quote_status", "approved") }, { label: label("Approved by", "اعتمد بواسطة"), value: requireText(record, "approved_by") }];
      }, { approver_role: approverRole })}>{label("Approve quotation", "اعتماد عرض السعر")}</button>
    </section>
    <section className="panel" aria-labelledby="crm-contract-heading"><h2 id="crm-contract-heading">{label("Contract lifecycle", "دورة حياة العقد")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(contractPath, value => {
        const record = requireRecord(value); return [{ label: label("Contract ID", "رقم العقد"), value: requireText(record, "contract_id", contractId.trim()) }, { label: label("Customer", "العميل"), value: requireText(record, "customer_id") }, { label: label("Status", "الحالة"), value: requireText(record, "status") }, { label: label("Currency", "العملة"), value: requireText(record, "currency") }, { label: label("Contract value (minor units)", "قيمة العقد (وحدات صغرى)"), value: requireCount(record, "total_contract_value_minor") }, { label: label("Start date", "تاريخ البداية"), value: requireText(record, "start_date") }, { label: label("End date", "تاريخ النهاية"), value: requireText(record, "end_date") }];
      }); }}><label>{label("Contract ID", "رقم العقد")}<input required maxLength={64} value={contractId} onChange={event => { workflow.clear(); setContractId(event.target.value); }} /></label><button disabled={disabled}>{label("Load contract", "عرض العقد")}</button></form>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${contractPath}/suspend`, value => contractMutation(value, "suspended"), { reason: reason.trim() }); }}><label>{label("Suspension reason", "سبب التعليق")}<input required maxLength={500} value={reason} onChange={event => { workflow.clear(); setReason(event.target.value); }} /></label><button disabled={disabled || !contractId.trim()}>{label("Suspend contract", "تعليق العقد")}</button></form>
      <button type="button" disabled={disabled || !contractId.trim()} onClick={() => void workflow.execute(`${contractPath}/resume`, value => contractMutation(value, "active"), {})}>{label("Resume contract", "استئناف العقد")}</button>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${contractPath}/renew`, value => contractMutation(value, "active"), { new_end_date: newEndDate, price_adjustment_bps: Number(adjustment) }); }}><label>{label("Renewal end date", "تاريخ نهاية التجديد")}<input type="date" required value={newEndDate} onChange={event => { workflow.clear(); setNewEndDate(event.target.value); }} /></label><label>{label("Price adjustment (basis points)", "تعديل السعر (نقاط أساس)")}<input type="number" required step={1} value={adjustment} onChange={event => { workflow.clear(); setAdjustment(event.target.value); }} /></label><button disabled={disabled || !contractId.trim()}>{label("Renew contract", "تجديد العقد")}</button></form>
    </section>
    <section className="panel" aria-labelledby="crm-proration-heading"><h2 id="crm-proration-heading">{label("Server-calculated plan change", "تغيير الخطة المحسوب على الخادم")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${path}/subscriptions/proration`, value => {
        const record = requireRecord(value); requireText(record, "status", "success"); requireText(record, "old_plan_id", oldPlanId.trim()); requireText(record, "new_plan_id", newPlanId.trim()); return [{ label: label("Credit (minor units)", "الائتمان (وحدات صغرى)"), value: requireCount(record, "unearned_credit_minor") }, { label: label("Charge (minor units)", "الرسم (وحدات صغرى)"), value: requireCount(record, "new_charge_minor") }, { label: label("Net (minor units)", "الصافي (وحدات صغرى)"), value: requireCount(record, "net_payable_minor") }, { label: label("Currency", "العملة"), value: requireText(record, "currency") }];
      }, { old_plan_id: oldPlanId.trim(), new_plan_id: newPlanId.trim(), period_start: periodStart, period_end: periodEnd, change_date: changeDate }); }}>
        <label>{label("Current plan ID", "رقم الخطة الحالية")}<input required maxLength={64} value={oldPlanId} onChange={event => { workflow.clear(); setOldPlanId(event.target.value); }} /></label><label>{label("New plan ID", "رقم الخطة الجديدة")}<input required maxLength={64} value={newPlanId} onChange={event => { workflow.clear(); setNewPlanId(event.target.value); }} /></label><label>{label("Period start", "بداية الفترة")}<input type="date" required value={periodStart} onChange={event => { workflow.clear(); setPeriodStart(event.target.value); }} /></label><label>{label("Period end", "نهاية الفترة")}<input type="date" required value={periodEnd} onChange={event => { workflow.clear(); setPeriodEnd(event.target.value); }} /></label><label>{label("Change date", "تاريخ التغيير")}<input type="date" required value={changeDate} onChange={event => { workflow.clear(); setChangeDate(event.target.value); }} /></label><button disabled={disabled}>{label("Calculate from saved plans", "الحساب من الخطط المحفوظة")}</button>
      </form>
    </section>
    <EnterpriseResult locale={locale} workflow={workflow} />
  </div>;
}
