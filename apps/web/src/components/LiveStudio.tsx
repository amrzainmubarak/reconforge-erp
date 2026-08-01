import { AlertTriangle, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { loadLiveStudioContract } from "../data";
import type { MessageKey } from "../i18n";
import type { LiveStudioContract } from "../types";

export function LiveStudio({ translate }: { translate: (key: MessageKey) => string }) {
  const [contract, setContract] = useState<LiveStudioContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setContract(null);
    setError("");
    loadLiveStudioContract({ signal: controller.signal })
      .then(setContract)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : translate("liveUnavailable"));
      });
    return () => controller.abort();
  }, [attempt, translate]);

  return <main id="main-content" className="workbench-content live-studio">
    <section className="workbench-hero workbench-hero--live" aria-labelledby="live-title">
      <div><p className="eyebrow">{translate("liveStudio")}</p><h1 id="live-title">{translate("liveTitle")}</h1><p>{translate("liveIntro")}</p></div>
      <div className="contract-badge"><ShieldCheck size={20} aria-hidden="true" /><span>{translate("liveSource")}<strong>/api/v1/metrics/dashboard</strong></span></div>
    </section>

    <p className="live-boundary"><Database size={17} aria-hidden="true" />{translate("liveBoundary")}</p>
    {!contract && !error ? <section className="panel live-state" role="status" aria-live="polite"><RefreshCw className="live-spinner" size={22} aria-hidden="true" /><h2>{translate("liveLoading")}</h2></section> : null}
    {error ? <section className="panel live-state live-state--error" role="alert"><AlertTriangle size={24} aria-hidden="true" /><h2>{translate("liveUnavailable")}</h2><p>{error}</p><button type="button" className="primary-button" onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={16} aria-hidden="true" />{translate("liveRetry")}</button></section> : null}
    {contract?.empty ? <section className="panel live-state" role="status"><Database size={24} aria-hidden="true" /><h2>{translate("liveEmpty")}</h2><p>{contract.endpoint}</p></section> : null}
    {contract && !contract.empty ? <>
      <section className={`live-freshness ${contract.stale ? "live-freshness--stale" : ""}`} role={contract.stale ? "alert" : "status"}>
        {contract.stale ? <AlertTriangle size={18} aria-hidden="true" /> : <ShieldCheck size={18} aria-hidden="true" />}
        <strong>{contract.stale ? translate("liveStale") : translate("liveFresh")}</strong>
        <span>{contract.generated_at}</span>
      </section>
      <section className="panel live-table-panel" aria-label={translate("liveTitle")}>
        <div className="table-scroll"><table className="live-table"><thead><tr><th>{translate("liveMetric")}</th><th>{translate("period")}</th><th>{translate("liveValue")}</th><th>{translate("liveComputed")}</th><th>{translate("liveLineage")}</th></tr></thead><tbody>{contract.metrics.map((metric) => <tr key={`${metric.period_name}:${metric.metric_key}`}><th scope="row"><strong>{metric.name}</strong><code>{metric.metric_key}</code></th><td>{metric.period_name}</td><td><code>{metric.value_text}</code></td><td>{metric.computed_at}</td><td>{metric.lineage}</td></tr>)}</tbody></table></div>
      </section>
    </> : null}
  </main>;
}
