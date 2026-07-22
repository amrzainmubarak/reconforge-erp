import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Building2,
  CalendarDays,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Database,
  FileCheck2,
  Gauge,
  Info,
  ListChecks,
  Route,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CSSProperties } from "react";

import type { MessageKey } from "../i18n";
import type { StudioMetric, StudioOverview, StudioPage } from "../types";

interface DashboardProps {
  data: StudioOverview;
  translate: (key: MessageKey) => string;
  colorSafe: boolean;
  onNavigate: (page: StudioPage) => void;
}

const metricLabelKeys: Record<string, MessageKey> = {
  close_completion: "closeCompletion",
  unresolved_high_risk_exceptions: "highRiskExceptions",
  evidence_coverage: "evidenceCoverage",
  match_rate: "matchRate",
  control_effectiveness: "controlEffectiveness",
  period_readiness: "periodReadiness",
  review_aging: "reviewAging",
  exception_aging: "exceptionAging",
};

const featuredMetricKeys = [
  "close_completion",
  "unresolved_high_risk_exceptions",
  "evidence_coverage",
  "match_rate",
];

function formatMetric(metric: StudioMetric): string {
  if (metric.format === "percent") return `${metric.value.toFixed(metric.value % 1 === 0 ? 0 : 1)}%`;
  if (metric.format === "days") return `${metric.value.toFixed(1)}d`;
  return metric.value.toLocaleString();
}

function MetricIcon({ metricKey }: { metricKey: string }) {
  if (metricKey === "close_completion") return <CalendarDays size={19} />;
  if (metricKey === "unresolved_high_risk_exceptions") return <ShieldAlert size={19} />;
  if (metricKey === "evidence_coverage") return <FileCheck2 size={19} />;
  return <TrendingUp size={19} />;
}

function MetricCard({ metric, translate }: { metric: StudioMetric; translate: (key: MessageKey) => string }) {
  return (
    <article className={`metric-card metric-card--${metric.tone}`}>
      <div className="metric-card-topline">
        <span className="metric-icon"><MetricIcon metricKey={metric.key} /></span>
        <button className="metric-info" type="button" title={metric.lineage} aria-label={`${translate("metricLineage")}: ${metric.lineage}`}>
          <Info size={15} />
        </button>
      </div>
      <strong className="metric-value">{formatMetric(metric)}</strong>
      <span className="metric-label">{translate(metricLabelKeys[metric.key] ?? "executivePulse")}</span>
      <div className="metric-context">
        <span className="metric-context-mark" aria-hidden="true" />
        <span>{translate("generated")}</span>
      </div>
    </article>
  );
}

function SectionHeading({ title, help, action }: { title: string; help: string; action?: string }) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        <p>{help}</p>
      </div>
      {action ? (
        <span className="section-action">
          {action} <ArrowUpRight size={14} />
        </span>
      ) : null}
    </div>
  );
}

function statusIcon(status: string) {
  if (status === "Complete") return <CheckCircle2 size={17} />;
  if (status === "In Progress") return <Clock3 size={17} />;
  return <CircleDashed size={17} />;
}

