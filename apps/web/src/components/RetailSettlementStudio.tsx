import { AlertTriangle, CircleCheck, CircleDollarSign, FileWarning, Search, ShieldCheck, Store } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadRetailSettlementStudio } from "../data";
import type { MessageKey } from "../i18n";
import type { RetailSettlementStatus, RetailSettlementStudioContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface RetailSettlementStudioProps {
  translate: (key: MessageKey) => string;
}

const statuses: RetailSettlementStatus[] = ["matched", "exception", "unmatched_pos", "unmatched_settlement", "ambiguous"];

const statusLabels: Record<RetailSettlementStatus, MessageKey> = {
  matched: "retailMatched",
  exception: "retailException",
  unmatched_pos: "retailUnmatchedPos",
  unmatched_settlement: "retailUnmatchedSettlement",
  ambiguous: "retailAmbiguous",
};

function statusLabel(translate: RetailSettlementStudioProps["translate"], status: RetailSettlementStatus): string {
  return translate(statusLabels[status]);
}

function varianceClass(value: string | null): string {
  if (value === null || value === "0.00") return "retail-variance retail-variance--zero";
  return value.startsWith("-") ? "retail-variance retail-variance--negative" : "retail-variance retail-variance--positive";
}

export function RetailSettlementStudio({ translate }: RetailSettlementStudioProps) {
  const [data, setData] = useState<RetailSettlementStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<RetailSettlementStatus | "">("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadRetailSettlementStudio(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("retailSettlementUnavailable"));
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.decisions.filter((decision) => {
      const haystack = [decision.batch_id, decision.store_id, decision.reason_code, ...decision.settlement_ids]
        .join(" ")
        .toLocaleLowerCase();
      return (!normalized || haystack.includes(normalized)) && (!status || decision.status === status);
    });
  }, [data, query, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--retail">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("retailSettlement")}</div>
          <h1>{translate("retailSettlementTitle")}</h1>
          <p>{translate("retailSettlementIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldCheck size={18} aria-hidden="true" /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <p className="live-boundary retail-boundary"><CircleDollarSign size={17} aria-hidden="true" />{translate("retailSettlementBoundary")}</p>

      <section className="workbench-stats" aria-label={translate("retailSettlementTitle")}>
        <article><span className="stat-icon"><Store size={18} /></span><strong>{data.summary.total}</strong><small>{translate("retailTotalRuns")}</small></article>
        <article><span className="stat-icon stat-icon--positive"><CircleCheck size={18} /></span><strong>{data.summary.matched}</strong><small>{translate("retailMatchedCount")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{data.summary.exceptions}</strong><small>{translate("retailExceptionCount")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><FileWarning size={18} /></span><strong>{data.summary.unmatched}</strong><small>{translate("retailUnmatchedCount")}</small></article>
        <article><span className="stat-icon"><ShieldCheck size={18} /></span><strong>{data.currency} {data.tolerance}</strong><small>{translate("retailTolerance")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterRetailSettlement")} aria-label={translate("filterRetailSettlement")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value as RetailSettlementStatus | "")} aria-label={translate("retailStatus")}>
            <option value="">{translate("retailAllStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{statusLabel(translate, value)}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{filtered.length}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table retail-table" tabIndex={0}>
            <table>
              <caption className="sr-only">{translate("retailSettlementTitle")}</caption>
              <thead><tr><th>{translate("retailBatch")}</th><th>{translate("retailStore")}</th><th>{translate("retailStatus")}</th><th>{translate("retailSettlementIds")}</th><th>{translate("retailExpectedNet")}</th><th>{translate("retailActualNet")}</th><th>{translate("retailVariance")}</th><th>{translate("retailReason")}</th></tr></thead>
              <tbody>{filtered.map((decision) => (
                <tr key={decision.batch_id}>
                  <th scope="row"><strong>{decision.batch_id}</strong><small>{decision.currency}</small></th>
                  <td>{decision.store_id}</td>
                  <td><span className={`status-chip retail-status--${decision.status}`}><span aria-hidden="true">{decision.status === "matched" ? "✓" : decision.status === "exception" ? "!" : "·"}</span> {statusLabel(translate, decision.status)}</span></td>
                  <td>{decision.settlement_ids.length ? decision.settlement_ids.join(", ") : "—"}</td>
                  <td><code>{decision.expected_card_net}</code></td>
                  <td><code>{decision.settlement_net ?? "—"}</code></td>
                  <td><code className={varianceClass(decision.net_variance)}>{decision.net_variance ?? "—"}</code></td>
                  <td><code>{decision.reason_code}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="panel retail-evidence-panel" aria-label={translate("retailEvidence")}>
        <div><strong>{translate("retailEvidence")}</strong><p>{translate("retailEvidenceIntro")}</p></div>
        <dl className="retail-digests"><div><dt>{translate("retailAlgorithm")}</dt><dd><code>{data.algorithm_version}</code></dd></div><div><dt>{translate("decisionDigest")}</dt><dd><code>{data.decision_digest}</code></dd></div><div><dt>{translate("artifactDigest")}</dt><dd><code>{data.artifact_digest}</code></dd></div></dl>
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("retailSettlementBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
