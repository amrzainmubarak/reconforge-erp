import { AlertTriangle, CalendarDays, CircleCheck, FileWarning, Landmark, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadBankStatementStudio } from "../data";
import type { MessageKey } from "../i18n";
import type { BankStatementStatus, BankStatementStudioContract, Locale } from "../types";
import { formatCount } from "../locale-format";
import { ErrorView, LoadingView } from "./StateViews";
interface BankStatementStudioProps {
  translate: (key: MessageKey) => string;
  locale?: Locale;
}

const statuses: BankStatementStatus[] = ["matched", "exception", "unmatched_bank", "unmatched_ledger", "ambiguous"];

const statusLabels: Record<BankStatementStatus, MessageKey> = {
  matched: "bankMatched",
  exception: "bankException",
  unmatched_bank: "bankUnmatchedBank",
  unmatched_ledger: "bankUnmatchedLedger",
  ambiguous: "bankAmbiguous",
};

function statusLabel(translate: BankStatementStudioProps["translate"], status: BankStatementStatus): string {
  return translate(statusLabels[status]);
}

function varianceClass(value: string | null): string {
  if (value === null || value === "0.00") return "bank-variance bank-variance--zero";
  return value.startsWith("-") ? "bank-variance bank-variance--negative" : "bank-variance bank-variance--positive";
}

export function BankStatementStudio({ translate, locale = "en" }: BankStatementStudioProps) {
  const [data, setData] = useState<BankStatementStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<BankStatementStatus | "">("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadBankStatementStudio(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("bankStatementUnavailable"));
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.decisions.filter((decision) => {
      const haystack = [decision.bank_line_id, decision.account_id, decision.reason_code, ...decision.ledger_record_ids]
        .join(" ")
        .toLocaleLowerCase();
      return (!normalized || haystack.includes(normalized)) && (!status || decision.status === status);
    });
  }, [data, query, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--bank" aria-labelledby="bank-statement-title">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("bankStatement")}</div>
          <h1 id="bank-statement-title">{translate("bankStatementTitle")}</h1>
          <p>{translate("bankStatementIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldCheck size={18} aria-hidden="true" /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <p className="live-boundary bank-boundary"><Landmark size={17} aria-hidden="true" />{translate("bankStatementBoundary")}</p>

      <section className="workbench-stats" aria-label={translate("bankStatementTitle")}>
        <article><span className="stat-icon"><Landmark size={18} /></span><strong>{formatCount(data.summary.total, locale)}</strong><small>{translate("bankTotalLines")}</small></article>
        <article><span className="stat-icon stat-icon--positive"><CircleCheck size={18} /></span><strong>{formatCount(data.summary.matched, locale)}</strong><small>{translate("bankMatchedCount")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{formatCount(data.summary.exceptions, locale)}</strong><small>{translate("bankExceptionCount")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><FileWarning size={18} /></span><strong>{formatCount(data.summary.unmatched, locale)}</strong><small>{translate("bankUnmatchedCount")}</small></article>
        <article><span className="stat-icon"><CalendarDays size={18} /></span><strong>{formatCount(data.date_window_days, locale)}</strong><small>{translate("bankDateWindow")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterBankStatement")} aria-label={translate("filterBankStatement")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value as BankStatementStatus | "")} aria-label={translate("bankStatus")}>
            <option value="">{translate("bankAllStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{statusLabel(translate, value)}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{formatCount(filtered.length, locale)}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table bank-table" tabIndex={0}>
            <table>
              <caption className="sr-only">{translate("bankStatementTitle")}</caption>
              <thead><tr><th>{translate("bankLine")}</th><th>{translate("bankAccount")}</th><th>{translate("bankStatus")}</th><th>{translate("bankLedgerIds")}</th><th>{translate("bankAmountVariance")}</th><th>{translate("bankDaysVariance")}</th><th>{translate("bankReason")}</th></tr></thead>
              <tbody>{filtered.map((decision) => (
                <tr key={decision.bank_line_id}>
                  <th scope="row"><strong>{decision.bank_line_id}</strong></th>
                  <td><code>{decision.account_id}</code></td>
                  <td><span className={`status-chip bank-status--${decision.status}`}><span aria-hidden="true">{decision.status === "matched" ? "✓" : decision.status === "exception" ? "!" : "·"}</span> {statusLabel(translate, decision.status)}</span></td>
                  <td>{decision.ledger_record_ids.length ? decision.ledger_record_ids.join(", ") : "—"}</td>
                  <td><code className={varianceClass(decision.amount_variance)}>{decision.amount_variance ?? "—"}</code></td>
                  <td><code>{decision.days_variance === null ? "—" : decision.days_variance}</code></td>
                  <td><code>{decision.reason_code}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="panel bank-evidence-panel" aria-label={translate("bankEvidence")}>
        <div><strong>{translate("bankEvidence")}</strong><p>{translate("bankEvidenceIntro")}</p></div>
        <dl className="bank-digests"><div><dt>{translate("bankAlgorithm")}</dt><dd><code>{data.algorithm_version}</code></dd></div><div><dt>{translate("decisionDigest")}</dt><dd><code>{data.decision_digest}</code></dd></div><div><dt>{translate("artifactDigest")}</dt><dd><code>{data.artifact_digest}</code></dd></div></dl>
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("bankStatementBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
