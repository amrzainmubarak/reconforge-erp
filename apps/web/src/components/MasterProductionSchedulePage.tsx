import { useEffect, useState } from "react";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

interface MasterProductionSchedulePageProps {
  locale: Locale;
}

interface SourcingRequisition {
  requisition_id: string;
  item_id: string;
  bucket_index: number;
  required_date: string;
  shortage_quantity_scaled: number;
  order_quantity_scaled: number;
  preferred_supplier_id: string;
  unit_price_ceiling_minor: number;
  currency: string;
}

interface MPSScheduleRow {
  bucket_index: number;
  bucket_start_date: string;
  bucket_end_date: string;
  sales_orders_scaled: number;
  forecast_demand_scaled: number;
  net_demand_scaled: number;
  scheduled_receipts_scaled: number;
  projected_available_balance_scaled: number;
  net_requirement_scaled: number;
  planned_order_receipts_scaled: number;
  available_to_promise_scaled: number;
}

interface MPSPlan {
  id: string;
  plan_id: string;
  plan_name: string;
  revision: string;
  item_id: string;
  unit_of_measure: string;
  safety_stock_scaled: number;
  lot_size_multiple_scaled: number;
  opening_inventory_scaled: number;
  plan_digest: string;
  schedule_rows: MPSScheduleRow[];
  sourcing_requisitions: SourcingRequisition[];
}

