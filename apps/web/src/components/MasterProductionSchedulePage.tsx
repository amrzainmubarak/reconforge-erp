import { useEffect, useState } from "react";
import { useBrowserSession } from "../browserSession";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

interface ScheduleRow {
  bucket_index: number; bucket_start_date: string; bucket_end_date: string;
  sales_orders_scaled: number; forecast_demand_scaled: number; net_demand_scaled: number;
  scheduled_receipts_scaled: number; planned_production_scaled: number; projected_inventory_scaled: number;
  available_to_promise_scaled: number; shortage_scaled: number;
}
interface Requisition {
  requisition_id: string; item_id: string; bucket_index: number; required_date: string;
  shortage_quantity_scaled: number; order_quantity_scaled: number; preferred_supplier_id: string;
  unit_price_ceiling_minor: number; currency: string;
}
interface Plan {
  id: string; plan_id: string; revision: string; item_id: string; unit_of_measure: string;
  quantity_scale: number; safety_stock_scaled: number; lot_size_multiple_scaled: number;
  plan_digest: string; schedule_rows: ScheduleRow[]; sourcing_requisitions: Requisition[];
}
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= 500;
const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value);
function parsePlans(value: unknown): Plan[] {
  if (!object(value) || !Array.isArray(value.plans) || value.plans.length > 1000 || value.total_count !== value.plans.length) throw new Error("mps_plans_invalid");
  const ids = new Set<string>();
  return value.plans.map(record => {
    if (!object(record) || !text(record.id) || ids.has(record.id) || !object(record.plan)) throw new Error("mps_record_invalid");
    const plan = record.plan;
    if (!["plan_id", "revision", "item_id", "unit_of_measure"].every(key => text(plan[key]) && plan[key] === record[key])
      || !integer(plan.quantity_scale) || plan.quantity_scale <= 0 || !integer(plan.safety_stock_scaled) || plan.safety_stock_scaled < 0
      || !integer(plan.lot_size_multiple_scaled) || plan.lot_size_multiple_scaled <= 0 || !integer(plan.opening_inventory_scaled)
      || typeof plan.plan_digest !== "string" || !/^[a-f0-9]{64}$/.test(plan.plan_digest) || plan.plan_digest !== record.plan_digest
      || !Array.isArray(plan.schedule_rows) || plan.schedule_rows.length > 1000 || !Array.isArray(plan.sourcing_requisitions) || plan.sourcing_requisitions.length > 1000) throw new Error("mps_plan_invalid");
    const buckets = new Set<number>(), requisitions = new Set<string>();
    for (const row of plan.schedule_rows) {
      if (!object(row) || !integer(row.bucket_index) || row.bucket_index < 0 || buckets.has(row.bucket_index)
        || !text(row.bucket_start_date) || !text(row.bucket_end_date)
        || !["sales_orders_scaled", "forecast_demand_scaled", "net_demand_scaled", "scheduled_receipts_scaled", "planned_production_scaled", "projected_inventory_scaled", "available_to_promise_scaled", "shortage_scaled"].every(key => integer(row[key]))) throw new Error("mps_row_invalid");
      buckets.add(row.bucket_index);
    }
    for (const req of plan.sourcing_requisitions) {
      if (!object(req) || !text(req.requisition_id) || requisitions.has(req.requisition_id) || req.plan_id !== plan.plan_id || req.plan_revision !== plan.revision || req.item_id !== plan.item_id
        || !integer(req.bucket_index) || !buckets.has(req.bucket_index) || !text(req.required_date) || !text(req.preferred_supplier_id)
        || !integer(req.shortage_quantity_scaled) || req.shortage_quantity_scaled < 0 || !integer(req.order_quantity_scaled) || req.order_quantity_scaled < 0
        || !integer(req.unit_price_ceiling_minor) || req.unit_price_ceiling_minor < 0 || typeof req.currency !== "string" || !/^[A-Z]{3}$/.test(req.currency)) throw new Error("mps_requisition_invalid");
      requisitions.add(req.requisition_id);
    }
    ids.add(record.id); return { ...plan, id: record.id } as unknown as Plan;
  });
}
export default function MasterProductionSchedulePage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <MPSSession key={auth.revision} locale={locale} />;
}
function MPSSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), isAr = locale === "ar";
  const [plans, setPlans] = useState<Plan[]>([]), [selected, setSelected] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState(false), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setPlans([]); setSelected(null); setError(false);
    if (!auth.session) return;
    setLoading(true); const revision = auth.revision;
    fetch("/api/v1/manufacturing/mps/plans", { credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json", "X-ReconForge-Tenant": auth.session.tenantId } })
      .then(response => { if (!response.ok) throw new Error("mps_read_failed"); return response.json(); })
      .then(value => { const result = parsePlans(value); if (!controller.signal.aborted && auth.isCurrent(revision)) setPlans(result); })
      .catch(() => { if (!controller.signal.aborted && auth.isCurrent(revision)) { setPlans([]); setSelected(null); setError(true); } })
      .finally(() => { if (!controller.signal.aborted && auth.isCurrent(revision)) setLoading(false); });
    return () => controller.abort();
  }, [auth.revision, locale, refresh]);
  const plan = selected ?? plans[0];
  return <div className="reporting-workspace" dir={isAr ? "rtl" : "ltr"}>
    <header className="workspace-header"><h1>{isAr ? "جدول الإنتاج الرئيسي وإدارة العجز المورّد (MPS & Sourcing)" : "Master Production Schedule & Shortage Sourcing"}</h1><p>{isAr ? "قراءة خطط الإنتاج المحفوظة من الخادم. لا تُنشأ طلبات شراء من بيانات تجريبية." : "Read stored production plans from the server. Sample data does not create procurement requisitions."}</p></header>
    {!auth.session && <p role="status">{isAr ? "سجّل الدخول إلى مساحة عمل مخوّلة لقراءة الخطط المحفوظة." : "Sign in to an authorized workspace to read stored plans."}</p>}
    {loading && <p role="status">{isAr ? "جارٍ تحميل الخطط..." : "Loading production plans..."}</p>}
    {error && <div role="alert">{isAr ? "تعذر تحميل خطط صالحة. تحقق من الجلسة والصلاحيات والاتصال ثم أعد المحاولة. لا تتوفر خطة أو طلبات شراء موثقة." : "Valid production plans could not be loaded. Check the session, permissions and connection, then retry. No verified plan or requisitions are available."}</div>}
    <section className="reporting-card" aria-labelledby="mps-params-title"><h2 id="mps-params-title">{isAr ? "معايير الجدولة والطلب" : "MPS Planning Parameters"}</h2>
      <p id="mps-source-required">{isAr ? "حساب الجدول معطّل حتى يتوفر اختيار طلب ومخزون ومورّد وسياسة عملة حقيقية." : "Computation is unavailable until real demand, inventory, supplier and currency inputs can be selected."}</p>
      <button type="button" disabled aria-describedby="mps-source-required">{isAr ? "حساب جدول MPS" : "Compute MPS Schedule"}</button>
    </section>
    <section className="reporting-card" aria-labelledby="mps-history-title"><h2 id="mps-history-title">{isAr ? "الخطط المحفوظة" : "Stored Production Plans"}</h2>
      <button type="button" disabled={!auth.session || loading} onClick={() => { setPlans([]); setSelected(null); setRefresh(value => value + 1); }}>{isAr ? "تحديث" : "Refresh"}</button>
      {auth.session && !loading && !error && plans.length === 0 && <p role="status">{isAr ? "لا توجد خطط إنتاج محفوظة." : "No stored production plans were returned."}</p>}
      {plans.map(item => <p key={item.id}><code>{item.plan_id} / {item.revision}</code> <button onClick={() => setSelected(item)}>{isAr ? "عرض" : "Inspect"}</button></p>)}
    </section>
    {plan && <>
      <section className="reporting-card" aria-labelledby="mps-summary-title"><h2 id="mps-summary-title">{isAr ? "ملخص الخطة والطلبات الناتجة" : "MPS Plan & Procurement Summary"}</h2>
        <p>{isAr ? "مقياس الكميات:" : "Quantity scale:"} {plan.quantity_scale} {plan.unit_of_measure}</p><p>{isAr ? "بصمة الخطة المحفوظة:" : "Stored plan digest:"} <code>{plan.plan_digest}</code></p>
      </section>
      <section className="reporting-card" aria-labelledby="mps-grid-title"><h2 id="mps-grid-title">{isAr ? "جدول الفترات الزمنية للإنتاج والتسليم" : "MPS Time-Phased Planning Grid"}</h2>
        <div className="table-responsive"><table aria-label={isAr ? "جدول خطة الإنتاج الرئيسية" : "Master production schedule grid"}><thead><tr>
          <th>{isAr ? "الفترة" : "Bucket"}</th><th>{isAr ? "تاريخ البداية" : "Start Date"}</th><th>{isAr ? "تاريخ النهاية" : "End Date"}</th><th>{isAr ? "أوامر البيع" : "Sales Orders"}</th><th>{isAr ? "التنبؤ" : "Forecast"}</th><th>{isAr ? "صافي الطلب" : "Net Demand"}</th><th>{isAr ? "الإيصالات" : "Receipts"}</th><th>{isAr ? "المخزون المتوقع" : "Projected Inventory"}</th><th>ATP</th>
        </tr></thead><tbody>{plan.schedule_rows.map(row => <tr key={row.bucket_index}><td>#{row.bucket_index}</td><td>{row.bucket_start_date}</td><td>{row.bucket_end_date}</td><td>{row.sales_orders_scaled}</td><td>{row.forecast_demand_scaled}</td><td>{row.net_demand_scaled}</td><td>{row.scheduled_receipts_scaled}</td><td>{row.projected_inventory_scaled}</td><td>{row.available_to_promise_scaled}</td></tr>)}</tbody></table></div>
      </section>
      <section className="reporting-card" aria-labelledby="mps-requisitions-title"><h2 id="mps-requisitions-title">{isAr ? "مقترحات شراء العجز المحفوظة" : "Stored Shortage Requisition Suggestions"}</h2>
        <p>{isAr ? "الاقتراح المخزّن ليس دليلاً على اعتماد الشراء. يُراجع في مسار المشتريات المخوّل." : "A stored suggestion does not establish procurement approval. Review it through the authorized procurement workflow."}</p>
        <div className="table-responsive"><table aria-label={isAr ? "جدول طلبات الشراء للعجز" : "Shortage purchase requisitions table"}><thead><tr><th>{isAr ? "رقم الطلب" : "Requisition ID"}</th><th>{isAr ? "تاريخ الاستحقاق" : "Required Date"}</th><th>{isAr ? "كمية العجز" : "Shortage Qty"}</th><th>{isAr ? "كمية الأمر" : "Order Qty"}</th><th>{isAr ? "المورّد" : "Supplier"}</th><th>{isAr ? "سقف السعر بوحدات صغرى" : "Price Ceiling in Minor Units"}</th></tr></thead><tbody>
          {plan.sourcing_requisitions.map(req => <tr key={req.requisition_id}><td><code>{req.requisition_id}</code></td><td>{req.required_date}</td><td>{req.shortage_quantity_scaled}</td><td>{req.order_quantity_scaled}</td><td>{req.preferred_supplier_id}</td><td>{req.unit_price_ceiling_minor} {req.currency}</td></tr>)}
        </tbody></table></div>
      </section>
    </>}
  </div>;
}
