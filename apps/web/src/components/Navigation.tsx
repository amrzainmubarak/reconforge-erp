import {
  Activity,
  Archive,
  Bell,
  Boxes,
  Check,
  ChevronDown,
  ClipboardCheck,
  Code2,
  CreditCard,
  Factory,
  FileChartColumn,
  FileInput,
  Gauge,
  RadioTower,
  Layers3,
  Landmark,
  PackageSearch,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ComponentType } from "react";

import type { MessageKey } from "../i18n";
import type { StudioPage } from "../types";
import { isLiveOperationalPage, operationalPageLabel } from "../studio-pages";

export type NavStudioPage = StudioPage | "crmSubscriptions" | "governedAssistant" | "projectMilestones";

export interface NavigationItem {
  key: string;
  label: MessageKey;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" | "false" }>;
  href?: string;
  page?: NavStudioPage;
  status?: "foundation" | "planned";
}

export interface NavigationGroup {
  label: MessageKey;
  items: NavigationItem[];
}

const currentStudio = import.meta.env.VITE_CURRENT_STUDIO_URL ?? "http://127.0.0.1:8601";

const originalNavigationGroups: NavigationGroup[] = [
  {
    label: "erpNavigation",
    items: [
      { key: "enterprise-finance", label: "enterpriseFinance", icon: Landmark, page: "enterpriseFinance" },
      { key: "financial-reporting", label: "financialReporting", icon: FileChartColumn, page: "financialReporting" },
      { key: "fixed-assets", label: "fixedAssets", icon: Landmark, page: "fixedAssets" },
      { key: "manufacturing-execution", label: "manufacturingExecution", icon: Factory, page: "manufacturingExecution" },
      { key: "intercompany-operations", label: "intercompanyOperations", icon: Landmark, page: "intercompanyOperations" },
      { key: "manufacturing-execution-v2", label: "manufacturingExecutionV2", icon: Factory, page: "manufacturingExecutionV2" },
      { key: "intercompany-fx", label: "intercompanyFx", icon: Landmark, page: "intercompanyFx" },
      { key: "intercompany-group-diagnostic", label: "groupDiagnostic", icon: FileChartColumn, page: "groupDiagnostic" },
      { key: "intercompany-source-cashflow", label: "intercompanyCashflow", icon: FileChartColumn, page: "intercompanyCashflow" },
      { key: "project-source-reconciliation", label: "projectSourceReconciliation", icon: FileChartColumn, page: "projectSourceReconciliation" },
      { key: "people-project-payroll", label: "peopleProjectPayroll", icon: FileChartColumn, page: "peopleProjectPayroll" },
      { key: "project-time-billing", label: "projectTimeBilling", icon: FileChartColumn, page: "projectTimeBilling" },
      { key: "accrual-deferral", label: "accrualDeferral", icon: FileChartColumn, page: "accrualDeferral" },
      { key: "manufacturing-supply-plan", label: "manufacturingSupplyPlan", icon: Factory, page: "manufacturingSupplyPlan" },
      { key: "procurement-sourcing", label: "procurementSourcing", icon: Boxes, page: "procurementSourcing" },
      { key: "customer-returns", label: "customerReturns", icon: Landmark, page: "customerReturns" },
      { key: "operational-fx-tax", label: "operationalFxTax", icon: Landmark, page: "operationalFxTax" },
      { key: "stock-sales", label: "stockSales", icon: Boxes, page: "stockSales" },
      { key: "procurement-partial", label: "procurementPartial", icon: Boxes, page: "procurementPartial" },
      { key: "sales-revenue", label: "salesRevenue", icon: FileChartColumn, page: "salesRevenue" },
      { key: "procurement-operations", label: "procurementOperations", icon: Boxes, page: "procurementOperations" },
      { key: "crm-subscriptions", label: "crmSubscriptions", icon: CreditCard, page: "crmSubscriptions" },
      { key: "hcm-leave", label: "hcmLeave", icon: ClipboardCheck, page: "hcmLeave" },
      { key: "project-milestones", label: "projectMilestones", icon: FileChartColumn, page: "projectMilestones" },
      { key: "master-production-schedule", label: "masterProductionSchedule", icon: Factory, page: "masterProductionSchedule" },
      { key: "shop-floor-traceability", label: "shopFloorTraceability", icon: Boxes, page: "shopFloorTraceability" },
      { key: "consolidated-statements", label: "consolidatedStatements", icon: Landmark, page: "consolidatedStatements" },
    ],
  },
  {
    label: "overview",
    items: [{ key: "dashboard", label: "dashboard", icon: Gauge, page: "dashboard" }],
  },
  {
    label: "finance",
    items: [
      { key: "receivables", label: "receivables", icon: FileChartColumn, page: "receivables" },
      { key: "budget-control", label: "budgetControl", icon: FileChartColumn, page: "budgetControl" },
      { key: "reconciliation", label: "reconciliation", icon: Activity, href: `${currentStudio}/reconciliation`, status: "foundation" },
      { key: "exceptions", label: "exceptions", icon: ShieldCheck, page: "exceptions", status: "foundation" },
      { key: "evidence", label: "evidence", icon: Archive, page: "evidence", status: "foundation" },
      { key: "close", label: "close", icon: ClipboardCheck, href: `${currentStudio}/close`, status: "foundation" },
      { key: "retail-settlement", label: "retailSettlement", icon: CreditCard, page: "retailSettlement", status: "foundation" },
      { key: "bank-statement", label: "bankStatement", icon: Landmark, page: "bankStatement", status: "foundation" },
      { key: "professional-invoice-payment", label: "professionalInvoicePayment", icon: FileChartColumn, page: "professionalInvoicePayment", status: "foundation" },
      { key: "individual-cashflow", label: "individualCashflow", icon: CreditCard, page: "individualCashflow", status: "foundation" },
    ],
  },
  {
    label: "operations",
    items: [
      { key: "inventory", label: "inventory", icon: Boxes, page: "inventory", status: "foundation" },
      { key: "inventory-receipts", label: "inventoryReceipt", icon: Boxes, page: "inventoryReceipt" },
      { key: "inventory-transfer", label: "inventoryTransfer", icon: Boxes, page: "inventoryTransfer" },
      { key: "manufacturing", label: "manufacturingCost", icon: Factory, page: "manufacturingCost", status: "foundation" },
    ],
  },
  {
    label: "platform",
    items: [
      { key: "governed-assistant", label: "governedAssistant", icon: Sparkles, page: "governedAssistant" },
      { key: "reports", label: "reports", icon: FileChartColumn, href: `${currentStudio}/downloads`, status: "foundation" },
      { key: "packs", label: "packs", icon: PackageSearch, href: `${currentStudio}/control-packs`, status: "foundation" },
      { key: "mapping", label: "mappingStudio", icon: FileInput, page: "mapping", status: "foundation" },
      { key: "rules", label: "ruleStudio", icon: Code2, page: "rules", status: "foundation" },
      { key: "live", label: "liveStudio", icon: RadioTower, page: "live", status: "foundation" },
      { key: "admin-audit", label: "adminAudit", icon: ShieldCheck, page: "adminAudit", status: "foundation" },
      { key: "notifications", label: "notifications", icon: Bell, page: "notifications", status: "foundation" },
      { key: "jobs", label: "durableJobs", icon: Activity, page: "durableJobs" },
      { key: "settings", label: "settings", icon: Settings, status: "planned" },
      { key: "developer", label: "developer", icon: Code2, href: `${currentStudio}/docs`, status: "foundation" },
    ],
  },
];

