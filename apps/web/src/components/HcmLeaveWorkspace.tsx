import { useState } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import { EnterpriseResult, EnterpriseScopeFields, requireCount, requireRecord, requireText, useEnterpriseWorkflow } from "./enterpriseWorkflow";
import type { ResultField } from "./enterpriseWorkflow";
import "./FinancialReportingPage.css";

export interface HcmLeaveWorkspaceProps { locale: Locale }
const leaveTypes = ["Annual", "Sick", "Unpaid", "Parental", "Bereavement"] as const;
const leaveStatuses = ["Draft", "Submitted", "Approved", "Rejected", "Cancelled", "Withdrawn"];

export function HcmLeaveWorkspace({ locale }: HcmLeaveWorkspaceProps) {
  const isAr = locale === "ar";
  const label = (en: string, ar: string) => isAr ? ar : en;
  const [scope, setScope] = useState({ workspace: "", organization: "", entity: "" });
  const workflow = useEnterpriseWorkflow(locale, scope);
  const [requestId, setRequestId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [leaveType, setLeaveType] = useState<string>("Annual");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [days, setDays] = useState("1");
  const [reason, setReason] = useState("");
  const [actionDate, setActionDate] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const disabled = workflow.loading || !workflow.signedIn || !scope.workspace.trim();
  const requestPath = `hcm/leave/requests/${encodeURIComponent(requestId.trim())}`;
  function mutation(value: unknown, expected: string): ResultField[] {
    const record = requireRecord(value);
    requireText(record, "status", "success"); requireText(record, "request_id", requestId.trim());
    return [{ label: label("Request ID", "رقم الطلب"), value: requireText(record, "request_id") }, { label: label("Persisted leave status", "حالة الإجازة المحفوظة"), value: requireText(record, "leave_status", expected) }];
  }
  const readRequest = (value: unknown): ResultField[] => {
    const record = requireRecord(value);
    const status = requireText(record, "status");
    if (!leaveStatuses.includes(status) || !leaveTypes.includes(requireText(record, "leave_type") as typeof leaveTypes[number])) throw new Error("invalid_response");
    return [
      { label: label("Request ID", "رقم الطلب"), value: requireText(record, "request_id", requestId.trim()) },
      { label: label("Employee", "الموظف"), value: requireText(record, "employee_id") },
      { label: label("Request owner", "صاحب الطلب"), value: requireText(record, "employee_user_id") },
      { label: label("Leave type", "نوع الإجازة"), value: requireText(record, "leave_type") },
      { label: label("Start date", "تاريخ البداية"), value: requireText(record, "start_date") },
      { label: label("End date", "تاريخ النهاية"), value: requireText(record, "end_date") },
      { label: label("Requested days", "الأيام المطلوبة"), value: requireCount(record, "requested_days") },
      { label: label("Persisted leave status", "حالة الإجازة المحفوظة"), value: status },
    ];
  };
  return <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
    <header className="panel"><h1>{translate(locale, "hcmLeaveTitle")}</h1><p>{label("Leave requests and balances from the authorized database. Approval uses your signed-in identity and server policy.", "طلبات وأرصدة الإجازات من قاعدة البيانات المخولة. يعتمد الخادم هويتك المسجلة وسياسة الصلاحيات عند الاعتماد.")}</p></header>
    <EnterpriseScopeFields locale={locale} scope={scope} onChange={setScope} />
    <section className="panel" aria-labelledby="leave-request-heading"><h2 id="leave-request-heading">{label("Leave request", "طلب إجازة")}</h2>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(requestPath, readRequest); }}>
        <label>{label("Request ID", "رقم الطلب")}<input required maxLength={64} value={requestId} onChange={event => { workflow.clear(); setRequestId(event.target.value); }} /></label>
        <button disabled={disabled || !requestId.trim()}>{label("Load request", "عرض الطلب")}</button>
      </form>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute("hcm/leave/requests", value => mutation(value, "Submitted"), { request_id: requestId.trim(), employee_id: employeeId.trim(), leave_type: leaveType, start_date: startDate, end_date: endDate, requested_days: Number(days), reason: reason.trim() }); }}>
        <label>{label("Employee ID", "معرّف الموظف")}<input required maxLength={64} value={employeeId} onChange={event => { workflow.clear(); setEmployeeId(event.target.value); }} /></label>
        <label>{label("Leave type", "نوع الإجازة")}<select value={leaveType} onChange={event => { workflow.clear(); setLeaveType(event.target.value); }}>{leaveTypes.map(type => <option key={type}>{type}</option>)}</select></label>
        <label>{label("Start date", "تاريخ البداية")}<input type="date" required value={startDate} onChange={event => { workflow.clear(); setStartDate(event.target.value); }} /></label>
        <label>{label("End date", "تاريخ النهاية")}<input type="date" required value={endDate} onChange={event => { workflow.clear(); setEndDate(event.target.value); }} /></label>
        <label>{label("Requested days", "الأيام المطلوبة")}<input type="number" min={1} max={365} step={1} required value={days} onChange={event => { workflow.clear(); setDays(event.target.value); }} /></label>
        <label>{label("Reason", "السبب")}<input required maxLength={500} value={reason} onChange={event => { workflow.clear(); setReason(event.target.value); }} /></label>
        <button disabled={disabled || !requestId.trim()}>{label("Submit request", "تقديم الطلب")}</button>
      </form>
      <div className="reporting-form"><button type="button" disabled={disabled || !requestId.trim()} onClick={() => void workflow.execute(`${requestPath}/approve`, value => mutation(value, "Approved"), {})}>{label("Approve request", "اعتماد الطلب")}</button>
        <button type="button" disabled={disabled || !requestId.trim()} onClick={() => void workflow.execute(`${requestPath}/withdraw`, value => mutation(value, "Cancelled"), {})}>{label("Withdraw own request", "سحب طلبي")}</button></div>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${requestPath}/reject`, value => mutation(value, "Rejected"), { rejection_reason: rejectionReason.trim() }); }}><label>{label("Rejection reason", "سبب الرفض")}<input required maxLength={500} value={rejectionReason} onChange={event => { workflow.clear(); setRejectionReason(event.target.value); }} /></label><button disabled={disabled || !requestId.trim()}>{label("Reject request", "رفض الطلب")}</button></form>
      <form className="reporting-form" onSubmit={event => { event.preventDefault(); void workflow.execute(`${requestPath}/cancel`, value => mutation(value, "Cancelled"), { current_date: actionDate }); }}><label>{label("Cancellation date", "تاريخ الإلغاء")}<input type="date" required value={actionDate} onChange={event => { workflow.clear(); setActionDate(event.target.value); }} /></label><button disabled={disabled || !requestId.trim()}>{label("Cancel approved request", "إلغاء الطلب المعتمد")}</button></form>
      <button type="button" disabled={disabled || !employeeId.trim()} onClick={() => void workflow.execute(`hcm/leave/balances/${encodeURIComponent(employeeId.trim())}/${encodeURIComponent(leaveType)}`, value => {
        const record = requireRecord(value); requireText(record, "employee_id", employeeId.trim()); requireText(record, "leave_type", leaveType);
        return [ { label: label("Employee", "الموظف"), value: employeeId.trim() }, { label: label("Accrued days", "الأيام المستحقة"), value: requireCount(record, "accrued_days") }, { label: label("Consumed days", "الأيام المستخدمة"), value: requireCount(record, "consumed_days") }, { label: label("Available days", "الأيام المتاحة"), value: requireCount(record, "available_days") } ];
      })}>{label("Load entitlement balance", "عرض رصيد الإجازة")}</button>
    </section>
    <EnterpriseResult locale={locale} workflow={workflow} />
  </div>;
}
