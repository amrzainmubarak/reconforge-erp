import { AlertTriangle, CircleCheck, FileCheck2, FileWarning, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadIndividualCashflowStudio } from "../data";
import type { MessageKey } from "../i18n";
import type { IndividualCashflowStatus, IndividualCashflowStudioContract, Locale } from "../types";
import { formatCount } from "../locale-format";
import { ErrorView, LoadingView } from "./StateViews";
interface IndividualCashflowStudioProps {
  translate: (key: MessageKey) => string;
  locale?: Locale;
}

const statuses: IndividualCashflowStatus[] = ["within_budget", "over_budget", "unbudgeted", "no_activity"];

const statusLabels: Record<IndividualCashflowStatus, MessageKey> = {
  within_budget: "individualWithinBudget",
  over_budget: "individualOverBudget",
  unbudgeted: "individualUnbudgeted",
  no_activity: "individualNoActivity",
};

function statusLabel(translate: IndividualCashflowStudioProps["translate"], status: IndividualCashflowStatus): string {
  return translate(statusLabels[status]);
}

function flowLabel(translate: IndividualCashflowStudioProps["translate"], flowType: "income" | "expense"): string {
  return translate(flowType === "income" ? "individualIncome" : "individualExpense");
}

function varianceClass(value: string | null): string {
  if (value === null || value === "0.00") return "individual-variance individual-variance--zero";
  return value.startsWith("-") ? "individual-variance individual-variance--within" : "individual-variance individual-variance--over";
}

export function IndividualCashflowStudio({ translate, locale = "en" }: IndividualCashflowStudioProps) {
  const [data, setData] = useState<IndividualCashflowStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<IndividualCashflowStatus | "">("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadIndividualCashflowStudio(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("individualCashflowUnavailable"));
      });
    return () => controller.abort();
  }, [attempt, translate]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.decisions.filter((decision) => {
      const haystack = [decision.period, decision.flow_type, decision.category, decision.reason_code, ...decision.transaction_ids].join(" ").toLocaleLowerCase();
      return (!normalized || haystack.includes(normalized)) && (!status || decision.status === status);
    });
  }, [data, query, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--individual" aria-labelledby="individual-cashflow-title">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("individualCashflow")}</div>
          <h1 id="individual-cashflow-title">{translate("individualCashflowTitle")}</h1>
          <p>{translate("individualCashflowIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldCheck size={18} aria-hidden="true" /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <p className="live-boundary individual-boundary"><FileCheck2 size={17} aria-hidden="true" />{translate("individualCashflowBoundary")}</p>

      <section className="workbench-stats" aria-label={translate("individualCashflowTitle")}>
        <article><span className="stat-icon"><FileCheck2 size={18} /></span><strong>{formatCount(data.summary.total, locale)}</strong><small>{translate("individualTotalDecisions")}</small></article>
        <article><span className="stat-icon stat-icon--positive"><CircleCheck size={18} /></span><strong>{formatCount(data.summary.within_budget, locale)}</strong><small>{translate("individualWithinBudgetCount")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{formatCount(data.summary.over_budget, locale)}</strong><small>{translate("individualOverBudgetCount")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><FileWarning size={18} /></span><strong>{formatCount(data.summary.unbudgeted, locale)}</strong><small>{translate("individualUnbudgetedCount")}</small></article>
        <article><span className="stat-icon"><FileCheck2 size={18} /></span><strong>{formatCount(data.summary.no_activity, locale)}</strong><small>{translate("individualNoActivityCount")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterIndividualCashflow")} aria-label={translate("filterIndividualCashflow")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value as IndividualCashflowStatus | "")} aria-label={translate("individualStatus")}>
            <option value="">{translate("individualAllStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{statusLabel(translate, value)}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{formatCount(filtered.length, locale)}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table individual-table" tabIndex={0}>
            <table>
              <caption className="sr-only">{translate("individualCashflowTitle")}</caption>
              <thead><tr><th>{translate("individualPeriod")}</th><th>{translate("individualFlowType")}</th><th>{translate("individualCategory")}</th><th>{translate("individualStatus")}</th><th>{translate("individualActual")}</th><th>{translate("individualBudget")}</th><th>{translate("individualVariance")}</th><th>{translate("individualReason")}</th></tr></thead>
              <tbody>{filtered.map((decision) => (
                <tr key={`${decision.period}:${decision.flow_type}:${decision.category}`}>
                  <th scope="row"><strong>{decision.period}</strong></th>
                  <td>{flowLabel(translate, decision.flow_type)}</td>
                  <td><code>{decision.category}</code></td>
                  <td><span className={`status-chip individual-status--${decision.status}`}><span aria-hidden="true">{decision.status === "within_budget" ? "✓" : decision.status === "over_budget" ? "!" : "·"}</span> {statusLabel(translate, decision.status)}</span></td>
                  <td><code>{decision.actual} {data.currency}</code></td>
                  <td><code>{decision.budget === null ? "—" : `${decision.budget} ${data.currency}`}</code></td>
                  <td><code className={varianceClass(decision.variance)}>{decision.variance === null ? "—" : `${decision.variance} ${data.currency}`}</code></td>
                  <td><code>{decision.reason_code}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="panel individual-evidence-panel" aria-label={translate("individualEvidence")}>
        <div><strong>{translate("individualEvidence")}</strong><p>{translate("individualEvidenceIntro")}</p></div>
        <dl className="individual-digests"><div><dt>{translate("individualAlgorithm")}</dt><dd><code>{data.algorithm_version}</code></dd></div><div><dt>{translate("decisionDigest")}</dt><dd><code>{data.decision_digest}</code></dd></div><div><dt>{translate("artifactDigest")}</dt><dd><code>{data.artifact_digest}</code></dd></div></dl>
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("individualCashflowBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
