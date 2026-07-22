import { Archive, CheckCircle2, FileCheck2, Fingerprint, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadEvidenceBinder } from "../data";
import type { MessageKey } from "../i18n";
import type { EvidenceBinderContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface EvidenceBinderProps {
  translate: (key: MessageKey) => string;
}

function unique(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

export function EvidenceBinder({ translate }: EvidenceBinderProps) {
  const [data, setData] = useState<EvidenceBinderContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [redaction, setRedaction] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadEvidenceBinder(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "The local evidence binder could not be loaded.");
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.evidence.filter((record) => {
      const haystack = [record.evidence_code, record.provenance_type, record.checksum_sha256].join(" ").toLocaleLowerCase();
      return (
        (!normalized || haystack.includes(normalized)) &&
        (!status || record.evidence_status === status) &&
        (!redaction || record.redaction_status === redaction)
      );
    });
  }, [data, query, redaction, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  const statuses = unique(data.evidence.map((record) => record.evidence_status));
  const redactions = unique(data.evidence.map((record) => record.redaction_status));

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--evidence">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("localContract")}</div>
          <h1>{translate("evidenceBinderTitle")}</h1>
          <p>{translate("evidenceBinderIntro")}</p>
        </div>
        <div className="contract-badge"><Archive size={18} /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <section className="workbench-stats workbench-stats--four" aria-label={translate("evidenceBinderTitle")}>
        <article><span className="stat-icon"><FileCheck2 size={18} /></span><strong>{data.summary.total}</strong><small>{translate("totalRecords")}</small></article>
        <article><span className="stat-icon"><CheckCircle2 size={18} /></span><strong>{data.summary.coverage_percent.toFixed(data.summary.coverage_percent % 1 ? 1 : 0)}%</strong><small>{translate("evidenceCoverage")}</small></article>
        <article><span className="stat-icon"><Fingerprint size={18} /></span><strong>{data.summary.checksum_count}</strong><small>{translate("verifiedChecksums")}</small></article>
        <article><span className="stat-icon"><ShieldCheck size={18} /></span><strong>{data.summary.available}</strong><small>{translate("availableEvidence")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar filter-toolbar--evidence">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterEvidence")} aria-label={translate("filterEvidence")} />
          </label>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value)} aria-label={translate("status")}>
            <option value="">{translate("allStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
          <select value={redaction} onChange={(event) => setRedaction(event.currentTarget.value)} aria-label={translate("redaction")}>
            <option value="">{translate("allRedactions")}</option>
            {redactions.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{filtered.length}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table" tabIndex={0}>
            <table>
              <thead><tr><th>{translate("evidenceCode")}</th><th>{translate("provenance")}</th><th>{translate("redaction")}</th><th>{translate("status")}</th><th>{translate("checksum")}</th></tr></thead>
              <tbody>
                {filtered.map((record) => (
                  <tr key={`${record.evidence_code}-${record.checksum_sha256}`}>
                    <td><span className="evidence-title"><FileCheck2 size={15} />{record.evidence_code}</span></td>
                    <td>{record.provenance_type}</td>
                    <td><span className="status-chip">{record.redaction_status}</span></td>
                    <td><span className="status-chip evidence-status">{record.evidence_status}</span></td>
                    <td><code className="checksum" title={record.checksum_sha256}>{record.checksum_sha256.slice(0, 12)}…{record.checksum_sha256.slice(-8)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("boundedMetadata")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