export default function MasterProductionSchedulePage({ locale }: MasterProductionSchedulePageProps) {
  const isAr = locale === "ar";
  const [itemId, setItemId] = useState("SERVER_CHASSIS_X1");
  const [planId, setPlanId] = useState("MPS_2026_Q4");
  const [revision, setRevision] = useState("rev1");
  const [safetyStock, setSafetyStock] = useState(500);
  const [lotSize, setLotSize] = useState(1000);
  const [openingInv, setOpeningInv] = useState(250);
  const [plans, setPlans] = useState<MPSPlan[]>([]);
  const [activePlan, setActivePlan] = useState<MPSPlan | null>(null);
  const [computing, setComputing] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/manufacturing/mps/plans")
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        if (data.plans) setPlans(data.plans);
      })
      .catch(() => {
        // Fallback / initial seed for studio
        const demoPlan: MPSPlan = {
          id: "mps_MPS_2026_Q4_rev1",
          plan_id: "MPS_2026_Q4",
          plan_name: "Enterprise Server Assembly Schedule",
          revision: "rev1",
          item_id: "SERVER_CHASSIS_X1",
          unit_of_measure: "EA",
          safety_stock_scaled: 500,
          lot_size_multiple_scaled: 1000,
          opening_inventory_scaled: 250,
          plan_digest: "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592",
          schedule_rows: [
            {
              bucket_index: 0,
              bucket_start_date: "2026-11-01",
              bucket_end_date: "2026-11-07",
              sales_orders_scaled: 1200,
              forecast_demand_scaled: 1000,
              net_demand_scaled: 1200,
              scheduled_receipts_scaled: 0,
              projected_available_balance_scaled: 50,
              net_requirement_scaled: 950,
              planned_order_receipts_scaled: 1000,
              available_to_promise_scaled: 50,
            },
            {
              bucket_index: 1,
              bucket_start_date: "2026-11-08",
              bucket_end_date: "2026-11-14",
              sales_orders_scaled: 800,
              forecast_demand_scaled: 1500,
              net_demand_scaled: 1500,
              scheduled_receipts_scaled: 0,
              projected_available_balance_scaled: 550,
              net_requirement_scaled: 950,
              planned_order_receipts_scaled: 2000,
              available_to_promise_scaled: 700,
            },
          ],
          sourcing_requisitions: [
            {
              requisition_id: "PR_MPS_2026_Q4_B0",
              item_id: "SERVER_CHASSIS_X1",
              bucket_index: 0,
              required_date: "2026-11-01",
              shortage_quantity_scaled: 950,
              order_quantity_scaled: 1000,
              preferred_supplier_id: "SUP_GLOBAL_PARTS",
              unit_price_ceiling_minor: 45000,
              currency: "USD",
            },
            {
              requisition_id: "PR_MPS_2026_Q4_B1",
              item_id: "SERVER_CHASSIS_X1",
              bucket_index: 1,
              required_date: "2026-11-08",
              shortage_quantity_scaled: 950,
              order_quantity_scaled: 2000,
              preferred_supplier_id: "SUP_GLOBAL_PARTS",
              unit_price_ceiling_minor: 45000,
              currency: "USD",
            },
          ],
        };
        setPlans([demoPlan]);
        setActivePlan(demoPlan);
      });
  }, []);

  const handleCompute = async (e: React.FormEvent) => {
    e.preventDefault();
    setComputing(true);
    setStatusMessage(null);
    try {
      const payload = {
        plan_id: planId,
        plan_name: "Automated Production Schedule",
        revision: revision,
        item_id: itemId,
        unit_of_measure: "EA",
        quantity_scale: 1000,
        safety_stock_scaled: safetyStock,
        lot_size_multiple_scaled: lotSize,
        opening_inventory_scaled: openingInv,
        preferred_supplier_id: "SUP_GLOBAL_PARTS",
        unit_price_ceiling_minor: 45000,
        currency: "USD",
        buckets: [
          {
            bucket_index: 0,
            bucket_start_date: "2026-11-01",
            bucket_end_date: "2026-11-07",
            sales_orders_scaled: 1200,
            forecast_demand_scaled: 1000,
            scheduled_receipts_scaled: 0,
          },
          {
            bucket_index: 1,
            bucket_start_date: "2026-11-08",
            bucket_end_date: "2026-11-14",
            sales_orders_scaled: 800,
            forecast_demand_scaled: 1500,
            scheduled_receipts_scaled: 0,
          },
        ],
      };

      const res = await fetch("/api/v1/manufacturing/mps/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStatusMessage(isAr ? "تم حساب جدول الإنتاج الرئيسي والطلبات بنجاح" : "MPS schedule and requisitions computed successfully");
      if (data.plan) {
        setActivePlan(data.plan);
      }
    } catch {
      setStatusMessage(isAr ? "فشل حساب جدول الإنتاج" : "Failed to compute MPS schedule");
    } finally {
      setComputing(false);
    }
  };

  const plan = activePlan || plans[0];

  return (
    <div className="reporting-workspace" dir={isAr ? "rtl" : "ltr"}>
      <header className="workspace-header">
        <h1 className="workspace-title">
          {isAr ? "جدول الإنتاج الرئيسي وإدارة العجز المورّد (MPS & Sourcing)" : "Master Production Schedule & Shortage Sourcing"}
        </h1>
        <p className="workspace-subtitle">
          {isAr
            ? "تخطيط استهلاك التنبؤات، حساب الكميات المتاحة للالتزام (ATP)، وتوليد طلبات الشراء للعجز دون تكرار"
            : "Deterministic forecast consumption, Available-to-Promise (ATP) accounting, and automated shortage purchase requisition generation."}
        </p>
      </header>

      {statusMessage && (
        <div className="alert-banner" role="alert" tabIndex={0}>
          {statusMessage}
        </div>
      )}

      <div className="reporting-grid">
        <section className="reporting-card control-card" aria-labelledby="mps-params-title">
          <h2 id="mps-params-title" className="card-title">
            {isAr ? "معايير الجدولة والطلب" : "MPS Planning Parameters"}
          </h2>
          <form onSubmit={handleCompute} className="form-vertical">
            <div className="form-group">
              <label htmlFor="mps-item-id">{isAr ? "رمز المنتج" : "Item Code"}</label>
              <input
                id="mps-item-id"
                type="text"
                value={itemId}
                onChange={(e) => setItemId(e.target.value)}
                className="input-text"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="mps-plan-id">{isAr ? "معرّف الخطة" : "Plan ID"}</label>
              <input
                id="mps-plan-id"
                type="text"
                value={planId}
                onChange={(e) => setPlanId(e.target.value)}
                className="input-text"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="mps-rev">{isAr ? "الإصدار" : "Revision"}</label>
              <input
                id="mps-rev"
                type="text"
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
                className="input-text"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="mps-safety-stock">{isAr ? "مخزون الأمان" : "Safety Stock"}</label>
              <input
                id="mps-safety-stock"
                type="number"
                value={safetyStock}
                onChange={(e) => setSafetyStock(Number(e.target.value))}
                className="input-text"
                min={0}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="mps-lot-size">{isAr ? "مضاعف الدفعة" : "Lot Size Multiple"}</label>
              <input
                id="mps-lot-size"
                type="number"
                value={lotSize}
                onChange={(e) => setLotSize(Number(e.target.value))}
                className="input-text"
                min={1}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="mps-opening-inv">{isAr ? "المخزون الافتتاحي" : "Opening Inventory"}</label>
              <input
                id="mps-opening-inv"
                type="number"
                value={openingInv}
                onChange={(e) => setOpeningInv(Number(e.target.value))}
                className="input-text"
                min={0}
                required
              />
            </div>
            <button type="submit" className="button button-primary" disabled={computing}>
              {computing ? (isAr ? "جارٍ الحساب..." : "Computing...") : isAr ? "حساب جدول MPS" : "Compute MPS Schedule"}
            </button>
          </form>
        </section>

        {plan && (
          <section className="reporting-card metrics-card" aria-labelledby="mps-summary-title">
            <h2 id="mps-summary-title" className="card-title">
              {isAr ? "ملخص الخطة والطلبات الناتجة" : "MPS Plan & Procurement Summary"}
            </h2>
            <div className="metrics-summary">
              <div className="metric-box">
                <span className="metric-label">{isAr ? "الفترات المخططة" : "Schedule Buckets"}</span>
                <span className="metric-value">{plan.schedule_rows?.length ?? 0}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "طلبات الشراء للعجز" : "Shortage Requisitions"}</span>
                <span className="metric-value">{plan.sourcing_requisitions?.length ?? 0}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "مخزون الأمان المستهدف" : "Target Safety Stock"}</span>
                <span className="metric-value">{plan.safety_stock_scaled}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "حجم دفعة الإنتاج" : "Lot Size"}</span>
                <span className="metric-value">{plan.lot_size_multiple_scaled}</span>
              </div>
            </div>

            <div className="digest-box">
              <span className="digest-label">{isAr ? "بصمة خطة MPS المشفرة:" : "MPS Cryptographic Digest:"}</span>
              <code className="digest-code">{plan.plan_digest}</code>
            </div>
          </section>
        )}
      </div>

      {plan && plan.schedule_rows && plan.schedule_rows.length > 0 && (
        <section className="reporting-card table-card" aria-labelledby="mps-grid-title">
          <h2 id="mps-grid-title" className="card-title">
            {isAr ? "جدول الفترات الزمنية للإنتاج والتسليم" : "MPS Time-Phased Planning Grid"}
          </h2>
          <div className="table-responsive">
            <table className="table" aria-label={isAr ? "جدول خطة الإنتاج الرئيسية" : "Master production schedule grid"}>
              <thead>
                <tr>
                  <th>{isAr ? "الفترة" : "Bucket"}</th>
                  <th>{isAr ? "تاريخ البداية" : "Start Date"}</th>
                  <th>{isAr ? "تاريخ النهاية" : "End Date"}</th>
                  <th>{isAr ? "أوامر البيع" : "Sales Orders"}</th>
                  <th>{isAr ? "التنبؤ" : "Forecast"}</th>
                  <th>{isAr ? "صافي الاحتياج" : "Net Demand"}</th>
                  <th>{isAr ? "الإيصالات المجدولة" : "Receipts"}</th>
                  <th>{isAr ? "الرصيد المتاح المتوقع (PAB)" : "PAB"}</th>
                  <th>{isAr ? "المتاح للالتزام (ATP)" : "ATP"}</th>
                </tr>
              </thead>
              <tbody>
                {plan.schedule_rows.map((row) => (
                  <tr key={row.bucket_index}>
                    <td>#{row.bucket_index}</td>
                    <td>{row.bucket_start_date}</td>
                    <td>{row.bucket_end_date}</td>
                    <td>{row.sales_orders_scaled}</td>
                    <td>{row.forecast_demand_scaled}</td>
                    <td><strong>{row.net_demand_scaled}</strong></td>
                    <td>{row.scheduled_receipts_scaled}</td>
                    <td>{row.projected_available_balance_scaled}</td>
                    <td><span className="badge badge-success">{row.available_to_promise_scaled}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {plan && plan.sourcing_requisitions && plan.sourcing_requisitions.length > 0 && (
        <section className="reporting-card table-card" aria-labelledby="mps-requisitions-title">
          <h2 id="mps-requisitions-title" className="card-title">
            {isAr ? "طلبات الشراء المنشأة آلياً للعجز (Shortage Purchase Requisitions)" : "Automated Shortage Purchase Requisitions"}
          </h2>
          <div className="table-responsive">
            <table className="table" aria-label={isAr ? "جدول طلبات الشراء للعجز" : "Shortage purchase requisitions table"}>
              <thead>
                <tr>
                  <th>{isAr ? "رقم الطلب" : "Requisition ID"}</th>
                  <th>{isAr ? "تاريخ الاستحقاق" : "Required Date"}</th>
                  <th>{isAr ? "كمية العجز" : "Shortage Qty"}</th>
                  <th>{isAr ? "كمية الأمر" : "Order Qty"}</th>
                  <th>{isAr ? "المورّد المفضل" : "Preferred Supplier"}</th>
                  <th>{isAr ? "سقف السعر" : "Price Ceiling"}</th>
                  <th>{isAr ? "الحالة" : "Status"}</th>
                </tr>
              </thead>
              <tbody>
                {plan.sourcing_requisitions.map((req) => (
                  <tr key={req.requisition_id}>
                    <td><code>{req.requisition_id}</code></td>
                    <td>{req.required_date}</td>
                    <td>{req.shortage_quantity_scaled}</td>
                    <td><strong>{req.order_quantity_scaled}</strong></td>
                    <td>{req.preferred_supplier_id}</td>
                    <td>${(req.unit_price_ceiling_minor / 100).toFixed(2)}</td>
                    <td><span className="badge badge-primary">{isAr ? "معتمد" : "APPROVED"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
