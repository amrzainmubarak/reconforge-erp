import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

interface GenealogyNode { lot_id: string; item_id: string; direction: "forward" | "backward"; children: GenealogyNode[] }
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= 128;
function parseTree(value: unknown, lot: string, direction: "forward" | "backward"): GenealogyNode {
  if (!object(value) || value.root_lot_id !== lot) throw new Error("genealogy_root_invalid");
  let count = 0;
  function parse(node: unknown, depth: number, ancestors: Set<string>): GenealogyNode {
    if (++count > 1000 || depth > 12 || !object(node) || !text(node.lot_id) || ancestors.has(node.lot_id) || !text(node.item_id)
      || node.direction !== direction || !Array.isArray(node.children) || node.children.length > 1000) throw new Error("genealogy_node_invalid");
    const branch = new Set(ancestors); branch.add(node.lot_id);
    return { lot_id: node.lot_id, item_id: node.item_id, direction, children: node.children.map(child => parse(child, depth + 1, branch)) };
  }
  const result = parse(value.genealogy, 0, new Set());
  if (result.lot_id !== lot) throw new Error("genealogy_binding_invalid");
  return result;
}
export default function ShopFloorTraceabilityPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <TraceSession key={auth.revision} locale={locale} />;
}
function TraceSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), isAr = locale === "ar";
  const [lot, setLot] = useState(""), [direction, setDirection] = useState<"forward" | "backward">("backward");
  const [tree, setTree] = useState<GenealogyNode | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState(false);
  const active = useRef<AbortController | null>(null), revision = useRef(0);
  function invalidate() { active.current?.abort(); revision.current++; setTree(null); setError(false); setLoading(false); }
  useEffect(() => { invalidate(); return () => { active.current?.abort(); revision.current++; }; }, [locale]);
  async function trace(event: FormEvent) {
    event.preventDefault(); if (!auth.session || !lot.trim()) return;
    invalidate(); const requestRevision = ++revision.current, sessionRevision = auth.revision;
    const controller = new AbortController(); active.current = controller; setLoading(true);
    const requestedLot = lot.trim(), requestedDirection = direction;
    try {
      const response = await fetch(`/api/v1/manufacturing/traceability/genealogy/${requestedDirection}/${encodeURIComponent(requestedLot)}`, {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: { Accept: "application/json", "X-ReconForge-Tenant": auth.session.tenantId },
      });
      if (!response.ok) throw new Error("genealogy_read_failed");
      const result = parseTree(await response.json(), requestedLot, requestedDirection);
      if (!controller.signal.aborted && revision.current === requestRevision && auth.isCurrent(sessionRevision)) setTree(result);
    } catch {
      if (!controller.signal.aborted && revision.current === requestRevision && auth.isCurrent(sessionRevision)) { setTree(null); setError(true); }
    } finally {
      if (!controller.signal.aborted && revision.current === requestRevision && auth.isCurrent(sessionRevision)) setLoading(false);
    }
  }
  const renderNode = (node: GenealogyNode, key = node.lot_id) => <li key={key}><div className="tree-node-content"><span>{node.item_id}</span> <code>{node.lot_id}</code></div>
    {node.children.length > 0 && <ul>{node.children.map((child, index) => renderNode(child, `${child.lot_id}-${index}`))}</ul>}
  </li>;
  return <div className="reporting-workspace" dir={isAr ? "rtl" : "ltr"}>
    <header className="workspace-header"><h1>{isAr ? "تنفيذ صالة الإنتاج والتتبع الجيني للتشغيل والدفعات" : "Shop Floor Execution & Bidirectional Lot Genealogy"}</h1>
      <p>{isAr ? "قراءة شجرة دفعة محفوظة من الخادم. لا تُعرض خطوات تشغيل أو دفعات تجريبية على أنها عمليات مكتملة." : "Read stored lot genealogy from the server. Sample lots and routing steps are not presented as completed operations."}</p></header>
    {!auth.session && <p role="status">{isAr ? "سجّل الدخول إلى مساحة عمل مخوّلة لقراءة تتبع الدفعات." : "Sign in to an authorized workspace to read lot genealogy."}</p>}
    {error && <div role="alert">{isAr ? "تعذر استرجاع شجرة صالحة. تحقق من معرّف الدفعة والجلسة والصلاحيات والاتصال ثم أعد المحاولة. لا تتوفر نتيجة تتبع موثقة." : "Valid genealogy could not be retrieved. Check the lot ID, session, permissions and connection, then retry. No verified trace result is available."}</div>}
    {loading && <p role="status">{isAr ? "جارٍ استرجاع التتبع..." : "Loading lot genealogy..."}</p>}
    <section className="reporting-card" aria-labelledby="genealogy-trace-title"><h2 id="genealogy-trace-title">{isAr ? "البحث والتتبع الجيني للدفعة" : "Genealogy Traversal Parameters"}</h2>
      <form onSubmit={event => void trace(event)} className="form-vertical"><label htmlFor="lot-id-input">{isAr ? "معرّف الدفعة / الشحنة" : "Lot / Batch ID"}</label>
        <input id="lot-id-input" required maxLength={128} value={lot} onChange={event => { invalidate(); setLot(event.target.value); }} />
        <label htmlFor="direction-select">{isAr ? "اتجاه التتبع" : "Trace Direction"}</label>
        <select id="direction-select" value={direction} onChange={event => { invalidate(); setDirection(event.target.value as "forward" | "backward"); }}>
          <option value="backward">{isAr ? "للخلف (ما الذي تم استهلاكه - المكونات)" : "Backward (Consumed Components)"}</option>
          <option value="forward">{isAr ? "للأمام (أين تم استخدامها - الاستدعاء)" : "Forward (Where Used / Recall)"}</option>
        </select><button disabled={!auth.session || !lot.trim() || loading}>{isAr ? "تتبع الشجرة الجينية" : "Trace Genealogy"}</button>
      </form>
    </section>
    {tree ? <section className="reporting-card" aria-labelledby="tree-view-title"><h2 id="tree-view-title">{isAr ? "شجرة الأنساب والتتبع للدفعة" : "Lot Genealogy Visual Tree"}</h2>
      <p role="status">{isAr ? "تم استرجاع شجرة التتبع من الخادم." : "Genealogy returned by the server."}</p><ul className="tree-root">{renderNode(tree)}</ul>
    </section> : !loading && !error && <p role="status">{isAr ? "لم يتم استرجاع شجرة دفعة. أدخل معرّفاً حقيقياً وحدد اتجاه التتبع." : "No genealogy has been retrieved. Enter a real lot ID and choose a trace direction."}</p>}
  </div>;
}
