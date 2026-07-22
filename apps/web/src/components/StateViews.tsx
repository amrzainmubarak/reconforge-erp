import { AlertTriangle, DatabaseZap, RefreshCw } from "lucide-react";

import type { MessageKey } from "../i18n";

export function LoadingView({ translate }: { translate: (key: MessageKey) => string }) {
  return (
    <main className="state-view" aria-live="polite">
      <div className="state-orbit" aria-hidden="true"><DatabaseZap size={24} /></div>
      <strong>{translate("loading")}</strong>
      <div className="loading-grid" aria-hidden="true">
        <span /><span /><span /><span />
      </div>
    </main>
  );
}
export function ErrorView({
  translate,
  message,
  onRetry,
}: {
  translate: (key: MessageKey) => string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="state-view" role="alert">
      <div className="state-orbit state-orbit--error" aria-hidden="true"><AlertTriangle size={24} /></div>
      <h1>{translate("loadError")}</h1>
      <p>{message}</p>
      <button className="primary-button" type="button" onClick={onRetry}>
        <RefreshCw size={16} /> {translate("retry")}
      </button>
      <code>reconforge demo studio-data</code>
    </main>
  );
}
