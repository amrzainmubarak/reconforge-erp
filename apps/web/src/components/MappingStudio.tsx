import { AlertTriangle, CheckCircle2, FileInput, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import type { MessageKey } from "../i18n";
import type { Locale } from "../types";
import { formatCount } from "../locale-format";
import { canonicalFields, emptyMapping, parsePreview, validateMapping, type ColumnMapping, type PreviewTable } from "../mapping";

const sample = `txn_id,amount_text,currency_code,posting_date,description
TX-001,1250.00,USD,2026-07-01,Invoice receipt
TX-002,,USD,2026-07-02,Missing amount remains visible
TX-003,not-a-number,EUR,2026-07-03,Malformed amount remains visible`;

export function MappingStudio({ translate, locale = "en" }: { translate: (key: MessageKey) => string; locale?: Locale }) {
  const [table, setTable] = useState<PreviewTable>(() => parsePreview(sample));
  const [mapping, setMapping] = useState<ColumnMapping>(() => emptyMapping());
  const [loadError, setLoadError] = useState("");
  const issues = useMemo(() => validateMapping(table, mapping), [table, mapping]);

  const loadText = (text: string) => {
    try { setTable(parsePreview(text)); setMapping(emptyMapping()); setLoadError(""); }
    catch (error) { setLoadError(error instanceof Error ? error.message : translate("mappingLoadError")); }
  };

  return (
    <main id="main-content" className="workbench-content mapping-studio">
      <section className="workbench-hero workbench-hero--mapping" aria-labelledby="mapping-title">
        <div><p className="eyebrow">{translate("mappingStudio")}</p><h1 id="mapping-title">{translate("mappingTitle")}</h1><p>{translate("mappingIntro")}</p></div>
        <div className="contract-badge"><ShieldCheck size={20} aria-hidden="true" /><span>{translate("safePreview")}<strong>{translate("localOnly")}</strong></span></div>
      </section>

      <section className="panel mapping-source" aria-labelledby="source-title">
        <div><h2 id="source-title">{translate("sourcePreview")}</h2><p>{translate("previewLimits")}</p></div>
        <label className="mapping-file"><FileInput size={18} aria-hidden="true" /><span>{translate("chooseCsv")}</span>
          <input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (!file) return;
            if (!/\.(csv|tsv)$/i.test(file.name) || !["", "text/csv", "text/tab-separated-values"].includes(file.type)) { setLoadError(translate("unsupportedMappingFile")); return; }
            if (file.size > 256 * 1024) { setLoadError("Preview exceeds the 256 KiB safety limit."); return; }
            void file.text().then(loadText).catch(() => setLoadError(translate("mappingLoadError")));
          }} />
        </label>
        {loadError ? <p className="mapping-error" role="alert"><AlertTriangle size={16} aria-hidden="true" />{loadError}</p> : null}
        {table.truncated ? <p className="mapping-warning" role="status">{translate("previewTruncated")}</p> : null}
      </section>

      <section className="panel" aria-labelledby="mapping-fields-title">
        <h2 id="mapping-fields-title">{translate("mapColumns")}</h2>
        <div className="mapping-grid">
          {canonicalFields.map((field) => <label key={field}><span>{field.replaceAll("_", " ")} <strong aria-hidden="true">*</strong></span><select value={mapping[field]} onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))}><option value="">{translate("notMapped")}</option>{table.headers.map((header) => <option value={header} key={header}>{header}</option>)}</select></label>)}
        </div>
      </section>

      <section className="panel" aria-labelledby="quality-title">
        <div className="mapping-quality-heading"><div><h2 id="quality-title">{translate("dataQuality")}</h2><p>{translate("noImplicitZero")}</p></div><strong className={issues.length ? "mapping-issue-count" : "mapping-valid"}>{issues.length ? <AlertTriangle size={16} aria-hidden="true" /> : <CheckCircle2 size={16} aria-hidden="true" />}{formatCount(issues.length, locale)} {translate("issues")}</strong></div>
        <div className="table-shell mapping-table"><table><caption className="sr-only">{translate("sourcePreview")}</caption><thead><tr><th scope="col">#</th>{table.headers.map((header) => <th scope="col" key={header}>{header}</th>)}</tr></thead><tbody>{table.rows.slice(0, 20).map((row, index) => <tr key={`${index}-${row[0] ?? ""}`}><th scope="row">{index + 1}</th>{row.map((value, column) => <td key={`${column}-${table.headers[column]}`} className={value === "" ? "mapping-cell-error" : ""}>{value === "" ? <span><AlertTriangle size={13} aria-hidden="true" />{translate("missingValue")}</span> : value}</td>)}</tr>)}</tbody></table></div>
        {issues.length ? <ul className="mapping-issues" aria-live="polite">{issues.slice(0, 12).map((issue, index) => <li key={`${issue.row}-${issue.field}-${issue.code}-${index}`}>{issue.row ? `Row ${issue.row}: ` : ""}{issue.field.replaceAll("_", " ")} — {issue.code.replaceAll("_", " ")}{issue.value ? ` (${issue.value})` : ""}</li>)}</ul> : null}
      </section>
    </main>
  );
}