const sections: Array<[MessageKey, string[]]> = [
  ["navOverview", ["dashboard", "exceptions", "evidence", "notifications"]],
  ["navFinance", ["enterprise-finance", "financial-reporting", "receivables", "budget-control", "fixed-assets", "accrual-deferral", "operational-fx-tax"]],
  ["navSales", ["sales-revenue", "stock-sales", "customer-returns", "crm-subscriptions", "professional-invoice-payment"]],
  ["navSupply", ["procurement-operations", "procurement-partial", "procurement-sourcing", "inventory", "inventory-receipts", "inventory-transfer"]],
  ["navManufacturing", ["manufacturing-execution", "manufacturing-execution-v2", "manufacturing-supply-plan", "master-production-schedule", "shop-floor-traceability", "manufacturing"]],
  ["navPeople", ["people-project-payroll", "hcm-leave", "project-source-reconciliation", "project-time-billing", "project-milestones"]],
  ["navGroup", ["intercompany-operations", "intercompany-fx", "intercompany-group-diagnostic", "intercompany-source-cashflow", "consolidated-statements", "bank-statement", "retail-settlement", "individual-cashflow"]],
  ["navPlatform", ["reconciliation", "close", "governed-assistant", "reports", "packs", "mapping", "rules", "live", "admin-audit", "jobs", "settings", "developer"]],
];
const allItems = originalNavigationGroups.flatMap(group => group.items);
export const navigationGroups: NavigationGroup[] = sections.map(([label, keys]) => ({ label, items: keys.map(key => allItems.find(item => item.key === key)!) }));
export function navigationGroupForPage(page: NavStudioPage): NavigationGroup | undefined {
  const canonical = page === "crmContracts" ? "crmSubscriptions" : page === "projectMilestoneBilling" ? "projectMilestones" : page;
  return navigationGroups.find(group => group.items.some(item => item.page === canonical));
}

