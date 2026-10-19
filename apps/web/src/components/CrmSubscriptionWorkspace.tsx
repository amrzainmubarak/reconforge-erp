import { useState } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import "./FinancialReportingPage.css";

export interface CrmSubscriptionWorkspaceProps {
  locale: Locale;
}

export type PipelineStage = "prospecting" | "qualified" | "proposal" | "negotiation" | "won" | "lost";

export interface OpportunityItem {
  id: string;
  name: string;
  company: string;
  amount_minor: number;
  stage: PipelineStage;
  probability: number;
}

export interface QuotationItem {
  id: string;
  submitter_user_id: string;
  customer_name: string;
  total_minor: number;
  discount_bips: number; // e.g. 2000 = 20.00%
  status: "Draft" | "Submitted" | "Approved" | "Rejected";
  approver_user_id?: string;
}

export interface ContractItem {
  id: string;
  customer_name: string;
  plan_code: string;
  monthly_fee_minor: number;
  status: "Draft" | "Active" | "Suspended" | "Terminated";
  start_date: string;
  end_date: string;
}

export function CrmSubscriptionWorkspace({ locale }: CrmSubscriptionWorkspaceProps) {
  const isAr = locale === "ar";
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  // Opportunities state
  const [opportunities, setOpportunities] = useState<OpportunityItem[]>([
    {
      id: "OPP-001",
      name: isAr ? "ترقية البنية التحتية السحابية" : "Cloud Infrastructure Upgrade",
      company: "Apex Global LLC",
      amount_minor: 4500000,
      stage: "prospecting",
      probability: 20,
    },
    {
      id: "OPP-002",
      name: isAr ? "رخصة منصة الرقابة المؤسسية" : "Enterprise Control Platform License",
      company: "Nordic Tech AB",
      amount_minor: 12000000,
      stage: "proposal",
      probability: 60,
    },
    {
      id: "OPP-003",
      name: isAr ? "عقد دعم فني وتكامل مالي" : "Financial Integration Support Contract",
      company: "Al-Baraka Trading",
      amount_minor: 3200000,
      stage: "negotiation",
      probability: 80,
    },
    {
      id: "OPP-004",
      name: isAr ? "اشتراك سنوي للخدمات المصرفية" : "Banking Reconciliation Annual Subscription",
      company: "Horizon Capital",
      amount_minor: 8500000,
      stage: "won",
      probability: 100,
    },
  ]);

  // Quotations state
  const [quotations, setQuotations] = useState<QuotationItem[]>([
    {
      id: "QUO-801",
      submitter_user_id: "SALES_USER_01",
      customer_name: "Nordic Tech AB",
      total_minor: 12000000,
      discount_bips: 2000, // 20% discount (exceeds standard 15% threshold!)
      status: "Submitted",
    },
    {
      id: "QUO-802",
      submitter_user_id: "SALES_USER_02",
      customer_name: "Al-Baraka Trading",
      total_minor: 3200000,
      discount_bips: 1000, // 10% discount (within standard threshold)
      status: "Approved",
      approver_user_id: "SALES_DIRECTOR",
    },
  ]);

  // Contracts state
  const [contracts, setContracts] = useState<ContractItem[]>([
    {
      id: "CON-2026-01",
      customer_name: "Horizon Capital",
      plan_code: "ENTERPRISE_PREMIUM",
      monthly_fee_minor: 750000,
      status: "Active",
      start_date: "2026-01-01",
      end_date: "2026-12-31",
    },
    {
      id: "CON-2026-02",
      customer_name: "Al-Baraka Trading",
      plan_code: "STANDARD_COMMERCIAL",
      monthly_fee_minor: 350000,
      status: "Suspended",
      start_date: "2026-03-01",
      end_date: "2027-02-28",
    },
  ]);

  // Approver user state for quotations
  const [approverId, setApproverId] = useState("SALES_DIRECTOR");

  // Proration calculator state
  const [calcMonthlyFeeMinor, setCalcMonthlyFeeMinor] = useState(100000); // 1,000.00
  const [calcCycleStart, setCalcCycleStart] = useState("2026-10-01");
  const [calcCycleEnd, setCalcCycleEnd] = useState("2026-10-31");
  const [calcServiceStart, setCalcServiceStart] = useState("2026-10-11");
  const [feedback, setFeedback] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const formatCurrency = (minor: number) => {
    return (minor / 100).toLocaleString(isAr ? "ar-EG" : "en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const advanceStage = (oppId: string) => {
    const stageOrder: PipelineStage[] = ["prospecting", "qualified", "proposal", "negotiation", "won"];
    setOpportunities(
      opportunities.map((opp) => {
        if (opp.id !== oppId) return opp;
        const currentIndex = stageOrder.indexOf(opp.stage);
        if (currentIndex >= 0 && currentIndex < stageOrder.length - 1) {
          const nextStage = stageOrder[currentIndex + 1];
          const nextProb = nextStage === "won" ? 100 : Math.min(90, (currentIndex + 2) * 20);
          return { ...opp, stage: nextStage, probability: nextProb };
        }
        return opp;
      })
    );
  };

  const handleApproveQuotation = (quoId: string, submitterUserId: string) => {
    const cleanApprover = approverId.trim();
    if (cleanApprover.toLowerCase() === submitterUserId.trim().toLowerCase()) {
      setFeedback({
        message: isAr
          ? "مخالفة فصل الصلاحيات (SoD): لا يمكن للمندوب مقدم عرض السعر أن يعتمده بنفسه!"
          : "Separation of Duties violation: Submitter cannot approve their own quotation!",
        type: "error",
      });
      return;
    }
    setQuotations(
      quotations.map((q) =>
        q.id === quoId ? { ...q, status: "Approved", approver_user_id: cleanApprover } : q
      )
    );
    setFeedback({
      message: isAr ? `تم اعتماد عرض السعر ${quoId} بنجاح` : `Quotation ${quoId} approved successfully`,
      type: "success",
    });
  };

  const handleContractAction = (contractId: string, action: "Activate" | "Suspend" | "Resume" | "Renew" | "Terminate") => {
    setContracts(
      contracts.map((c) => {
        if (c.id !== contractId) return c;
        let nextStatus: ContractItem["status"] = c.status;
        if (action === "Activate" || action === "Resume") nextStatus = "Active";
        else if (action === "Suspend") nextStatus = "Suspended";
        else if (action === "Terminate") nextStatus = "Terminated";
        else if (action === "Renew") {
          return {
            ...c,
            status: "Active",
            end_date: "2027-12-31",
          };
        }
        return { ...c, status: nextStatus };
      })
    );
    setFeedback({
      message: isAr ? `تم تنفيذ إجراء (${action}) على العقد ${contractId}` : `Action (${action}) executed on ${contractId}`,
      type: "success",
    });
  };

  // Day proration calculation (Integer minor units, no floats)
  const calculateProration = () => {
    const cycleStartTime = new Date(calcCycleStart).getTime();
    const cycleEndTime = new Date(calcCycleEnd).getTime();
    const serviceStartTime = new Date(calcServiceStart).getTime();

    const totalDays = Math.max(1, Math.floor((cycleEndTime - cycleStartTime) / (1000 * 60 * 60 * 24)) + 1);
    const activeDays = Math.max(0, Math.min(totalDays, Math.floor((cycleEndTime - serviceStartTime) / (1000 * 60 * 60 * 24)) + 1));
    const proratedMinor = Math.round((calcMonthlyFeeMinor * activeDays) / totalDays);
    const refundMinor = calcMonthlyFeeMinor - proratedMinor;

    return { totalDays, activeDays, proratedMinor, refundMinor };
  };

  const prorationResult = calculateProration();

  return (
    <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
      <header className="panel" style={{ background: "#16324f", color: "#ffffff" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>{t("crmSubscriptionTitle")}</h1>
        <p style={{ margin: "0.5rem 0 0", opacity: 0.9 }}>{t("crmSubscriptionSubtitle")}</p>
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

      {/* Opportunity Pipeline / Kanban */}
      <section aria-labelledby="crm-pipeline-heading" className="panel">
        <h2 id="crm-pipeline-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {isAr ? "مسار الفرص البيعية (Opportunity Pipeline)" : "Opportunity Pipeline & Stages"}
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {(["prospecting", "qualified", "proposal", "negotiation", "won"] as PipelineStage[]).map((stage) => {
            const stageOpps = opportunities.filter((o) => o.stage === stage);
            const stageTotal = stageOpps.reduce((sum, o) => sum + o.amount_minor, 0);

            return (
              <div
                key={stage}
                style={{
                  background: "#ffffff",
                  border: "1px solid #dce3ea",
                  borderRadius: "8px",
                  padding: "0.75rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #edf1f5", paddingBottom: "0.5rem", marginBottom: "0.5rem" }}>
                  <h3 style={{ margin: 0, fontSize: "0.95rem", color: "#16324f" }}>
                    {stage === "prospecting"
                      ? t("crmPipelineProspecting")
                      : stage === "qualified"
                      ? t("crmPipelineQualified")
                      : stage === "proposal"
                      ? t("crmPipelineProposal")
                      : stage === "negotiation"
                      ? t("crmPipelineNegotiation")
                      : t("crmPipelineWon")}
                  </h3>
                  <span style={{ fontSize: "0.8rem", color: "#667085", fontWeight: 600 }}>({stageOpps.length})</span>
                </div>
                <div style={{ fontSize: "0.85rem", color: "#0c6257", fontWeight: 700, marginBottom: "0.5rem" }}>
                  {formatCurrency(stageTotal)}
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  {stageOpps.map((opp) => (
                    <article
                      key={opp.id}
                      style={{
                        padding: "0.5rem",
                        background: "#f8faf9",
                        borderRadius: "6px",
                        border: "1px solid #e7edf4",
                        fontSize: "0.85rem",
                      }}
                    >
                      <strong style={{ display: "block", color: "#182230" }}>{opp.name}</strong>
                      <span style={{ display: "block", color: "#475467" }}>{opp.company}</span>
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.3rem" }}>
                        <span style={{ fontWeight: 600, color: "#16324f" }}>{formatCurrency(opp.amount_minor)}</span>
                        <span style={{ color: "#0c6257" }}>{opp.probability}%</span>
                      </div>
                      {stage !== "won" && (
                        <button
                          type="button"
                          onClick={() => advanceStage(opp.id)}
                          style={{
                            marginTop: "0.4rem",
                            width: "100%",
                            padding: "0.25rem",
                            fontSize: "0.75rem",
                            background: "#e8eef5",
                            color: "#16324f",
                            border: "1px solid #ccd6e0",
                            borderRadius: "4px",
                            cursor: "pointer",
                          }}
                        >
                          {isAr ? "تقدم للمرحلة التالية →" : "Advance Stage →"}
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Quotation Governance & Approval (SoD checks) */}
      <section aria-labelledby="crm-quotations-heading" className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h2 id="crm-quotations-heading" style={{ margin: 0, fontSize: "1.2rem", color: "#16324f" }}>
            {t("crmQuotationApproval")}
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <label htmlFor="crm-approver-id" style={{ margin: 0, fontSize: "0.85rem", fontWeight: 600 }}>
              {isAr ? "معرّف المعتمد:" : "Approver User ID:"}
            </label>
            <input
              id="crm-approver-id"
              type="text"
              value={approverId}
              onChange={(e) => setApproverId(e.target.value)}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccd6e0" }}
            />
          </div>
        </div>
        <p style={{ margin: "0 0 1rem", fontSize: "0.85rem", color: "#593800", background: "#fff4cc", padding: "0.5rem", borderRadius: "4px" }}>
          {isAr
            ? "حوكمة الخصومات: الخصومات التي تتجاوز 15% تتطلب اعتماد المدير المالي مع تطبيق فصل الصلاحيات الصارم (لا يمكن لمقدم العرض اعتماده)."
            : "Discount Governance: Discounts exceeding 15.00% require managerial dual-custody approval under strict SoD invariants."}
        </p>

        <div className="reporting-table">
          <table aria-label={isAr ? "جدول عروض الأسعار" : "Quotations Table"}>
            <thead>
              <tr>
                <th>{isAr ? "رقم العرض" : "Quotation ID"}</th>
                <th>{isAr ? "مقدم العرض" : "Submitter"}</th>
                <th>{isAr ? "العميل" : "Customer"}</th>
                <th>{isAr ? "المبلغ الإجمالي" : "Total Amount"}</th>
                <th>{t("crmDiscountThreshold")}</th>
                <th>{isAr ? "الحالة" : "Status"}</th>
                <th>{isAr ? "إجراء الاعتماد" : "Governance Action"}</th>
              </tr>
            </thead>
            <tbody>
              {quotations.map((q) => {
                const discountPercent = (q.discount_bips / 100).toFixed(2);
                const isOverThreshold = q.discount_bips > 1500;

                return (
                  <tr key={q.id}>
                    <td><code>{q.id}</code></td>
                    <td>{q.submitter_user_id}</td>
                    <td>{q.customer_name}</td>
                    <td><strong>{formatCurrency(q.total_minor)}</strong></td>
                    <td>
                      <span
                        style={{
                          fontWeight: 700,
                          color: isOverThreshold ? "#7a1710" : "#02542d",
                          backgroundColor: isOverThreshold ? "#fee4e2" : "#ecfdf3",
                          padding: "0.2rem 0.4rem",
                          borderRadius: "4px",
                        }}
                      >
                        {discountPercent}% {isOverThreshold ? (isAr ? "(يتطلب موافقة)" : "(Needs Approval)") : ""}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          padding: "0.2rem 0.5rem",
                          borderRadius: "999px",
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          background: q.status === "Approved" ? "#ecfdf3" : "#fff4cc",
                          color: q.status === "Approved" ? "#02542d" : "#593800",
                        }}
                      >
                        {q.status}
                      </span>
                    </td>
                    <td>
                      {q.status === "Submitted" ? (
                        <button
                          type="button"
                          onClick={() => handleApproveQuotation(q.id, q.submitter_user_id)}
                          style={{
                            padding: "0.3rem 0.7rem",
                            background: "#0c6257",
                            color: "#ffffff",
                            border: 0,
                            borderRadius: "4px",
                            cursor: "pointer",
                            fontSize: "0.8rem",
                            fontWeight: 600,
                          }}
                        >
                          {t("hcmActionApprove")}
                        </button>
                      ) : (
                        <span style={{ fontSize: "0.8rem", color: "#667085" }}>
                          {isAr ? "معتمد بواسطة:" : "Approved by:"} {q.approver_user_id || "-"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Contract Lifecycle Management */}
      <section aria-labelledby="crm-contracts-heading" className="panel">
        <h2 id="crm-contracts-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("crmContractLifecycle")}
        </h2>
        <div className="reporting-table">
          <table aria-label={isAr ? "جدول العقود" : "Contracts Table"}>
            <thead>
              <tr>
                <th>{isAr ? "رقم العقد" : "Contract ID"}</th>
                <th>{isAr ? "العميل" : "Customer"}</th>
                <th>{isAr ? "خطة الاشتراك" : "Plan Code"}</th>
                <th>{t("crmMonthlyFee")}</th>
                <th>{isAr ? "الحالة" : "Status"}</th>
                <th>{isAr ? "تاريخ السريان" : "Period"}</th>
                <th>{isAr ? "إجراءات دورة الحياة" : "Lifecycle Actions"}</th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr key={c.id}>
                  <td><code>{c.id}</code></td>
                  <td>{c.customer_name}</td>
                  <td><code>{c.plan_code}</code></td>
                  <td><strong>{formatCurrency(c.monthly_fee_minor)}</strong></td>
                  <td>
                    <span
                      style={{
                        padding: "0.2rem 0.5rem",
                        borderRadius: "999px",
                        fontSize: "0.8rem",
                        fontWeight: 600,
                        background:
                          c.status === "Active"
                            ? "#ecfdf3"
                            : c.status === "Suspended"
                            ? "#fff4cc"
                            : "#fee4e2",
                        color:
                          c.status === "Active"
                            ? "#02542d"
                            : c.status === "Suspended"
                            ? "#593800"
                            : "#7a1710",
                      }}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td>{c.start_date} → {c.end_date}</td>
                  <td>
                    <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                      {c.status === "Active" && (
                        <button
                          type="button"
                          onClick={() => handleContractAction(c.id, "Suspend")}
                          style={{
                            padding: "0.25rem 0.5rem",
                            background: "#b54708",
                            color: "#ffffff",
                            border: 0,
                            borderRadius: "4px",
                            cursor: "pointer",
                            fontSize: "0.8rem",
                          }}
                        >
                          {t("crmActionSuspend")}
                        </button>
                      )}
                      {c.status === "Suspended" && (
                        <button
                          type="button"
                          onClick={() => handleContractAction(c.id, "Resume")}
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
                          {t("crmActionResume")}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleContractAction(c.id, "Renew")}
                        style={{
                          padding: "0.25rem 0.5rem",
                          background: "#16324f",
                          color: "#ffffff",
                          border: 0,
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "0.8rem",
                        }}
                      >
                        {t("crmActionRenew")}
                      </button>
                      {c.status !== "Terminated" && (
                        <button
                          type="button"
                          onClick={() => handleContractAction(c.id, "Terminate")}
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
                          {t("crmActionTerminate")}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Subscription Day-Proration Calculator */}
      <section aria-labelledby="crm-proration-heading" className="panel">
        <h2 id="crm-proration-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("crmProrationCalculator")}
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
          <div>
            <label htmlFor="crm-calc-fee">{t("crmMonthlyFee")}</label>
            <input
              id="crm-calc-fee"
              type="number"
              value={calcMonthlyFeeMinor}
              onChange={(e) => setCalcMonthlyFeeMinor(Number(e.target.value))}
              min={0}
              step={100}
            />
          </div>
          <div>
            <label htmlFor="crm-cycle-start">{isAr ? "بداية دورة الفوترة" : "Billing Cycle Start"}</label>
            <input
              id="crm-cycle-start"
              type="date"
              value={calcCycleStart}
              onChange={(e) => setCalcCycleStart(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="crm-cycle-end">{isAr ? "نهاية دورة الفوترة" : "Billing Cycle End"}</label>
            <input
              id="crm-cycle-end"
              type="date"
              value={calcCycleEnd}
              onChange={(e) => setCalcCycleEnd(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="crm-service-start">{isAr ? "تاريخ بدء الخدمة النسبي" : "Effective Service Start"}</label>
            <input
              id="crm-service-start"
              type="date"
              value={calcServiceStart}
              onChange={(e) => setCalcServiceStart(e.target.value)}
            />
          </div>
        </div>

        <div
          style={{
            marginTop: "1.5rem",
            padding: "1rem",
            background: "#ffffff",
            border: "1px solid #dce3ea",
            borderRadius: "8px",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "1rem",
          }}
        >
          <div>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{isAr ? "إجمالي أيام الدورة:" : "Total Cycle Days:"}</span>
            <strong style={{ display: "block", fontSize: "1.2rem", color: "#16324f" }}>{prorationResult.totalDays}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{isAr ? "الأيام النشطة المستحقة:" : "Active Billable Days:"}</span>
            <strong style={{ display: "block", fontSize: "1.2rem", color: "#16324f" }}>{prorationResult.activeDays}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{t("crmProratedAmount")}:</span>
            <strong style={{ display: "block", fontSize: "1.3rem", color: "#0c6257" }}>{formatCurrency(prorationResult.proratedMinor)}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{isAr ? "مبلغ الاسترداد / الخصم:" : "Unused / Refund Credit:"}</span>
            <strong style={{ display: "block", fontSize: "1.2rem", color: "#b54708" }}>{formatCurrency(prorationResult.refundMinor)}</strong>
          </div>
        </div>
      </section>
    </div>
  );
}

export default CrmSubscriptionWorkspace;