export function Dashboard({ data, translate, colorSafe, onNavigate }: DashboardProps) {
  const metricMap = new Map(data.metrics.map((metric) => [metric.key, metric]));
  const brief = data.executive_brief;
  const featuredMetrics = featuredMetricKeys.map((key) => metricMap.get(key)).filter((metric): metric is StudioMetric => Boolean(metric));
  const pulseMetrics = ["close_completion", "evidence_coverage", "control_effectiveness", "match_rate"]
    .map((key) => metricMap.get(key))
    .filter((metric): metric is StudioMetric => Boolean(metric))
    .map((metric) => ({ name: translate(metricLabelKeys[metric.key]), value: metric.value }));
  const riskColors = colorSafe
    ? ["#6f5bd3", "#0072b2", "#e69f00", "#009e73"]
    : ["#c43d4b", "#e4663a", "#d49c21", "#15977e"];
  const riskData = data.risk_distribution.map((point, index) => ({
    name: translate((point.risk ?? "low") as MessageKey),
    value: point.count,
    color: riskColors[index] ?? "#8d99a6",
  }));
  const totalExceptions = riskData.reduce((sum, point) => sum + point.value, 0);
  const tourSteps: Array<{
    page: StudioPage;
    label: MessageKey;
    help: MessageKey;
    value: string;
    icon: typeof Gauge;
  }> = [
    { page: "dashboard", label: "tourExecutive", help: "tourExecutiveHelp", value: `${data.metrics.length}`, icon: Gauge },
    { page: "exceptions", label: "tourExceptions", help: "tourExceptionsHelp", value: `${brief.open_exception_count}`, icon: ListChecks },
    { page: "evidence", label: "tourEvidence", help: "tourEvidenceHelp", value: `${data.workspace.evidence_count}`, icon: ShieldCheck },
    { page: "inventory", label: "tourInventory", help: "tourInventoryHelp", value: translate("exactControls"), icon: Boxes },
  ];
  const readinessStyle = { "--readiness": `${brief.readiness_score * 3.6}deg` } as CSSProperties;

  return (
    <main className="dashboard-content" id="main-content">
      <section className="page-hero">
        <div className="page-hero-copy">
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("local")}</div>
          <h1>{translate("controlRoom")}</h1>
          <p>{translate("intro")}</p>
          <div className="hero-meta">
            <span><CalendarDays size={15} /> {translate("period")}: <strong>{data.workspace.current_period}</strong></span>
            <span><Database size={15} /> {data.workspace.entity_count} entities</span>
          </div>
        </div>
        <div className="hero-readiness" aria-label={translate("closeReadiness")}>
          <div className="readiness-ring" style={readinessStyle}>
            <div><strong>{brief.readiness_score.toFixed(0)}%</strong><span>{translate("ready")}</span></div>
          </div>
          <div className="readiness-copy">
            <span className={`showcase-status showcase-status--${brief.readiness_status}`}>{translate(brief.readiness_status)}</span>
            <strong>{translate("closeReadiness")}</strong>
            <p>{translate(`readinessStatus${brief.readiness_status[0].toUpperCase()}${brief.readiness_status.slice(1)}` as MessageKey)}</p>
          </div>
        </div>
      </section>

      <section className="showcase-tour" aria-label={translate("guidedShowcase")}>
        <div className="showcase-tour-heading">
          <span><Route size={17} /></span>
          <div><strong>{translate("guidedShowcase")}</strong><small>{translate("guidedShowcaseHelp")}</small></div>
        </div>
        <div className="showcase-tour-steps">
          {tourSteps.map((step, index) => {
            const Icon = step.icon;
            return (
              <button type="button" className={`tour-step ${step.page === "dashboard" ? "tour-step--current" : ""}`} onClick={() => onNavigate(step.page)} key={step.page}>
                <span className="tour-step-index">{index + 1}</span>
                <span className="tour-step-icon"><Icon size={17} /></span>
                <span className="tour-step-copy"><strong>{translate(step.label)}</strong><small>{translate(step.help)}</small></span>
                <span className="tour-step-value">{step.value}</span>
                <ArrowRight className="tour-step-arrow" size={15} />
              </button>
            );
          })}
        </div>
      </section>

      <section className="metrics-grid" aria-label={translate("executivePulse")}>
        {featuredMetrics.length ? featuredMetrics.map((metric) => <MetricCard metric={metric} translate={translate} key={metric.key} />) : <p>{translate("empty")}</p>}
      </section>

      <section className="dashboard-grid dashboard-grid--briefing">
        <article className={`panel decision-panel decision-panel--${brief.readiness_status}`}>
          <SectionHeading title={translate("decisionBrief")} help={translate("decisionBriefHelp")} action={translate("deterministicLineage")} />
          <div className="decision-summary">
            <span className="decision-symbol"><Sparkles size={22} /></span>
            <div>
              <span>{translate("managementFocus")}</span>
              <strong>{translate(`readinessStatus${brief.readiness_status[0].toUpperCase()}${brief.readiness_status.slice(1)}` as MessageKey)}</strong>
            </div>
          </div>
          <div className="decision-signals">
            <div><span>{translate("highRiskItems")}</span><strong>{brief.high_risk_count}</strong></div>
            <div><span>{translate("openExceptions")}</span><strong>{brief.open_exception_count}</strong></div>
            <div><span>{translate("blockedTasks")}</span><strong>{brief.blocked_task_count}</strong></div>
            <div><span>{translate("completedTasks")}</span><strong>{brief.completed_task_count}/{data.workspace.close_task_count}</strong></div>
          </div>
        </article>

        <article className="panel domain-panel">
          <SectionHeading title={translate("controlCoverage")} help={translate("controlCoverageHelp")} />
          {data.control_domains.length ? <div className="domain-list">
            {data.control_domains.map((domain) => (
              <div className="domain-row" title={domain.lineage} key={domain.domain}>
                <div><strong>{translate(`domain${domain.domain[0].toUpperCase()}${domain.domain.slice(1)}` as MessageKey)}</strong><span className={`showcase-status showcase-status--${domain.status}`}>{translate(domain.status)}</span></div>
                <div className="domain-progress"><i style={{ width: `${domain.score}%` }} /></div>
                <strong>{domain.score.toFixed(domain.score % 1 === 0 ? 0 : 1)}%</strong>
              </div>
            ))}
          </div> : <p className="empty-panel">{translate("empty")}</p>}
        </article>
      </section>

      <section className="panel entity-health-panel">
        <SectionHeading title={translate("entityHealth")} help={translate("entityHealthHelp")} action={`${data.entity_health.length} ${translate("entities")}`} />
        {data.entity_health.length ? (
          <div className="entity-health-grid">
            {data.entity_health.map((entity) => (
              <article className={`entity-health-card entity-health-card--${entity.status}`} key={entity.entity_code}>
                <div className="entity-health-title">
                  <span><Building2 size={18} /></span>
                  <div><strong>{entity.entity_name}</strong><small>{entity.entity_code} · {entity.region} · {entity.currency}</small></div>
                  <span className={`showcase-status showcase-status--${entity.status}`}>{translate(entity.status)}</span>
                </div>
                <div className="entity-health-metrics">
                  <span><strong>{entity.open_exception_count}</strong>{translate("openExceptions")}</span>
                  <span><strong>{entity.high_risk_count}</strong>{translate("highRiskItems")}</span>
                </div>
              </article>
            ))}
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <section className="dashboard-grid dashboard-grid--charts">
        <article className="panel panel--wide">
          <SectionHeading title={translate("executivePulse")} help={translate("executivePulseHelp")} action={translate("metricLineage")} />
          {pulseMetrics.length ? (
            <div className="chart-wrap" aria-label={translate("executivePulse")}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pulseMetrics} margin={{ top: 12, right: 6, left: -20, bottom: 4 }} accessibilityLayer>
                  <CartesianGrid vertical={false} stroke="var(--border-subtle)" strokeDasharray="3 5" />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                  <Tooltip cursor={{ fill: "var(--surface-hover)" }} contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 12 }} />
                  <Bar dataKey="value" fill="#168d7b" radius={[8, 8, 3, 3]} maxBarSize={42} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="empty-panel">{translate("empty")}</p>}
        </article>

        <article className="panel risk-panel">
          <SectionHeading title={translate("riskMix")} help={translate("riskMixHelp")} />
          {totalExceptions ? (
            <div className="risk-visual">
              <div className="risk-chart-wrap">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart accessibilityLayer>
                    <Pie data={riskData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={78} paddingAngle={3} stroke="none" isAnimationActive={false}>
                      {riskData.map((point) => <Cell fill={point.color} key={point.name} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="risk-total"><strong>{totalExceptions}</strong><span>{translate("exceptions")}</span></div>
              </div>
              <div className="risk-legend">
                {riskData.map((point) => (
                  <div className="risk-legend-row" key={point.name}>
                    <span className="legend-dot" style={{ background: point.color }} />
                    <span>{point.name}</span>
                    <strong>{point.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : <p className="empty-panel">{translate("empty")}</p>}
        </article>
      </section>

      <section className="dashboard-grid dashboard-grid--work">
        <article className="panel close-panel">
          <SectionHeading title={translate("closeProgress")} help={translate("closeProgressHelp")} action={`${data.workspace.close_task_count} tasks`} />
          {data.close_tasks.length ? (
            <ol className="task-list">
              {data.close_tasks.map((task, index) => (
                <li className={`task-row task-row--${task.status.toLowerCase().replaceAll(" ", "-")}`} key={task.task_id}>
                  <div className="task-step">
                    <span>{statusIcon(task.status)}</span>
                    {index < data.close_tasks.length - 1 ? <i aria-hidden="true" /> : null}
                  </div>
                  <div className="task-copy">
                    <strong>{task.name}</strong>
                    <span>{task.owner}</span>
                  </div>
                  <span className="status-chip">{task.status}</span>
                </li>
              ))}
            </ol>
          ) : <p className="empty-panel">{translate("empty")}</p>}
        </article>

        <article className="panel exception-panel">
          <SectionHeading title={translate("priorityQueue")} help={translate("priorityQueueHelp")} action={`${data.exceptions.length} shown`} />
          {data.exceptions.length ? (
            <div className="table-scroll" tabIndex={0} aria-label={translate("priorityQueue")}>
              <table>
                <thead>
                  <tr>
                    <th>{translate("exception")}</th>
                    <th>{translate("entity")}</th>
                    <th>{translate("risk")}</th>
                    <th>{translate("status")}</th>
                    <th>{translate("owner")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.exceptions.slice(0, 5).map((exception, index) => (
                    <tr key={`${exception.source_type}-${exception.control_code}-${index}`}>
                      <td>
                        <span className="exception-title"><Activity size={15} /> {exception.description}</span>
                        <small>{exception.control_code || exception.source_type}</small>
                      </td>
                      <td>{exception.entity_code || "—"}</td>
                      <td><span className={`risk-chip risk-chip--${exception.risk_rating}`}>{exception.risk_rating}</span></td>
                      <td>{exception.status}</td>
                      <td>{exception.owner || "Unassigned"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="empty-panel">{translate("empty")}</p>}
        </article>
      </section>

      <footer className="data-provenance">
        <span><span className="status-dot" /> {translate("generated")}</span>
        <span>{data.synthetic_data_marker}</span>
      </footer>
    </main>
  );
}
