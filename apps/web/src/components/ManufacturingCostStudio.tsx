import { AlertTriangle, CircleCheck, Factory, FileWarning, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadManufacturingCostStudio } from "../data";
import type { MessageKey } from "../i18n";
import type { ManufacturingCostStatus, ManufacturingCostStudioContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface ManufacturingCostStudioProps {
  translate: (key: MessageKey) => string;
}

const statuses: ManufacturingCostStatus[] = ["reconciled", "exception", "unmatched"];

const statusLabels: Record<ManufacturingCostStatus, MessageKey> = {
  reconciled: "mfgReconciled",
  exception: "mfgException",
  unmatched: "mfgUnmatched",
};

function statusLabel(translate: ManufacturingCostStudioProps["translate"], status: ManufacturingCostStatus): string {
  return translate(statusLabels[status]);
}

function varianceClass(value: string): string {
  if (value === "0.00") return "manufacturing-variance manufacturing-variance--zero";
  return value.startsWith("-") ? "manufacturing-variance manufacturing-variance--negative" : "manufacturing-variance manufacturing-variance--positive";
}

export function ManufacturingCostStudio({ translate }: ManufacturingCostStudioProps) {
  const [data, setData] = useState<ManufacturingCostStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<ManufacturingCostStatus | "">("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadManufacturingCostStudio(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("manufacturingCostUnavailable"));
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.decisions.filter((decision) => {
      const haystack = [decision.order_id, decision.product_id, ...decision.reason_codes].join(" ").toLocaleLowerCase();
      return (!normalized || haystack.includes(normalized)) && (!status || decision.status === status);
    });
  }, [data, query, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--manufacturing" aria-labelledby="manufacturing-cost-title">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("manufacturingCost")}</div>
          <h1 id="manufacturing-cost-title">{translate("manufacturingCostTitle")}</h1>
          <p>{translate("manufacturingCostIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldCheck size={18} aria-hidden="true" /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <p className="live-boundary manufacturing-boundary"><Factory size={17} aria-hidden="true" />{translate("manufacturingCostBoundary")}</p>

      <section className="workbench-stats" aria-label={translate("manufacturingCostTitle")}>
        <article><span className="stat-icon"><Factory size={18} /></span><strong>{data.summary.total}</strong><small>{translate("mfgTotalOrders")}</small></article>
        <article><span className="stat-icon stat-icon--positive"><CircleCheck size={18} /></span><strong>{data.summary.reconciled}</strong><small>{translate("mfgReconciledCount")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{data.summary.exceptions}</strong><small>{translate("mfgExceptionCount")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><FileWarning size={18} /></span><strong>{data.summary.unmatched}</strong><small>{translate("mfgUnmatchedCount")}</small></article>
        <article><span className="stat-icon"><Factory size={18} /></span><strong>{data.max_scrap_quantity} {data.unit}</strong><small>{translate("mfgScrapLimit")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterManufacturing")} aria-label={translate("filterManufacturing")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value as ManufacturingCostStatus | "")} aria-label={translate("mfgStatus")}>
            <option value="">{translate("mfgAllStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{statusLabel(translate, value)}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{filtered.length}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table manufacturing-table" tabIndex={0}>
            <table>
              <caption className="sr-only">{translate("manufacturingCostTitle")}</caption>
              <thead><tr><th>{translate("mfgOrder")}</th><th>{translate("mfgProduct")}</th><th>{translate("mfgStatus")}</th><th>{translate("mfgPlannedQty")}</th><th>{translate("mfgIssuedQty")}</th><th>{translate("mfgCompletedQty")}</th><th>{translate("mfgScrapQty")}</th><th>{translate("mfgMaterialVariance")}</th><th>{translate("mfgCompletionVariance")}</th><th>{translate("mfgReasons")}</th></tr></thead>
              <tbody>{filtered.map((decision) => (
                <tr key={decision.order_id}>
                  <th scope="row"><strong>{decision.order_id}</strong></th>
                  <td><code>{decision.product_id}</code></td>
                  <td><span className={`status-chip manufacturing-status--${decision.status}`}><span aria-hidden="true">{decision.status === "reconciled" ? "✓" : decision.status === "exception" ? "!" : "·"}</span> {statusLabel(translate, decision.status)}</span></td>
                  <td><code>{decision.planned_quantity} {data.unit}</code></td>
                  <td><code>{decision.issued_quantity} {data.unit}</code></td>
                  <td><code>{decision.completed_quantity} {data.unit}</code></td>
                  <td><code>{decision.scrap_quantity} {data.unit}</code></td>
                  <td><code className={varianceClass(decision.material_cost_variance)}>{decision.material_cost_variance} {data.currency}</code></td>
                  <td><code className={varianceClass(decision.completion_cost_variance)}>{decision.completion_cost_variance} {data.currency}</code></td>
                  <td><code>{decision.reason_codes.join(", ")}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="panel manufacturing-evidence-panel" aria-label={translate("mfgEvidence")}>
        <div><strong>{translate("mfgEvidence")}</strong><p>{translate("mfgEvidenceIntro")}</p></div>
        <dl className="manufacturing-digests"><div><dt>{translate("mfgAlgorithm")}</dt><dd><code>{data.algorithm_version}</code></dd></div><div><dt>{translate("decisionDigest")}</dt><dd><code>{data.decision_digest}</code></dd></div><div><dt>{translate("artifactDigest")}</dt><dd><code>{data.artifact_digest}</code></dd></div></dl>
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("manufacturingCostBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
