import { Fragment, useState } from "react";
import type { Locale } from "../types";
import { translate } from "../i18n";
import "./FinancialReportingPage.css";

export interface ProjectMilestoneWorkspaceProps {
  locale: Locale;
}

export interface WbsTask {
  id: string;
  code: string; // e.g. "1.1", "1.2"
  title: string;
  status: "NotStarted" | "InProgress" | "Completed";
  progress_pct: number;
  budget_minor: number;
  actual_cost_minor: number;
  children?: WbsTask[];
}

export interface RoleRateCard {
  role_code: string;
  role_name: string;
  currency: string;
  standard_rate_minor: number;
  overtime_rate_minor: number;
  effective_date: string;
}

export interface ProjectMilestone {
  id: string;
  name: string;
  target_date: string;
  amount_minor: number;
  weight_pct: number;
  deliverables: string;
  status: "Pending" | "Verified" | "Billed";
  verified_by?: string;
  invoice_ref?: string;
}

export function ProjectMilestoneWorkspace({ locale }: ProjectMilestoneWorkspaceProps) {
  const isAr = locale === "ar";
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  // Financial posture values (minor units)
  const totalContractValueMinor = 50000000; // 500,000.00
  const [billedToDateMinor, setBilledToDateMinor] = useState(30000000); // 300,000.00
  const unrecognizedRevenueMinor = totalContractValueMinor - billedToDateMinor;
  const remainingBudgetMinor = 14500000; // 145,000.00

  // WBS Tasks State
  const [tasks] = useState<WbsTask[]>([
    {
      id: "TSK-01",
      code: "1.0",
      title: isAr ? "التصميم المعماري وتحديد المتطلبات" : "Architecture & Requirements Blueprint",
      status: "Completed",
      progress_pct: 100,
      budget_minor: 10000000,
      actual_cost_minor: 9500000,
      children: [
        {
          id: "TSK-01-1",
          code: "1.1",
          title: isAr ? "نمذجة قواعد البيانات المالية" : "Financial Database Schema Modeling",
          status: "Completed",
          progress_pct: 100,
          budget_minor: 5000000,
          actual_cost_minor: 4800000,
        },
        {
          id: "TSK-01-2",
          code: "1.2",
          title: isAr ? "تصميم واجهات برمجة التطبيقات والمطابقة" : "Matching Engine & API Design",
          status: "Completed",
          progress_pct: 100,
          budget_minor: 5000000,
          actual_cost_minor: 4700000,
        },
      ],
    },
    {
      id: "TSK-02",
      code: "2.0",
      title: isAr ? "بناء واختبار محرك المطابقة ونماذج الحوكمة" : "Core Engine Implementation & Governance",
      status: "InProgress",
      progress_pct: 75,
      budget_minor: 25000000,
      actual_cost_minor: 18000000,
      children: [
        {
          id: "TSK-02-1",
          code: "2.1",
          title: isAr ? "تنفيذ استراتيجيات المطابقة المتقدمة" : "Advanced Group Matching Strategies",
          status: "InProgress",
          progress_pct: 85,
          budget_minor: 15000000,
          actual_cost_minor: 11000000,
        },
        {
          id: "TSK-02-2",
          code: "2.2",
          title: isAr ? "حوكمة الذكاء الاصطناعي والصانع-المعتمد" : "Governed AI & Maker-Checker Workflows",
          status: "InProgress",
          progress_pct: 65,
          budget_minor: 10000000,
          actual_cost_minor: 7000000,
        },
      ],
    },
    {
      id: "TSK-03",
      code: "3.0",
      title: isAr ? "التدقيق الأمني واختبارات الأداء الجاهزة للإنتاج" : "Security Audit & Production Hardening",
      status: "NotStarted",
      progress_pct: 0,
      budget_minor: 15000000,
      actual_cost_minor: 0,
    },
  ]);

  // Rate Cards State
  const [rateCards] = useState<RoleRateCard[]>([
    {
      role_code: "PRIN_ARCH",
      role_name: isAr ? "كبير مهندسي النظم المالية" : "Principal Financial Systems Architect",
      currency: "USD",
      standard_rate_minor: 25000, // $250.00 / hr
      overtime_rate_minor: 37500, // $375.00 / hr
      effective_date: "2026-01-01",
    },
    {
      role_code: "SR_DEV",
      role_name: isAr ? "مطور برمجيات خبير" : "Senior Distributed Systems Engineer",
      currency: "USD",
      standard_rate_minor: 18000, // $180.00 / hr
      overtime_rate_minor: 27000, // $270.00 / hr
      effective_date: "2026-01-01",
    },
    {
      role_code: "SEC_AUDIT",
      role_name: isAr ? "مراجع أمني واختبار اختراق" : "Security & Cryptographic Auditor",
      currency: "USD",
      standard_rate_minor: 22000, // $220.00 / hr
      overtime_rate_minor: 33000, // $330.00 / hr
      effective_date: "2026-01-01",
    },
  ]);

  // Milestones State
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([
    {
      id: "MLS-01",
      name: isAr ? "المرحلة الأولى: التسليم المعماري ونموذج البيانات" : "Milestone 1: Blueprint & Canonical Schema",
      target_date: "2026-03-31",
      amount_minor: 10000000,
      weight_pct: 20,
      deliverables: isAr ? "مخطط البنية ووثيقة التصميم الفني المعتمدة" : "Architecture Blueprint & Approved Tech Spec",
      status: "Billed",
      verified_by: "TECH_LEAD_01",
      invoice_ref: "INV-2026-042",
    },
    {
      id: "MLS-02",
      name: isAr ? "المرحلة الثانية: محرك المطابقة والحوكمة الثنائية" : "Milestone 2: Matching Engine & Dual Custody",
      target_date: "2026-07-31",
      amount_minor: 20000000,
      weight_pct: 40,
      deliverables: isAr ? "محرك المطابقة التوافقي وفصل الصلاحيات المجاز" : "Reconciliation Engine & SoD Invariants",
      status: "Billed",
      verified_by: "QA_DIRECTOR_01",
      invoice_ref: "INV-2026-098",
    },
    {
      id: "MLS-03",
      name: isAr ? "المرحلة الثالثة: مساعد الذكاء الاصطناعي وبوابة الإدارة" : "Milestone 3: Governed AI & Studio Workspaces",
      target_date: "2026-10-31",
      amount_minor: 10000000,
      weight_pct: 20,
      deliverables: isAr ? "رسم بياني للأدلة ونوافذ React الثنائية كاملة التوافق" : "Evidence Graph & Accessible React Workspaces",
      status: "Verified",
      verified_by: "PROJECT_MANAGER_02",
    },
    {
      id: "MLS-04",
      name: isAr ? "المرحلة الرابعة: الإطلاق النهائي وضمان الجودة الشامل" : "Milestone 4: Final Production Cutover & Warranty",
      target_date: "2026-12-31",
      amount_minor: 10000000,
      weight_pct: 20,
      deliverables: isAr ? "باقة النشر المؤسسي والتوثيق والاعتماد النهائي" : "Production Packages, Audit Signoff & Runbooks",
      status: "Pending",
    },
  ]);

  const [feedback, setFeedback] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const formatCurrency = (minor: number) => {
    return (minor / 100).toLocaleString(isAr ? "ar-EG" : "en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const handleVerifyMilestone = (milestoneId: string) => {
    setMilestones(
      milestones.map((m) =>
        m.id === milestoneId
          ? { ...m, status: "Verified", verified_by: "INDEPENDENT_AUDITOR" }
          : m
      )
    );
    setFeedback({
      message: isAr
        ? `تم التحقق من اكتمال مخرجات المرحلة ${milestoneId} بنجاح وتسجيل التدقيق المستقل`
        : `Deliverables verified for ${milestoneId}; independent audit evidence recorded`,
      type: "success",
    });
  };

  const handleBillMilestone = (milestoneId: string) => {
    const target = milestones.find((m) => m.id === milestoneId);
    if (!target) return;
    const invRef = `INV-2026-${String(Math.floor(Math.random() * 900) + 100)}`;
    setMilestones(
      milestones.map((m) =>
        m.id === milestoneId ? { ...m, status: "Billed", invoice_ref: invRef } : m
      )
    );
    setBilledToDateMinor((prev) => prev + target.amount_minor);
    setFeedback({
      message: isAr
        ? `تم إصدار فاتورة المرحلة ${milestoneId} بمبلغ ${formatCurrency(target.amount_minor)} (رقم الفاتورة: ${invRef})`
        : `Billing invoice generated for ${milestoneId} for ${formatCurrency(target.amount_minor)} (Invoice Ref: ${invRef})`,
      type: "success",
    });
  };

  return (
    <div className="financial-reporting" dir={isAr ? "rtl" : "ltr"}>
      <header className="panel" style={{ background: "#16324f", color: "#ffffff" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>{t("projectMilestoneTitle")}</h1>
        <p style={{ margin: "0.5rem 0 0", opacity: 0.9 }}>{t("projectMilestoneSubtitle")}</p>
      </header>

      {feedback && (
        <div
          role="status"
          aria-live="polite"
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

      {/* Real-Time Financial Posture Card */}
      <section aria-labelledby="project-posture-heading" className="panel">
        <h2 id="project-posture-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("projectFinancialPosture")}
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
            gap: "1rem",
          }}
        >
          <article style={{ background: "#ffffff", border: "1px solid #dce3ea", borderRadius: "8px", padding: "1rem" }}>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{t("projectContractValue")}</span>
            <strong style={{ display: "block", fontSize: "1.4rem", color: "#16324f", marginTop: "0.4rem" }}>
              ${formatCurrency(totalContractValueMinor)}
            </strong>
          </article>
          <article style={{ background: "#ffffff", border: "1px solid #dce3ea", borderRadius: "8px", padding: "1rem" }}>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{t("projectBilledAmount")}</span>
            <strong style={{ display: "block", fontSize: "1.4rem", color: "#0c6257", marginTop: "0.4rem" }}>
              ${formatCurrency(billedToDateMinor)}
            </strong>
          </article>
          <article style={{ background: "#ffffff", border: "1px solid #dce3ea", borderRadius: "8px", padding: "1rem" }}>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{t("projectUnrecognizedRevenue")}</span>
            <strong style={{ display: "block", fontSize: "1.4rem", color: "#b54708", marginTop: "0.4rem" }}>
              ${formatCurrency(unrecognizedRevenueMinor)}
            </strong>
          </article>
          <article style={{ background: "#ffffff", border: "1px solid #dce3ea", borderRadius: "8px", padding: "1rem" }}>
            <span style={{ fontSize: "0.85rem", color: "#667085" }}>{t("projectRemainingBudget")}</span>
            <strong style={{ display: "block", fontSize: "1.4rem", color: "#475467", marginTop: "0.4rem" }}>
              ${formatCurrency(remainingBudgetMinor)}
            </strong>
          </article>
        </div>
      </section>

      {/* Milestone Verification & Billing */}
      <section aria-labelledby="project-milestones-heading" className="panel">
        <h2 id="project-milestones-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("projectMilestoneVerification")}
        </h2>
        <div className="reporting-table">
          <table aria-label={isAr ? "جدول مراحل المشروع والفوترة" : "Project Milestones Table"}>
            <thead>
              <tr>
                <th>{isAr ? "معرّف المرحلة" : "Milestone ID"}</th>
                <th>{isAr ? "اسم المرحلة" : "Milestone Name"}</th>
                <th>{isAr ? "التاريخ المستهدف" : "Target Date"}</th>
                <th>{isAr ? "الوزن النسبي" : "Weight"}</th>
                <th>{isAr ? "المبلغ المستحق" : "Amount"}</th>
                <th>{isAr ? "المخرجات المعتمدة" : "Deliverables"}</th>
                <th>{isAr ? "الحالة" : "Status"}</th>
                <th>{isAr ? "إجراءات التحقق والفوترة" : "Verification & Invoicing"}</th>
              </tr>
            </thead>
            <tbody>
              {milestones.map((m) => {
                const badgeStyle = {
                  padding: "0.2rem 0.5rem",
                  borderRadius: "999px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  backgroundColor:
                    m.status === "Billed"
                      ? "#ecfdf3"
                      : m.status === "Verified"
                      ? "#e0f2fe"
                      : "#fff4cc",
                  color:
                    m.status === "Billed"
                      ? "#02542d"
                      : m.status === "Verified"
                      ? "#0369a1"
                      : "#593800",
                };

                return (
                  <tr key={m.id}>
                    <td><code>{m.id}</code></td>
                    <td><strong>{m.name}</strong></td>
                    <td>{m.target_date}</td>
                    <td>{m.weight_pct}%</td>
                    <td><strong>${formatCurrency(m.amount_minor)}</strong></td>
                    <td style={{ fontSize: "0.85rem", color: "#475467" }}>{m.deliverables}</td>
                    <td>
                      <span style={badgeStyle}>
                        {m.status === "Billed"
                          ? isAr ? "مفوتر" : "Billed"
                          : m.status === "Verified"
                          ? isAr ? "تم التحقق" : "Verified"
                          : isAr ? "قيد الانتظار" : "Pending"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", alignItems: "center" }}>
                        {m.status === "Pending" && (
                          <button
                            type="button"
                            onClick={() => handleVerifyMilestone(m.id)}
                            style={{
                              padding: "0.25rem 0.6rem",
                              background: "#0369a1",
                              color: "#ffffff",
                              border: 0,
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontSize: "0.8rem",
                              fontWeight: 600,
                            }}
                          >
                            {isAr ? "اعتماد التحقق ✓" : "Verify Deliverable ✓"}
                          </button>
                        )}
                        {m.status === "Verified" && (
                          <button
                            type="button"
                            onClick={() => handleBillMilestone(m.id)}
                            style={{
                              padding: "0.25rem 0.6rem",
                              background: "#0c6257",
                              color: "#ffffff",
                              border: 0,
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontSize: "0.8rem",
                              fontWeight: 600,
                            }}
                          >
                            {isAr ? "إصدار الفاتورة 📄" : "Generate Invoice 📄"}
                          </button>
                        )}
                        {m.status === "Billed" && (
                          <span style={{ fontSize: "0.8rem", color: "#02542d" }}>
                            <code>{m.invoice_ref}</code>
                          </span>
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

      {/* WBS Task Tree */}
      <section aria-labelledby="project-wbs-heading" className="panel">
        <h2 id="project-wbs-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("projectWbsTree")}
        </h2>
        <div className="reporting-table">
          <table aria-label={isAr ? "جدول هيكل تجزئة العمل" : "WBS Tasks Table"}>
            <thead>
              <tr>
                <th>{isAr ? "رمز WBS" : "WBS Code"}</th>
                <th>{isAr ? "عنوان المهمة / حزمة العمل" : "Task / Work Package Title"}</th>
                <th>{isAr ? "نسبة الإنجاز" : "Progress"}</th>
                <th>{isAr ? "الميزانية المخصصة" : "Budget"}</th>
                <th>{isAr ? "التكلفة الفعلية" : "Actual Cost"}</th>
                <th>{isAr ? "الحالة" : "Status"}</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <Fragment key={task.id}>
                  <tr key={task.id} style={{ background: "#f8faf9", fontWeight: 600 }}>
                    <td><code>{task.code}</code></td>
                    <td>{task.title}</td>
                    <td>{task.progress_pct}%</td>
                    <td>${formatCurrency(task.budget_minor)}</td>
                    <td>${formatCurrency(task.actual_cost_minor)}</td>
                    <td>
                      <span style={{ fontSize: "0.8rem", color: task.status === "Completed" ? "#02542d" : "#0369a1" }}>
                        {task.status}
                      </span>
                    </td>
                  </tr>
                  {task.children?.map((child) => (
                    <tr key={child.id}>
                      <td style={{ paddingInlineStart: "2rem" }}><code>{child.code}</code></td>
                      <td style={{ paddingInlineStart: "2rem" }}>{child.title}</td>
                      <td>{child.progress_pct}%</td>
                      <td>${formatCurrency(child.budget_minor)}</td>
                      <td>${formatCurrency(child.actual_cost_minor)}</td>
                      <td>
                        <span style={{ fontSize: "0.8rem", color: child.status === "Completed" ? "#02542d" : "#0369a1" }}>
                          {child.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Role Rate Cards */}
      <section aria-labelledby="project-rates-heading" className="panel">
        <h2 id="project-rates-heading" style={{ margin: "0 0 1rem", fontSize: "1.2rem", color: "#16324f" }}>
          {t("projectRateCards")}
        </h2>
        <div className="reporting-table">
          <table aria-label={isAr ? "جدول بطاقات أسعار الأدوار" : "Rate Cards Table"}>
            <thead>
              <tr>
                <th>{isAr ? "رمز الدور" : "Role Code"}</th>
                <th>{isAr ? "المسمى الوظيفي" : "Role Name"}</th>
                <th>{isAr ? "السعر الاعتيادي / ساعة" : "Standard Rate / Hr"}</th>
                <th>{isAr ? "سعر العمل الإضافي / ساعة" : "Overtime Rate / Hr"}</th>
                <th>{isAr ? "تاريخ السريان" : "Effective Date"}</th>
              </tr>
            </thead>
            <tbody>
              {rateCards.map((rc) => (
                <tr key={rc.role_code}>
                  <td><code>{rc.role_code}</code></td>
                  <td><strong>{rc.role_name}</strong></td>
                  <td>${formatCurrency(rc.standard_rate_minor)}</td>
                  <td>${formatCurrency(rc.overtime_rate_minor)}</td>
                  <td>{rc.effective_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default ProjectMilestoneWorkspace;
