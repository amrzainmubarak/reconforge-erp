import { AlertTriangle, CircleCheck, FileCheck2, FileWarning, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadProfessionalInvoicePaymentStudio } from "../data";
import type { MessageKey } from "../i18n";
import type { ProfessionalInvoicePaymentStatus, ProfessionalInvoicePaymentStudioContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface ProfessionalInvoicePaymentStudioProps {
  translate: (key: MessageKey) => string;
}

const statuses: ProfessionalInvoicePaymentStatus[] = ["matched", "exception", "unmatched_invoice", "unmatched_payment", "ambiguous"];

const statusLabels: Record<ProfessionalInvoicePaymentStatus, MessageKey> = {
  matched: "professionalMatched",
  exception: "professionalException",
  unmatched_invoice: "professionalUnmatchedInvoice",
  unmatched_payment: "professionalUnmatchedPayment",
  ambiguous: "professionalAmbiguous",
};

function statusLabel(translate: ProfessionalInvoicePaymentStudioProps["translate"], status: ProfessionalInvoicePaymentStatus): string {
  return translate(statusLabels[status]);
}

function varianceClass(value: string | null): string {
  if (value === null || value === "0.00") return "professional-variance professional-variance--zero";
  return value.startsWith("-") ? "professional-variance professional-variance--negative" : "professional-variance professional-variance--positive";
}

export function ProfessionalInvoicePaymentStudio({ translate }: ProfessionalInvoicePaymentStudioProps) {
  const [data, setData] = useState<ProfessionalInvoicePaymentStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<ProfessionalInvoicePaymentStatus | "">("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadProfessionalInvoicePaymentStudio(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("professionalInvoicePaymentUnavailable"));
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.decisions.filter((decision) => {
      const haystack = [decision.invoice_id, decision.client_id, decision.reason_code, ...decision.payment_ids].join(" ").toLocaleLowerCase();
      return (!normalized || haystack.includes(normalized)) && (!status || decision.status === status);
    });
  }, [data, query, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--professional" aria-labelledby="professional-invoice-payment-title">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("professionalInvoicePayment")}</div>
          <h1 id="professional-invoice-payment-title">{translate("professionalInvoicePaymentTitle")}</h1>
          <p>{translate("professionalInvoicePaymentIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldCheck size={18} aria-hidden="true" /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <p className="live-boundary professional-boundary"><FileCheck2 size={17} aria-hidden="true" />{translate("professionalInvoicePaymentBoundary")}</p>

      <section className="workbench-stats" aria-label={translate("professionalInvoicePaymentTitle")}>
        <article><span className="stat-icon"><FileCheck2 size={18} /></span><strong>{data.summary.total}</strong><small>{translate("professionalTotalDecisions")}</small></article>
        <article><span className="stat-icon stat-icon--positive"><CircleCheck size={18} /></span><strong>{data.summary.matched}</strong><small>{translate("professionalMatchedCount")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{data.summary.exceptions}</strong><small>{translate("professionalExceptionCount")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><FileWarning size={18} /></span><strong>{data.summary.ambiguous}</strong><small>{translate("professionalAmbiguousCount")}</small></article>
        <article><span className="stat-icon"><FileCheck2 size={18} /></span><strong>{data.payment_window_days}</strong><small>{translate("professionalPaymentWindow")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterProfessionalInvoicePayment")} aria-label={translate("filterProfessionalInvoicePayment")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value as ProfessionalInvoicePaymentStatus | "")} aria-label={translate("professionalStatus")}>
            <option value="">{translate("professionalAllStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{statusLabel(translate, value)}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{filtered.length}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table professional-table" tabIndex={0}>
            <table>
              <caption className="sr-only">{translate("professionalInvoicePaymentTitle")}</caption>
              <thead><tr><th>{translate("professionalInvoice")}</th><th>{translate("professionalClient")}</th><th>{translate("professionalStatus")}</th><th>{translate("professionalPayments")}</th><th>{translate("professionalAmountVariance")}</th><th>{translate("professionalDaysVariance")}</th><th>{translate("professionalReason")}</th></tr></thead>
              <tbody>{filtered.map((decision) => (
                <tr key={decision.invoice_id}>
                  <th scope="row"><strong>{decision.invoice_id}</strong></th>
                  <td><code>{decision.client_id}</code></td>
                  <td><span className={`status-chip professional-status--${decision.status}`}><span aria-hidden="true">{decision.status === "matched" ? "✓" : decision.status === "exception" ? "!" : "·"}</span> {statusLabel(translate, decision.status)}</span></td>
                  <td>{decision.payment_ids.length ? decision.payment_ids.join(", ") : "—"}</td>
                  <td><code className={varianceClass(decision.amount_variance)}>{decision.amount_variance === null ? "—" : `${decision.amount_variance} ${data.currency}`}</code></td>
                  <td><code>{decision.days_from_due_date === null ? "—" : decision.days_from_due_date}</code></td>
                  <td><code>{decision.reason_code}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="panel professional-evidence-panel" aria-label={translate("professionalEvidence")}>
        <div><strong>{translate("professionalEvidence")}</strong><p>{translate("professionalEvidenceIntro")}</p></div>
        <dl className="professional-digests"><div><dt>{translate("professionalAlgorithm")}</dt><dd><code>{data.algorithm_version}</code></dd></div><div><dt>{translate("decisionDigest")}</dt><dd><code>{data.decision_digest}</code></dd></div><div><dt>{translate("artifactDigest")}</dt><dd><code>{data.artifact_digest}</code></dd></div></dl>
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("professionalInvoicePaymentBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
