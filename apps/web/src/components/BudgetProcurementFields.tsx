import { useEffect, useState } from "react";
import { loadBudgetPage, type BudgetEnvelope } from "../budget-control-data";
import type { ProcurementScope } from "../procurement-data";
import type { BrowserAdminSession, Locale } from "../types";

export function BudgetProcurementFields({ session, scope, periodId, locked, locale, value, onChange, onError }: {
  session: BrowserAdminSession; scope: ProcurementScope; periodId: string; locked: boolean; locale: Locale;
  value: BudgetEnvelope | null; onChange(value: BudgetEnvelope | null): void; onError(error: unknown): void;
}) {
  const [offset, setOffset] = useState(0), [next, setNext] = useState(false), [records, setRecords] = useState<BudgetEnvelope[]>([]);
  const ar = locale === "ar";
  useEffect(() => {
    const controller = new AbortController();
    const budgetScope = { workspace_id: scope.workspace_id, organization_id: scope.organization_id, legal_entity_id: scope.legal_entity_id };
    loadBudgetPage(session, budgetScope, offset, controller.signal).then((page) => {
      if (!controller.signal.aborted) { setRecords(page.envelopes); setNext(page.pagination.has_more); }
    }).catch((error) => { if (!controller.signal.aborted) onError(error); });
    return () => controller.abort();
  }, [session, scope, offset]);
  const eligible = records.filter((budget) => budget.status === "Approved" && budget.currency_code === scope.currency_code && budget.period_id === periodId);
  return <fieldset disabled={locked}><legend>{ar ? "اعتماد شراء معتمد" : "Approved purchase appropriation"}</legend>
    <p>{ar ? "ابدأ رقم الأمر بـ BPC1-. يُحجز كامل ثمن البضاعة فور إنشاء الأمر؛ تُحفظ الكميات والأسعار الأصلية." : "Begin the order number with BPC1-. Creating the order reserves its complete merchandise value and retains its original quantities and prices."}</p>
    <label>{ar ? "الاعتماد" : "Appropriation"}<select required value={value?.id ?? ""} onChange={(event) => onChange(eligible.find((budget) => budget.id === event.target.value) ?? null)}>
      <option value="">—</option>{value && !eligible.some((budget) => budget.id === value.id) && <option value={value.id}>{value.budget_code}</option>}
      {eligible.map((budget) => <option key={budget.id} value={budget.id}>{budget.budget_code} · {budget.available_minor} {budget.currency_code} · v{budget.row_version}</option>)}
    </select></label>
    <button type="button" disabled={locked || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>{ar ? "الاعتمادات السابقة" : "Previous appropriations"}</button>
    <button type="button" disabled={locked || !next} onClick={() => setOffset(offset + 25)}>{ar ? "الاعتمادات التالية" : "Next appropriations"}</button>
  </fieldset>;
}
