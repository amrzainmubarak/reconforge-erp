import { Component, createRef, type ReactNode } from "react";

import type { Locale } from "../types";
import "./WorkspaceErrorBoundary.css";

const copy = {
  en: {
    title: "Workspace unavailable",
    detail: "This workspace could not be displayed. Navigation remains available.",
    evidence: "Business commands are not retried automatically. Check retained evidence for any earlier action before submitting it again.",
    reference: "Support reference",
    dashboard: "Open dashboard",
    reload: "Reload page",
  },
  ar: {
    title: "مساحة العمل غير متاحة",
    detail: "تعذّر عرض مساحة العمل. تظل أدوات التنقل متاحة.",
    evidence: "لا تُعاد أوامر الأعمال تلقائيًا. راجع الأدلة المحفوظة لأي إجراء سابق قبل إرساله مرة أخرى.",
    reference: "مرجع الدعم",
    dashboard: "فتح لوحة المتابعة",
    reload: "إعادة تحميل الصفحة",
  },
} as const;

interface WorkspaceErrorBoundaryProps {
  children: ReactNode;
  locale: Locale;
  onDashboard: () => void;
  onReload: () => void;
}

interface WorkspaceErrorBoundaryState {
  failed: boolean;
}

/** Keep page failures inside the workspace, without replaying business actions. */
export class WorkspaceErrorBoundary extends Component<WorkspaceErrorBoundaryProps, WorkspaceErrorBoundaryState> {
  state: WorkspaceErrorBoundaryState = { failed: false };
  private readonly alert = createRef<HTMLDivElement>();

  static getDerivedStateFromError(): WorkspaceErrorBoundaryState {
    // No exception message, stack, source payload or actor data enters UI state.
    return { failed: true };
  }

  componentDidMount(): void {
    if (this.state.failed) this.alert.current?.focus();
  }

  componentDidUpdate(_previousProps: WorkspaceErrorBoundaryProps, previousState: WorkspaceErrorBoundaryState): void {
    if (this.state.failed && !previousState.failed) this.alert.current?.focus();
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    const words = copy[this.props.locale];
    return (
      <main id="main-content" className="workbench-content workspace-recovery" dir={this.props.locale === "ar" ? "rtl" : "ltr"}>
        <section className="panel workspace-recovery-panel">
          <div ref={this.alert} role="alert" tabIndex={-1} className="workspace-recovery-alert">
            <h1>{words.title}</h1>
            <p>{words.detail}</p>
            <p>{words.evidence}</p>
            <p>{words.reference}: <code dir="ltr">RF-WORKSPACE-001</code></p>
          </div>
          <div className="workspace-recovery-actions">
            <button type="button" className="primary-button" onClick={this.props.onDashboard}>{words.dashboard}</button>
            <button type="button" className="workspace-recovery-reload" onClick={this.props.onReload}>{words.reload}</button>
          </div>
        </section>
      </main>
    );
  }
}
