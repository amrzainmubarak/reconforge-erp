import { useState } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import { EnterpriseResult, EnterpriseScopeFields, requireCount, requireRecord, requireText, useEnterpriseWorkflow } from "./enterpriseWorkflow";
import type { ResultField } from "./enterpriseWorkflow";
import "./FinancialReportingPage.css";

export interface ProjectMilestoneWorkspaceProps { locale: Locale }
export function ProjectMilestoneWorkspace({ locale }: ProjectMilestoneWorkspaceProps) {
  const isAr = locale === "ar", label = (en: string, ar: string) => isAr ? ar : en;
  const [scope, setScope] = useState({ workspace: "", organization: "", entity: "" });
  const workflow = useEnterpriseWorkflow(locale, scope);
  const [projectId, setProjectId] = useState("");
  const [milestoneId, setMilestoneId] = useState("");
  const [invoiceId, setInvoiceId] = useState("");
  const [issuedAt, setIssuedAt] = useState("");
  const [customerCode, setCustomerCode] = useState("");
  const [organizationCode, setOrganizationCode] = useState("");
  const [entityCode, setEntityCode] = useState("");
  const [periodId, setPeriodId] = useState("");
  const [postingDate, setPostingDate] = useState("");
  const [journalCode, setJournalCode] = useState("");
  const [commandId, setCommandId] = useState("");
  const [bindingId, setBindingId] = useState("");
  const [sourceDigest, setSourceDigest] = useState("");
  const [reversalReason, setReversalReason] = useState("");
  const [currency, setCurrency] = useState("");
  const disabled = workflow.loading || !workflow.signedIn || !scope.workspace.trim();
  const milestonePath = `projects/billing/milestones/${encodeURIComponent(milestoneId.trim())}`;
  const bindingPath = `projects/billing/finance/${encodeURIComponent(bindingId.trim())}`;
  function binding(value: unknown, expectedPhase?: string, expectedId?: string, expectedSource?: string): ResultField[] {
    const record = requireRecord(value), phase = requireText(record, "phase");
    if (!["Draft", "Reviewed", "Posted"].includes(phase) || (expectedPhase && phase !== expectedPhase) || !["ProjectMilestone", "Reversal"].includes(requireText(record, "source_kind"))) throw new Error("invalid_response");
    const amount = requireText(record, "amount_minor"), digest = requireText(record, "source_digest");
    if (!/^-?\d+$/.test(amount) || !/^[a-f0-9]{64}$/.test(digest)) throw new Error("invalid_response");
    return [ { label: label("Financial binding ID", "رقم الربط المالي"), value: requireText(record, "binding_id", expectedId) }, { label: label("Financial phase", "المرحلة المالية"), value: phase }, { label: label("Finance Core entry", "قيد النواة المالية"), value: requireText(record, "entry_id") }, { label: label("Original source", "المصدر الأصلي"), value: requireText(record, "source_id", expectedSource) }, { label: label("Source digest", "بصمة المصدر"), value: digest }, { label: label("Amount (minor units)", "المبلغ (وحدات صغرى)"), value: amount }, { label: label("Currency", "العملة"), value: requireText(record, "currency_code") }, { label: label("Currency precision", "دقة العملة"), value: requireCount(record, "currency_precision") } ];
  }
  const phaseBody = () => ({ command_id: commandId.trim(), expected_source_digest: sourceDigest.trim() });
  const phaseDisabled = disabled || !bindingId.trim() || !commandId.trim() || !/^[a-f0-9]{64}$/.test(sourceDigest.trim());
  return <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
    <header className="panel"><h1>{translate(locale, "projectMilestoneTitle")}</h1><p>{label("Read original milestones and prepare invoices through Finance Core. A draft is not a posted financial effect; review and posting require server authorization.", "اعرض المراحل الأصلية وجهّز الفواتير عبر النواة المالية. المسودة ليست أثراً مالياً مرحلاً؛ تتطلب المراجعة والترحيل صلاحية على الخادم.")}</p></header>
    <EnterpriseScopeFields locale={locale} scope={scope} onChange={setScope} />
    <section className="panel" aria-labelledby="project-source-heading"><h2 id="project-source-heading">{label("Project source records", "السجلات المصدرية للمشروع")}</h2>
      <label>{label("Project ID", "رقم المشروع")}<input maxLength={128} value={projectId} onChange={event => { workflow.clear(); setProjectId(event.target.value); }} /></label>
      <label>{label("Reporting currency", "عملة التقرير")}<input maxLength={6} value={currency} onChange={event => { workflow.clear(); setCurrency(event.target.value); }} /></label>
      <button type="button" disabled={disabled || !projectId.trim()} onClick={() => void workflow.execute(`projects/billing/tasks/${encodeURIComponent(projectId.trim())}`, value => {
        const record = requireRecord(value); requireText(record, "project_id", projectId.trim());
        if (!Array.isArray(record.tasks) || record.tasks.length > 1000) throw new Error("invalid_response");
        const ids = new Set<string>();
        const fields: ResultField[] = [{ label: label("Project ID", "رقم المشروع"), value: projectId.trim() }, { label: label("Task count", "عدد المهام"), value: record.tasks.length }];
        for (const item of record.tasks) { const task = requireRecord(item), id = requireText(task, "task_id"); if (ids.has(id)) throw new Error("invalid_response"); ids.add(id); fields.push({ label: `${requireText(task, "task_code")} — ${requireText(task, "name")}`, value: requireText(task, "status") }, { label: label("Task budget (minor units)", "ميزانية المهمة (وحدات صغرى)"), value: requireCount(task, "budget_cost_minor") }, { label: label("Currency", "العملة"), value: requireText(task, "currency") }); }
        return fields;
      })}>{label("Load WBS tasks", "عرض مهام هيكل العمل")}</button>
      <button type="button" disabled={disabled || !projectId.trim() || !currency.trim()} onClick={() => void workflow.execute(`projects/billing/summary/${encodeURIComponent(projectId.trim())}?currency=${encodeURIComponent(currency.trim())}`, value => {
        const record = requireRecord(value); requireText(record, "project_id", projectId.trim()); requireText(record, "currency", currency.trim());
        return [{ label: label("Currency", "العملة"), value: currency.trim() }, { label: label("Source budget (minor units)", "ميزانية المصدر (وحدات صغرى)"), value: requireCount(record, "budget_cost_minor") }, { label: label("Source actual cost (minor units)", "التكلفة الفعلية للمصدر (وحدات صغرى)"), value: requireCount(record, "actual_cost_minor") }, { label: label("Source billed total (minor units)", "إجمالي فواتير المصدر (وحدات صغرى)"), value: requireCount(record, "total_billed_minor") }, { label: label("Unbilled work (minor units)", "العمل غير المفوتر (وحدات صغرى)"), value: requireCount(record, "unbilled_wip_minor") }];
      })}>{label("Load source billing summary", "عرض ملخص فواتير المصدر")}</button>
      <p>{label("The source summary is operational; use Finance Core reports to verify posted balances.", "ملخص المصدر تشغيلي؛ تحقق من الأرصدة المرحلة عبر تقارير النواة المالية.")}</p>
    </section>
    <section className="panel" aria-labelledby="milestone-source-heading"><h2 id="milestone-source-heading">{label("Milestone verification", "التحقق من المرحلة")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(milestonePath, value => { const record = requireRecord(value); return [{ label: label("Milestone ID", "رقم المرحلة"), value: requireText(record, "milestone_id", milestoneId.trim()) }, { label: label("Project ID", "رقم المشروع"), value: requireText(record, "project_id") }, { label: label("Title", "العنوان"), value: requireText(record, "title") }, { label: label("Status", "الحالة"), value: requireText(record, "status") }, { label: label("Amount (minor units)", "المبلغ (وحدات صغرى)"), value: requireCount(record, "milestone_amount_minor") }, { label: label("Currency", "العملة"), value: requireText(record, "currency") }]; }); }}><label>{label("Milestone ID", "رقم المرحلة")}<input required maxLength={128} value={milestoneId} onChange={event => { workflow.clear(); setMilestoneId(event.target.value); }} /></label><button disabled={disabled}>{label("Load milestone", "عرض المرحلة")}</button></form>
      <button type="button" disabled={disabled || !milestoneId.trim()} onClick={() => void workflow.execute(`${milestonePath}/verify`, value => { const record = requireRecord(value); requireText(record, "status", "verified"); return [{ label: label("Milestone ID", "رقم المرحلة"), value: requireText(record, "milestone_id", milestoneId.trim()) }, { label: label("Verified by", "تحقق بواسطة"), value: requireText(record, "verified_by") }]; }, {})}>{label("Verify deliverable", "التحقق من التسليم")}</button>
    </section>
    <section className="panel" aria-labelledby="milestone-finance-heading"><h2 id="milestone-finance-heading">{label("Governed financial commands", "الأوامر المالية الخاضعة للرقابة")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${milestonePath}/bill`, value => { const record = requireRecord(value); requireText(record, "status", "prepared"); requireText(record, "invoice_id", invoiceId.trim()); return binding(record.financial_binding, "Draft", undefined, invoiceId.trim()); }, { invoice_id: invoiceId.trim(), issued_at: issuedAt.trim(), customer_code: customerCode.trim(), financial_context: { command_id: commandId.trim(), organization_code: organizationCode.trim(), entity_code: entityCode.trim(), period_id: periodId.trim(), posting_date: postingDate, journal_code: journalCode.trim() } }); }}>
        <label>{label("Invoice ID", "رقم الفاتورة")}<input required maxLength={128} value={invoiceId} onChange={event => { workflow.clear(); setInvoiceId(event.target.value); }} /></label><label>{label("Issue timestamp (UTC)", "وقت إصدار الفاتورة (UTC)")}<input required maxLength={64} pattern=".*Z" value={issuedAt} onChange={event => { workflow.clear(); setIssuedAt(event.target.value); }} /></label><label>{label("Customer code", "رمز العميل")}<input required maxLength={128} value={customerCode} onChange={event => { workflow.clear(); setCustomerCode(event.target.value); }} /></label><label>{label("Organization code", "رمز المنظمة")}<input required maxLength={64} value={organizationCode} onChange={event => { workflow.clear(); setOrganizationCode(event.target.value); }} /></label><label>{label("Entity code", "رمز الكيان")}<input required maxLength={64} value={entityCode} onChange={event => { workflow.clear(); setEntityCode(event.target.value); }} /></label><label>{label("Fiscal period ID", "رقم الفترة المالية")}<input required maxLength={160} value={periodId} onChange={event => { workflow.clear(); setPeriodId(event.target.value); }} /></label><label>{label("Posting date", "تاريخ الترحيل")}<input type="date" required value={postingDate} onChange={event => { workflow.clear(); setPostingDate(event.target.value); }} /></label><label>{label("Journal code", "رمز اليومية")}<input required maxLength={64} value={journalCode} onChange={event => { workflow.clear(); setJournalCode(event.target.value); }} /></label><label>{label("Command ID (reuse for retry)", "رقم الأمر (أعد استخدامه للمحاولة نفسها)")}<input required maxLength={140} value={commandId} onChange={event => { workflow.clear(); setCommandId(event.target.value); }} /></label><button disabled={disabled || !milestoneId.trim() || !scope.organization.trim() || !scope.entity.trim()}>{label("Prepare invoice draft", "تجهيز مسودة الفاتورة")}</button>
      </form>
      <label>{label("Financial binding ID", "رقم الربط المالي")}<input maxLength={160} value={bindingId} onChange={event => { workflow.clear(); setBindingId(event.target.value); }} /></label><label>{label("Expected source digest", "بصمة المصدر المتوقعة")}<input maxLength={64} value={sourceDigest} onChange={event => { workflow.clear(); setSourceDigest(event.target.value); }} /></label>
      <button type="button" disabled={disabled || !bindingId.trim()} onClick={() => void workflow.execute(bindingPath, value => binding(value, undefined, bindingId.trim()))}>{label("Load financial binding", "عرض الربط المالي")}</button>
      <button type="button" disabled={phaseDisabled} onClick={() => void workflow.execute(`${bindingPath}/review`, value => binding(value, "Reviewed", bindingId.trim()), phaseBody())}>{label("Review financial draft", "مراجعة المسودة المالية")}</button>
      <button type="button" disabled={phaseDisabled} onClick={() => void workflow.execute(`${bindingPath}/post`, value => binding(value, "Posted", bindingId.trim()), phaseBody())}>{label("Post reviewed entry", "ترحيل القيد المراجع")}</button>
      <label>{label("Reversal reason", "سبب العكس")}<input maxLength={500} value={reversalReason} onChange={event => { workflow.clear(); setReversalReason(event.target.value); }} /></label>
      <button type="button" disabled={phaseDisabled || !reversalReason.trim() || !periodId.trim() || !postingDate} onClick={() => void workflow.execute(`${bindingPath}/reversal`, value => binding(value, "Draft"), { ...phaseBody(), period_id: periodId.trim(), posting_date: postingDate, reason: reversalReason.trim() })}>{label("Prepare reversal draft", "تجهيز مسودة العكس")}</button>
    </section>
    <EnterpriseResult locale={locale} workflow={workflow} />
  </div>;
}