interface SidebarProps {
  translate: (key: MessageKey) => string;
  collapsed: boolean;
  mobileOpen: boolean;
  onCollapse: () => void;
  onMobileClose: () => void;
  activePage: NavStudioPage;
  onNavigate: (page: NavStudioPage) => void;
  canView?: (page: NavStudioPage) => boolean;
}

export function Sidebar({ translate, collapsed, mobileOpen, onCollapse, onMobileClose, activePage, onNavigate, canView = () => true }: SidebarProps) {
  const [query, setQuery] = useState("");
  const [expandedGroup, setExpandedGroup] = useState<MessageKey | null>(() => navigationGroupForPage(activePage)?.label ?? "navOverview");
  useEffect(() => { setExpandedGroup(navigationGroupForPage(activePage)?.label ?? "navOverview"); }, [activePage]);
  const [viewport, setViewport] = useState(() => ({ mobile: window.matchMedia?.("(max-width: 840px)").matches ?? false, tablet: window.matchMedia?.("(min-width: 841px) and (max-width: 1060px)").matches ?? false }));
  useEffect(() => {
    if (!window.matchMedia) return;
    const mobile = window.matchMedia("(max-width: 840px)"), tablet = window.matchMedia("(min-width: 841px) and (max-width: 1060px)");
    const update = () => setViewport({ mobile: mobile.matches, tablet: tablet.matches });
    mobile.addEventListener("change", update); tablet.addEventListener("change", update);
    return () => { mobile.removeEventListener("change", update); tablet.removeEventListener("change", update); };
  }, []);
  const rail = !mobileOpen && (collapsed || viewport.tablet);
  useLayoutEffect(() => {
    if (rail) setQuery("");
  }, [rail]);
  const drawer = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer.current?.querySelector<HTMLElement>("button")?.focus();
    return () => { document.body.style.overflow = bodyOverflow; previous?.focus(); };
  }, [mobileOpen]);
  function trapDrawer(event: React.KeyboardEvent<HTMLElement>) {
    if (mobileOpen && event.key === "Escape") { event.preventDefault(); onMobileClose(); return; }
    if (!mobileOpen || event.key !== "Tab") return;
    const controls = [...(drawer.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input, a[href], summary') ?? [])].filter(control => (!control.closest("details:not([open])") || control.tagName === "SUMMARY") && getComputedStyle(control).display !== "none" && getComputedStyle(control).visibility !== "hidden");
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  const filteredGroups = navigationGroups.map(group => ({ ...group, items: group.items.filter(item => (!item.page || canView(item.page)) && `${translate(item.label)} ${translate(group.label)} ${item.key}`.toLocaleLowerCase().includes(query.toLocaleLowerCase().trim())) })).filter(group => group.items.length);
  const liveOperationalPage = isLiveOperationalPage(activePage as StudioPage) || ["crmSubscriptions", "projectMilestones", "governedAssistant"].includes(activePage);
  return (
    <aside inert={viewport.mobile && !mobileOpen} ref={drawer} role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen ? true : undefined} aria-label={translate("primaryNavigation")} onKeyDown={trapDrawer} className={`sidebar ${rail ? "sidebar--collapsed" : ""} ${mobileOpen ? "sidebar--mobile-open" : ""}`}>
      <div className="brand-row">
        <div className="brand-mark" aria-hidden="true">
          <Layers3 size={20} />
        </div>
        <div className="brand-copy">
          <strong>ReconForge</strong>
          <span>Studio</span>
        </div>
        <button className="icon-button sidebar-close-mobile" type="button" onClick={onMobileClose} aria-label={translate("closeDialog")}>
          <PanelLeftClose size={18} />
        </button>
      </div>

      <details className="workspace-disclosure">
        <summary className="workspace-switcher" aria-label={translate("workspaceDetails")}>
          <span className="workspace-avatar">FC</span>
          <span className="workspace-copy">
            <strong>{translate(operationalPageLabel(activePage as StudioPage) ?? (activePage === "crmSubscriptions" ? "crmSubscriptions" : activePage === "projectMilestones" ? "projectMilestones" : activePage === "governedAssistant" ? "governedAssistant" : "local"))}</strong>
            <small>{translate(liveOperationalPage ? "arLiveSession" : "preview")}</small>
          </span>
          <ChevronDown className="workspace-chevron" size={15} aria-hidden="true" />
        </summary>
        <div className="workspace-menu">
          <div className="workspace-menu-option">
            <span className="workspace-avatar">FC</span>
            <span className="workspace-copy">
              <strong>{translate("local")}</strong>
              <small>{translate("workspaceOnly")}</small>
            </span>
            <Check size={15} aria-hidden="true" />
          </div>
        </div>
      </details>

      <label className="navigation-search"><span>{translate("navFilter")}</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={translate("navFilter")} /></label>
      <nav className="desktop-navigation" aria-label={translate("primaryNavigation")}>
        {filteredGroups.map((group) => (
          <details className="nav-group" key={group.label} open={rail || query.trim() ? true : group.label === expandedGroup}>
            <summary className="nav-group-label" title={translate(group.label)} onClick={event => { event.preventDefault(); setExpandedGroup(current => current === group.label ? null : group.label); }}>{translate(group.label)}<ChevronDown size={14} aria-hidden="true" /></summary>
            {group.items.map((item) => {
              const Icon = item.icon;
              const content = (
                <>
                  <Icon size={18} aria-hidden="true" />
                  <span className="nav-item-label">{translate(item.label)}</span>
                  {item.status ? <span className={`nav-status nav-status--${item.status}`}>{translate(item.status)}</span> : null}
                </>
              );
              if (item.page) {
                return (
                  <button
                    className={`nav-item ${activePage === item.page ? "nav-item--active" : ""}`}
                    type="button"
                    aria-label={translate(item.label)}
                    title={translate(item.label)}
                    aria-current={activePage === item.page ? "page" : undefined}
                    key={item.key}
                    onClick={() => {
                      onNavigate(item.page as StudioPage);
                      setQuery("");
                      setExpandedGroup(group.label);
                      onMobileClose();
                    }}
                  >
                    {content}
                  </button>
                );
              }
              if (item.href) {
                return (
                  <a className="nav-item" aria-label={translate(item.label)} href={item.href} target="_blank" rel="noreferrer" key={item.key} onClick={() => {
                    setQuery("");
                    setExpandedGroup(navigationGroupForPage(activePage)?.label ?? "navOverview");
                    onMobileClose();
                  }}>
                    {content}
                  </a>
                );
              }
              return (
                <button className="nav-item" type="button" aria-label={translate(item.label)} disabled key={item.key} title={translate("planned")}>
                  {content}
                </button>
              );
            })}
          </details>
        ))}
        {!filteredGroups.length && <p className="navigation-empty" role="status">{translate("navNoResults")}</p>}
      </nav>

      <div className="sidebar-footer">
        <div className="local-state">
          <span className="status-dot" aria-hidden="true" />
          <span>
            <strong>{translate(liveOperationalPage ? "arLiveSession" : "readOnly")}</strong>
            <small>{translate(operationalPageLabel(activePage as StudioPage) ?? (activePage === "crmSubscriptions" ? "crmSubscriptions" : activePage === "projectMilestones" ? "projectMilestones" : activePage === "governedAssistant" ? "governedAssistant" : "localNote"))}</small>
          </span>
        </div>
        <button className="collapse-button" type="button" onClick={onCollapse} aria-label={translate(collapsed ? "expandSidebar" : "collapseSidebar")}>
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          <span>{collapsed ? "" : translate("collapseSidebar")}</span>
        </button>
      </div>
    </aside>
  );
}

interface MobileDockProps {
  canView?: (page: NavStudioPage) => boolean;
  translate: (key: MessageKey) => string;
  onMenu: () => void;
  onQuickAction: () => void;
  activePage: NavStudioPage;
  onNavigate: (page: NavStudioPage) => void;
}

export function MobileDock({ translate, onMenu, onQuickAction, activePage, onNavigate, canView = () => true }: MobileDockProps) {
  const live = isLiveOperationalPage(activePage as StudioPage) || ["crmSubscriptions", "projectMilestones", "governedAssistant"].includes(activePage);
  const shortcuts: Array<{ page: NavStudioPage; label: MessageKey; icon: NavigationItem["icon"] }> = live ? [
    { page: "enterpriseFinance", label: "enterpriseFinance", icon: Gauge },
    { page: "salesRevenue", label: "salesRevenue", icon: ShieldCheck },
    { page: "inventoryReceipt", label: "inventoryReceipt", icon: Boxes },
    { page: "procurementOperations", label: "procurementOperations", icon: ClipboardCheck },
  ] : [{ page: "dashboard", label: "dashboard", icon: Gauge }, { page: "exceptions", label: "exceptions", icon: ShieldCheck }];
  return <nav className="mobile-dock" aria-label={translate("mobileNav")}>
    {shortcuts.filter(item => canView(item.page)).map(item => <button type="button" key={item.page} className={`mobile-dock-item ${activePage === item.page ? "mobile-dock-item--active" : ""}`} onClick={() => onNavigate(item.page)} aria-current={activePage === item.page ? "page" : undefined}><item.icon size={20} aria-hidden="true" /><span>{translate(item.label)}</span></button>)}
    {!live && <><button type="button" className="mobile-create" onClick={onQuickAction} aria-label={translate("quickCreate")}><Sparkles size={21} aria-hidden="true" /></button><a href={`${currentStudio}/close`} target="_blank" rel="noreferrer" className="mobile-dock-item"><ClipboardCheck size={20} aria-hidden="true" /><span>{translate("close")}</span></a></>}
    <button type="button" className="mobile-dock-item" onClick={onMenu}><PanelLeftOpen size={20} aria-hidden="true" /><span>{translate("menu")}</span></button>
  </nav>;
}
