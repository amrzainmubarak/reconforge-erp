import { useState, type FormEvent } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import "./FinancialReportingPage.css";

export interface HcmLeaveWorkspaceProps {
  locale: Locale;
}

export interface LeaveBalance {
  leave_type: string;
  accrued_days: number;
  used_days: number;
  pending_days: number;
  remaining_days: number;
}

export interface LeaveRequestItem {
  id: string;
  employee_user_id: string;
  leave_type: "annual" | "sick" | "unpaid";
  start_date: string;
  end_date: string;
  days_count: number;
  reason: string;
  status: "Draft" | "Submitted" | "Approved" | "Rejected" | "Cancelled" | "Withdrawn";
  approver_user_id?: string;
  created_at: string;
}

export function HcmLeaveWorkspace({ locale }: HcmLeaveWorkspaceProps) {
  const isAr = locale === "ar";
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  // Balances state
  const [balances, setBalances] = useState<LeaveBalance[]>([
    { leave_type: "annual", accrued_days: 21, used_days: 7, pending_days: 0, remaining_days: 14 },
    { leave_type: "sick", accrued_days: 15, used_days: 3, pending_days: 0, remaining_days: 12 },
    { leave_type: "unpaid", accrued_days: 0, used_days: 0, pending_days: 0, remaining_days: 0 },
  ]);

  // Request list state
  const [requests, setRequests] = useState<LeaveRequestItem[]>([
    {
      id: "LR-2026-001",
      employee_user_id: "EMP-1001",
      leave_type: "annual",
      start_date: "2026-11-01",
      end_date: "2026-11-05",
      days_count: 5,
      reason: isAr ? "إجازة عائلية سنوية" : "Annual family vacation",
      status: "Submitted",
      created_at: "2026-10-15T09:00:00Z",
    },
    {
      id: "LR-2026-002",
      employee_user_id: "EMP-1002",
      leave_type: "sick",
      start_date: "2026-10-10",
      end_date: "2026-10-12",
      days_count: 2,
      reason: isAr ? "وعكة صحية طارئة" : "Emergency medical leave",
      status: "Approved",
      approver_user_id: "MGR-5001",
      created_at: "2026-10-09T08:30:00Z",
    },
  ]);

  // Submit form state
  const [empId, setEmpId] = useState("EMP-1001");
  const [leaveType, setLeaveType] = useState<"annual" | "sick" | "unpaid">("annual");
  const [startDate, setStartDate] = useState("2026-11-10");
  const [endDate, setEndDate] = useState("2026-11-12");
  const [reason, setReason] = useState("");
  const [approverId, setApproverId] = useState("MGR-5001");
  const [feedback, setFeedback] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const calculateDays = (start: string, end: string): number => {
    if (!start || !end) return 1;
    const diff = new Date(end).getTime() - new Date(start).getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24)) + 1;
    return days > 0 ? days : 1;
  };

  const handleSubmitRequest = (e: FormEvent) => {
    e.preventDefault();
    if (!empId.trim() || !startDate || !endDate) {
      setFeedback({ message: isAr ? "يرجى تعبئة جميع الحقول المطلوبة" : "Please complete all required fields", type: "error" });
      return;
    }
    const days = calculateDays(startDate, endDate);
    const newReq: LeaveRequestItem = {
      id: `LR-2026-${String(requests.length + 1).padStart(3, "0")}`,
      employee_user_id: empId.trim(),
      leave_type: leaveType,
      start_date: startDate,
      end_date: endDate,
      days_count: days,
      reason: reason.trim() || (isAr ? "طلب إجازة اعتيادية" : "Regular leave request"),
      status: "Submitted",
      created_at: new Date().toISOString(),
    };
    setRequests([newReq, ...requests]);
    setFeedback({
      message: isAr ? `تم تقديم طلب الإجازة بنجاح (${newReq.id})` : `Leave request submitted successfully (${newReq.id})`,
      type: "success",
    });
    setReason("");
  };

  const handleApprove = (reqId: string, employeeUserId: string) => {
    const cleanApprover = approverId.trim();
    if (cleanApprover.toLowerCase() === employeeUserId.trim().toLowerCase()) {
      setFeedback({
        message: isAr
          ? "مخالفة فصل الصلاحيات (SoD): لا يمكن للموظف اعتماد طلبه بنفسه!"
          : "Separation of Duties violation: Approver cannot be the employee requesting leave!",
        type: "error",
      });
      return;
    }
    setRequests(
      requests.map((r) =>
        r.id === reqId ? { ...r, status: "Approved", approver_user_id: cleanApprover } : r
      )
    );
    // Deduct from balance
    const target = requests.find((r) => r.id === reqId);
    if (target) {
      setBalances((prev) =>
        prev.map((b) =>
          b.leave_type === target.leave_type
            ? {
                ...b,
                used_days: b.used_days + target.days_count,
                remaining_days: Math.max(0, b.remaining_days - target.days_count),
              }
            : b
        )
      );
    }
    setFeedback({
      message: isAr ? `تم اعتماد الطلب ${reqId} بنجاح` : `Request ${reqId} approved successfully`,
      type: "success",
    });
  };

  const handleReject = (reqId: string) => {
    setRequests(requests.map((r) => (r.id === reqId ? { ...r, status: "Rejected" } : r)));
    setFeedback({
      message: isAr ? `تم رفض الطلب ${reqId}` : `Request ${reqId} rejected`,
      type: "success",
    });
  };

  const handleWithdraw = (reqId: string) => {
    setRequests(requests.map((r) => (r.id === reqId ? { ...r, status: "Withdrawn" } : r)));
    setFeedback({
      message: isAr ? `تم سحب الطلب ${reqId}` : `Request ${reqId} withdrawn`,
      type: "success",
    });
  };

  const handleCancel = (reqId: string) => {
    setRequests(requests.map((r) => (r.id === reqId ? { ...r, status: "Cancelled" } : r)));
    setFeedback({
      message: isAr ? `تم إلغاء الطلب ${reqId}` : `Request ${reqId} cancelled`,
      type: "success",
    });
  };

  const handleRollover = () => {
    setBalances((prev) =>
      prev.map((b) =>
        b.leave_type === "annual"
          ? {
              ...b,
              accrued_days: 21 + Math.min(b.remaining_days, 5),
              remaining_days: 21 + Math.min(b.remaining_days, 5),
              used_days: 0,
            }
          : b
      )
    );
    setFeedback({
      message: isAr
        ? "تم ترحيل رصيد نهاية العام بنجاح (بحد أقصى 5 أيام محالة للعام القادم)"
        : "Year-end rollover completed successfully (max 5 days carried forward)",
      type: "success",
    });
  };

  return (
    <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
      <header className="panel" style={{ background: "#16324f", color: "#ffffff" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>{t("hcmLeaveTitle")}</h1>
        <p style={{ margin: "0.5rem 0 0", opacity: 0.9 }}>{t("hcmLeaveSubtitle")}</p>
      </header>

      {feedback && (
        <div
          role="alert"
          tabIndex={0}
          style={{
            padding: "1rem",
            borderRadius: "8px",
            backgroundColor: feedback.type === "error" ? "#fee4e2" : "#ecfdf3",
            color: feedback.type === "error" ? "#7a1710" : "#02542d",
            border: `1px solid ${feedback.type === "error" ? "#fecdca" : "#abefc6"}`,
            fontWeight: 600,
          }}
        >
          {feedback.message}
        </div>
      )}

      {/* Leave Balances Grid */}
      <section aria-labelledby="hcm-balances-heading" className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 id="hcm-balances-heading" style={{ margin: 0, fontSize: "1.2rem", color: "#16324f" }}>
            {isAr ? "أرصدة إجازات الموظف" : "Employee Leave Balances"}
          </h2>
          <button
            type="button"
            onClick={handleRollover}
            style={{
              padding: "0.5rem 1rem",
              background: "#0c6257",
              color: "#ffffff",
              border: 0,
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {t("hcmActionRollover")}
          </button>
        </div>

        <div className="reporting-statement-grid">
          {balances.map((b) => (
            <article
              key={b.leave_type}
              style={{
                background: "#ffffff",
                border: "1px solid #dce3ea",
                borderRadius: "8px",
                padding: "1rem",
              }}
            >
              <h3 style={{ margin: "0 0 0.5rem", fontSize: "1.1rem", textTransform: "capitalize", color: "#16324f" }}>
                {b.leave_type === "annual" ? t("hcmAnnualBalance") : b.leave_type === "sick" ? t("hcmSickBalance") : t("hcmUnpaidBalance")}
              </h3>
              <p style={{ margin: "0.25rem 0", color: "#344054" }}>
                <strong>{isAr ? "المستحق:" : "Accrued:"}</strong> {b.accrued_days} {isAr ? "أيام" : "days"}
              </p>
              <p style={{ margin: "0.25rem 0", color: "#344054" }}>
                <strong>{isAr ? "المستهلك:" : "Used:"}</strong> {b.used_days} {isAr ? "أيام" : "days"}
              </p>
              <p style={{ margin: "0.5rem 0 0", fontSize: "1.25rem", color: "#0c6257", fontWeight: 700 }}>
                <strong>{isAr ? "المتبقي:" : "Remaining:"}</strong> {b.remaining_days} {isAr ? "أيام" : "days"}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* Submit Leave Request Form */}
      <section aria-labelledby="hcm-submit-heading" className="panel">
        <h2 id="hcm-submit-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("hcmRequestSubmit")}
        </h2>
        <form onSubmit={handleSubmitRequest} className="reporting-form">
          <div>
            <label htmlFor="hcm-emp-id">{t("hcmEmployeeId")}</label>
            <input
              id="hcm-emp-id"
              type="text"
              value={empId}
              onChange={(e) => setEmpId(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="hcm-leave-type">{t("hcmLeaveType")}</label>
            <select
              id="hcm-leave-type"
              value={leaveType}
              onChange={(e) => setLeaveType(e.target.value as "annual" | "sick" | "unpaid")}
            >
              <option value="annual">{isAr ? "سنوية" : "Annual"}</option>
              <option value="sick">{isAr ? "مرضية" : "Sick"}</option>
              <option value="unpaid">{isAr ? "بدون راتب" : "Unpaid"}</option>
            </select>
          </div>
          <div>
            <label htmlFor="hcm-start-date">{t("hcmStartDate")}</label>
            <input
              id="hcm-start-date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="hcm-end-date">{t("hcmEndDate")}</label>
            <input
              id="hcm-end-date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="hcm-reason">{t("hcmReason")}</label>
            <input
              id="hcm-reason"
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={isAr ? "سبب طلب الإجازة..." : "Vacation, medical, personal..."}
            />
          </div>
          <div>
            <button
              type="submit"
              style={{
                padding: "0.6rem 1.2rem",
                background: "#16324f",
                color: "#ffffff",
                border: 0,
                borderRadius: "6px",
                cursor: "pointer",
                fontWeight: 600,
                width: "100%",
              }}
            >
              {t("hcmRequestSubmit")}
            </button>
          </div>
        </form>
      </section>

      {/* Governance & Approvals Section */}
      <section aria-labelledby="hcm-requests-heading" className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h2 id="hcm-requests-heading" style={{ margin: 0, fontSize: "1.2rem", color: "#16324f" }}>
            {isAr ? "طلبات الإجازات وقرارات الحوكمة" : "Leave Requests & Governance Queue"}
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <label htmlFor="hcm-approver-id" style={{ margin: 0, fontSize: "0.85rem", fontWeight: 600 }}>
              {isAr ? "المعتمد الحالي:" : "Current Approver:"}
            </label>
            <input
              id="hcm-approver-id"
              type="text"
              value={approverId}
              onChange={(e) => setApproverId(e.target.value)}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccd6e0" }}
            />
          </div>
        </div>
        <p style={{ margin: "0 0 1rem", fontSize: "0.85rem", color: "#593800", background: "#fff4cc", padding: "0.5rem", borderRadius: "4px" }}>
          {t("hcmSodWarning")}
        </p>

        <div className="reporting-table">
          <table aria-label={isAr ? "جدول طلبات الإجازات" : "Leave Requests Table"}>
            <thead>
              <tr>
                <th>{isAr ? "رقم الطلب" : "Request ID"}</th>
                <th>{t("hcmEmployeeId")}</th>
                <th>{t("hcmLeaveType")}</th>
                <th>{t("hcmStartDate")}</th>
                <th>{t("hcmEndDate")}</th>
                <th>{t("hcmDaysCount")}</th>
                <th>{t("hcmReason")}</th>
                <th>{isAr ? "الحالة" : "Status"}</th>
                <th>{isAr ? "إجراءات الحوكمة" : "Actions"}</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => {
                const statusBadgeStyle = {
                  padding: "0.2rem 0.6rem",
                  borderRadius: "999px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  backgroundColor:
                    r.status === "Approved"
                      ? "#ecfdf3"
                      : r.status === "Rejected"
                      ? "#fee4e2"
                      : r.status === "Submitted"
                      ? "#fff4cc"
                      : "#e8eef5",
                  color:
                    r.status === "Approved"
                      ? "#02542d"
                      : r.status === "Rejected"
                      ? "#7a1710"
                      : r.status === "Submitted"
                      ? "#593800"
                      : "#16324f",
                };

                return (
                  <tr key={r.id}>
                    <td><code>{r.id}</code></td>
                    <td>{r.employee_user_id}</td>
                    <td style={{ textTransform: "capitalize" }}>{r.leave_type}</td>
                    <td>{r.start_date}</td>
                    <td>{r.end_date}</td>
                    <td><strong>{r.days_count}</strong></td>
                    <td>{r.reason}</td>
                    <td>
                      <span style={statusBadgeStyle}>
                        {r.status === "Approved"
                          ? t("hcmStatusApproved")
                          : r.status === "Rejected"
                          ? t("hcmStatusRejected")
                          : r.status === "Submitted"
                          ? t("hcmStatusSubmitted")
                          : r.status === "Withdrawn"
                          ? t("hcmStatusWithdrawn")
                          : r.status === "Cancelled"
                          ? t("hcmStatusCancelled")
                          : t("hcmStatusDraft")}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                        {r.status === "Submitted" && (
                          <>
                            <button
                              type="button"
                              onClick={() => handleApprove(r.id, r.employee_user_id)}
                              style={{
                                padding: "0.25rem 0.5rem",
                                background: "#02542d",
                                color: "#ffffff",
                                border: 0,
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontSize: "0.8rem",
                              }}
                            >
                              {t("hcmActionApprove")}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleReject(r.id)}
                              style={{
                                padding: "0.25rem 0.5rem",
                                background: "#7a1710",
                                color: "#ffffff",
                                border: 0,
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontSize: "0.8rem",
                              }}
                            >
                              {t("hcmActionReject")}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleWithdraw(r.id)}
                              style={{
                                padding: "0.25rem 0.5rem",
                                background: "#475467",
                                color: "#ffffff",
                                border: 0,
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontSize: "0.8rem",
                              }}
                            >
                              {t("hcmActionWithdraw")}
                            </button>
                          </>
                        )}
                        {r.status === "Approved" && (
                          <button
                            type="button"
                            onClick={() => handleCancel(r.id)}
                            style={{
                              padding: "0.25rem 0.5rem",
                              background: "#d92d20",
                              color: "#ffffff",
                              border: 0,
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontSize: "0.8rem",
                            }}
                          >
                            {t("hcmActionCancel")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default HcmLeaveWorkspace;
