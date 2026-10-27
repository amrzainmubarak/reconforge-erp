import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { MobileDock, Sidebar } from "./components/Navigation";
import { AccessibilityPanel, CommandPalette } from "./components/Overlays";
import { ErrorView, LoadingView } from "./components/StateViews";
import { NoticesPanel, ProfilePanel, QuickPanel, Topbar, type OpenPanel } from "./components/Topbar";
import { WorkspaceErrorBoundary } from "./components/WorkspaceErrorBoundary";
import { loadStudioOverview } from "./data";
import { translate, type MessageKey } from "./i18n";
import { usePreferences } from "./preferences";
import type { StudioOverviewWithProvenance, StudioPage, ThemePreference } from "./types";
import { BrowserSessionProvider, useBrowserSession } from "./browserSession";
import { StudioSessionControls } from "./components/StudioSessionControls";
import { useNavigationAccess } from "./navigation-access";
import { isLiveOperationalPage } from "./studio-pages";

const themes: ThemePreference[] = ["system", "light", "dark"];
const SalesRevenueWorkspace = lazy(() => import("./components/SalesRevenueWorkspace").then((module) => ({ default: module.SalesRevenueWorkspace })));
const ProcurementWorkspace = lazy(() => import("./components/ProcurementWorkspace").then((module) => ({ default: module.ProcurementWorkspace })));
const EnterpriseFinanceWorkspace = lazy(() => import("./components/EnterpriseFinanceWorkspace"));
const StockSalesPage = lazy(() => import("./components/StockSalesPage").then((module) => ({ default: module.StockSalesPage })));
const ProcurementPartialPage = lazy(() => import("./components/ProcurementPartialPage").then((module) => ({ default: module.ProcurementPartialPage })));
const FinancialReportingPage = lazy(() => import("./components/FinancialReportingPage"));
const FixedAssetsPage = lazy(() => import("./components/FixedAssetsPage"));
const CustomerReturnsPage = lazy(() => import("./components/CustomerReturnsPage"));
const OperationalFxTaxPage = lazy(() => import("./components/OperationalFxTaxPage"));
const ManufacturingExecutionPage = lazy(() => import("./components/ManufacturingExecutionPage").then((module) => ({ default: module.ManufacturingExecutionPage })));
const IntercompanyOperationsPage = lazy(() => import("./components/IntercompanyOperationsPage"));
const ManufacturingExecutionV2Page = lazy(() => import("./components/ManufacturingExecutionV2Page").then((module) => ({ default: module.ManufacturingExecutionV2Page })));
const IntercompanyFxPage = lazy(() => import("./components/IntercompanyFxPage"));
const GroupDiagnosticPage = lazy(() => import("./components/GroupDiagnosticPage"));
const IntercompanyCashflowPage = lazy(() => import("./components/IntercompanyCashflowPage"));
const ProjectSourceReconciliationPage = lazy(() => import("./components/ProjectSourceReconciliationPage").then((module) => ({ default: module.ProjectSourceReconciliationPage })));
const PeopleProjectPayrollPage = lazy(() => import("./components/PeopleProjectPayrollPage").then((module) => ({ default: module.PeopleProjectPayrollPage })));
const ProjectTimeBillingPage = lazy(() => import("./components/ProjectTimeBillingPage").then((module) => ({ default: module.ProjectTimeBillingPage })));
const AccrualDeferralPage = lazy(() => import("./components/AccrualDeferralPage").then((module) => ({ default: module.AccrualDeferralPage })));
const ManufacturingSupplyPlanPage = lazy(() => import("./components/ManufacturingSupplyPlanPage").then((module) => ({ default: module.ManufacturingSupplyPlanPage })));
const InventoryTransferPage = lazy(() => import("./components/InventoryTransferPage").then((module) => ({ default: module.InventoryTransferPage })));
const ProcurementSourcingPage = lazy(() => import("./components/ProcurementSourcingPage").then((module) => ({ default: module.ProcurementSourcingPage })));
const Dashboard = lazy(() => import("./components/Dashboard").then((module) => ({ default: module.Dashboard })));
const ExceptionQueue = lazy(() => import("./components/ExceptionQueue").then((module) => ({ default: module.ExceptionQueue })));
const EvidenceBinder = lazy(() => import("./components/EvidenceBinder").then((module) => ({ default: module.EvidenceBinder })));
const InventoryControl = lazy(() => import("./components/InventoryControl").then((module) => ({ default: module.InventoryControl })));
const RetailSettlementStudio = lazy(() => import("./components/RetailSettlementStudio").then((module) => ({ default: module.RetailSettlementStudio })));
const BankStatementStudio = lazy(() => import("./components/BankStatementStudio").then((module) => ({ default: module.BankStatementStudio })));
const ManufacturingCostStudio = lazy(() => import("./components/ManufacturingCostStudio").then((module) => ({ default: module.ManufacturingCostStudio })));
const ProfessionalInvoicePaymentStudio = lazy(() => import("./components/ProfessionalInvoicePaymentStudio").then((module) => ({ default: module.ProfessionalInvoicePaymentStudio })));
const IndividualCashflowStudio = lazy(() => import("./components/IndividualCashflowStudio").then((module) => ({ default: module.IndividualCashflowStudio })));
const MappingStudio = lazy(() => import("./components/MappingStudio").then((module) => ({ default: module.MappingStudio })));
const RuleStudio = lazy(() => import("./components/RuleStudio").then((module) => ({ default: module.RuleStudio })));
const LiveStudio = lazy(() => import("./components/LiveStudio").then((module) => ({ default: module.LiveStudio })));
const AdminAudit = lazy(() => import("./components/AdminAudit").then((module) => ({ default: module.AdminAudit })));
const NotificationInbox = lazy(() => import("./components/NotificationInbox").then((module) => ({ default: module.NotificationInbox })));
const ReceivablesWorkspace = lazy(() => import("./components/ReceivablesWorkspace").then((module) => ({ default: module.ReceivablesWorkspace })));
const BudgetControlWorkspace = lazy(() => import("./components/BudgetControlWorkspace").then((module) => ({ default: module.BudgetControlWorkspace })));
const InventoryReceiptPosting = lazy(() => import("./components/InventoryReceiptPosting").then((module) => ({ default: module.InventoryReceiptPosting })));
const JobOperationsWorkspace = lazy(() => import("./components/JobOperationsWorkspace").then((module) => ({ default: module.JobOperationsWorkspace })));
const ConsolidatedStatementsPage = lazy(() => import("./components/ConsolidatedStatementsPage"));
const MasterProductionSchedulePage = lazy(() => import("./components/MasterProductionSchedulePage"));
const ShopFloorTraceabilityPage = lazy(() => import("./components/ShopFloorTraceabilityPage"));
const CrmSubscriptionWorkspace = lazy(() => import("./components/CrmSubscriptionWorkspace").then((module) => ({ default: module.CrmSubscriptionWorkspace })));
const HcmLeaveWorkspace = lazy(() => import("./components/HcmLeaveWorkspace").then((module) => ({ default: module.HcmLeaveWorkspace })));
const GovernedAssistantWorkspace = lazy(() => import("./components/GovernedAssistantWorkspace").then((module) => ({ default: module.GovernedAssistantWorkspace })));
const ProjectMilestoneWorkspace = lazy(() => import("./components/ProjectMilestoneWorkspace").then((module) => ({ default: module.ProjectMilestoneWorkspace })));

import { pageFromPath, pathForPage, type AppStudioPage } from "./studio-routes";
export type { AppStudioPage } from "./studio-routes";

export default function App() {
  return <BrowserSessionProvider><StudioApp /></BrowserSessionProvider>;
}

function StudioApp() {
  const auth = useBrowserSession();
  const access = useNavigationAccess();
  const preferences = usePreferences();
  const t = useCallback((key: MessageKey) => translate(preferences.locale, key), [preferences.locale]);
  const [data, setData] = useState<StudioOverviewWithProvenance | null>(null);
  const [error, setError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => { try { return localStorage.getItem("reconforge.studio.sidebar-collapsed") === "true"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("reconforge.studio.sidebar-collapsed", String(sidebarCollapsed)); } catch { /* Layout preference remains usable without storage. */ } }, [sidebarCollapsed]);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const lastSidebarFocus = useRef<HTMLElement | null>(null);
  const pendingDesktopFocus = useRef<HTMLElement | null>(null);
  const shell = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mobile = window.matchMedia("(max-width: 840px)");
    let focusFrame: number | undefined;
    const handleViewportChange = (event: MediaQueryListEvent) => {
      if (!event.matches) {
        if (mobileMenuOpen) pendingDesktopFocus.current = lastSidebarFocus.current;
        setMobileMenuOpen(false);
      } else if (!mobileMenuOpen && lastSidebarFocus.current) {
        const sidebar = shell.current?.querySelector<HTMLElement>("aside.sidebar");
        const focused = document.activeElement;
        if (focused !== document.body && !sidebar?.contains(focused)) return;
        focusFrame = window.requestAnimationFrame(() => {
          const current = document.activeElement;
          if (!mobile.matches || (current !== document.body && !sidebar?.contains(current))) return;
          const menu = shell.current?.querySelector<HTMLButtonElement>("button.mobile-menu-button");
          if (menu?.getClientRects().length) menu.focus();
        });
      }
    };
    mobile.addEventListener("change", handleViewportChange);
    return () => {
      mobile.removeEventListener("change", handleViewportChange);
      if (focusFrame !== undefined) window.cancelAnimationFrame(focusFrame);
    };
  }, [mobileMenuOpen]);
  useLayoutEffect(() => {
    if (mobileMenuOpen) return;
    const previous = pendingDesktopFocus.current;
    pendingDesktopFocus.current = null;
    if (!previous || previous.getClientRects().length > 0) return;
    const focused = document.activeElement;
    if (focused !== document.body && focused !== previous) return;
    const sidebar = shell.current?.querySelector<HTMLElement>("aside.sidebar");
    const navigation = sidebar?.querySelector<HTMLElement>("nav.desktop-navigation");
    const current = navigation?.querySelector<HTMLElement>('[aria-current="page"]');
    const candidates = navigation?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]') ?? [];
    const visible = (element: HTMLElement) => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";
    const workspace = sidebar?.querySelector<HTMLElement>("summary.workspace-switcher");
    const target = (current && visible(current) ? current : [...candidates].find(visible)) ?? (workspace && visible(workspace) ? workspace : null);
    target?.focus();
  }, [mobileMenuOpen]);
  const [commandOpen, setCommandOpen] = useState(false);
  const commandReturnFocus = useRef<HTMLElement | null>(null);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const [activePage, setActivePage] = useState<AppStudioPage>(() => pageFromPath(window.location.pathname));
  const liveOperationalPage = isLiveOperationalPage(activePage as StudioPage) || activePage === "crmSubscriptions" || activePage === "projectMilestones" || activePage === "governedAssistant";

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    if (liveOperationalPage) return () => controller.abort();
    loadStudioOverview(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "The local Studio artifact could not be loaded.");
      });
    return () => controller.abort();
  }, [loadAttempt, liveOperationalPage]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        commandReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setCommandOpen(true);
        setOpenPanel(null);
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
        window.requestAnimationFrame(() => commandReturnFocus.current?.focus());
        setOpenPanel(null);
        setMobileMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const onPopState = () => setActivePage(pageFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (page: AppStudioPage) => {
    if (page !== activePage) window.history.pushState({}, "", pathForPage(page));
    setActivePage(page);
    setOpenPanel(null);
  };

  const cycleTheme = () => {
    const index = themes.indexOf(preferences.theme);
    preferences.setTheme(themes[(index + 1) % themes.length]);
  };

  const openCommandPalette = () => {
    commandReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setCommandOpen(true);
    setOpenPanel(null);
  };

  const closeCommandPalette = () => {
    setCommandOpen(false);
    window.requestAnimationFrame(() => commandReturnFocus.current?.focus());
  };

  return (
    <div ref={shell} className={`app-shell ${sidebarCollapsed ? "app-shell--collapsed" : ""}`} onFocusCapture={event => {
      const target = event.target;
      lastSidebarFocus.current = target instanceof HTMLElement && target.closest("aside.sidebar") ? target : null;
    }}>
      <a className="skip-link" href="#studio-workspace-content">{t("skipToMain")}</a>
      <Sidebar
        translate={t}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileMenuOpen}
        onCollapse={() => setSidebarCollapsed((current) => !current)}
        onMobileClose={() => setMobileMenuOpen(false)}
        activePage={activePage}
        onNavigate={navigate}
        canView={access.canView}
      />
      {mobileMenuOpen ? <button className="mobile-scrim" type="button" onClick={() => setMobileMenuOpen(false)} aria-label={t("closeDialog")} /> : null}

      <div className="workspace-area">
        <Topbar
          translate={t}
          locale={preferences.locale}
          theme={preferences.theme}
          openPanel={openPanel}
          onPanel={setOpenPanel}
          onLocale={() => preferences.setLocale(preferences.locale === "en" ? "ar" : "en")}
          onTheme={cycleTheme}
          onCommand={openCommandPalette}
          onMobileMenu={() => setMobileMenuOpen(true)}
          noticeCount={data?.notices.length ?? 0}
          activePage={activePage === "crmSubscriptions" ? "crmContracts" : activePage === "projectMilestones" ? "projectMilestoneBilling" : (activePage as StudioPage)}
          liveIdentity={liveOperationalPage ? auth.username || t("arSignedOut") : undefined}
        />

        <StudioSessionControls translate={t} workspaces={access.workspaces} onSignIn={() => navigate("adminAudit")} />

        {openPanel === "accessibility" ? (
          <AccessibilityPanel
            translate={t}
            accessibility={preferences.accessibility}
            density={preferences.density}
            theme={preferences.theme}
            onAccessibility={preferences.updateAccessibility}
            onDensity={preferences.setDensity}
            onTheme={preferences.setTheme}
          />
        ) : null}
        {openPanel === "notifications" && data && !liveOperationalPage ? <NoticesPanel notices={data.notices} translate={t} locale={preferences.locale} /> : null}
        {openPanel === "quick" && !liveOperationalPage ? <QuickPanel translate={t} onNavigate={navigate} /> : null}
        {openPanel === "profile" && !liveOperationalPage ? <ProfilePanel translate={t} /> : null}

        {access.loading && <p className="studio-access-state" role="status">{t("navLoading")}</p>}
        {access.error && <div className="studio-access-state" role="alert"><p>{t("navAccessError")}</p><button type="button" onClick={access.retry}>{t("navRetry")}</button></div>}
        {!access.loading && !access.error && !access.canView(activePage) && <section className="studio-access-state"><h1>{t("navAccessRestricted")}</h1><button type="button" onClick={() => navigate("adminAudit")}>{t("adminAudit")}</button></section>}
        <div id="studio-workspace-content" tabIndex={-1} className="studio-page-frame">
        <WorkspaceErrorBoundary key={activePage} locale={preferences.locale} onDashboard={() => navigate("dashboard")} onReload={() => window.location.reload()}>
        {access.canView(activePage) ? <>
        {activePage === "stockSales" ? <Suspense fallback={<LoadingView translate={t} />}><StockSalesPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "procurementPartial" ? <Suspense fallback={<LoadingView translate={t} />}><ProcurementPartialPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "financialReporting" ? <Suspense fallback={<LoadingView translate={t} />}><FinancialReportingPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "fixedAssets" ? <Suspense fallback={<LoadingView translate={t} />}><FixedAssetsPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "customerReturns" ? <Suspense fallback={<LoadingView translate={t} />}><CustomerReturnsPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "operationalFxTax" ? <Suspense fallback={<LoadingView translate={t} />}><OperationalFxTaxPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "manufacturingExecution" ? <Suspense fallback={<LoadingView translate={t} />}><ManufacturingExecutionPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "intercompanyOperations" ? <Suspense fallback={<LoadingView translate={t} />}><IntercompanyOperationsPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "manufacturingExecutionV2" ? <Suspense fallback={<LoadingView translate={t} />}><ManufacturingExecutionV2Page locale={preferences.locale} /></Suspense> : null}
        {activePage === "intercompanyFx" ? <Suspense fallback={<LoadingView translate={t} />}><IntercompanyFxPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "groupDiagnostic" ? <Suspense fallback={<LoadingView translate={t} />}><GroupDiagnosticPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "intercompanyCashflow" ? <Suspense fallback={<LoadingView translate={t} />}><IntercompanyCashflowPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "projectSourceReconciliation" ? <Suspense fallback={<LoadingView translate={t} />}><ProjectSourceReconciliationPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "peopleProjectPayroll" ? <Suspense fallback={<LoadingView translate={t} />}><PeopleProjectPayrollPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "projectTimeBilling" ? <Suspense fallback={<LoadingView translate={t} />}><ProjectTimeBillingPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "accrualDeferral" ? <Suspense fallback={<LoadingView translate={t} />}><AccrualDeferralPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "manufacturingSupplyPlan" ? <Suspense fallback={<LoadingView translate={t} />}><ManufacturingSupplyPlanPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "inventoryTransfer" ? <Suspense fallback={<LoadingView translate={t} />}><InventoryTransferPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "procurementSourcing" ? <Suspense fallback={<LoadingView translate={t} />}><ProcurementSourcingPage locale={preferences.locale} /></Suspense> : null}
        {activePage === "dashboard" && error ? <ErrorView translate={t} message={error} onRetry={() => setLoadAttempt((attempt) => attempt + 1)} /> : null}
        {activePage === "dashboard" && !error && !data ? <LoadingView translate={t} /> : null}
        {activePage === "dashboard" && data ? (
          <Suspense fallback={<LoadingView translate={t} />}>
            <Dashboard data={data} locale={preferences.locale} translate={t} colorSafe={preferences.accessibility.colorSafe} onNavigate={navigate} />
          </Suspense>
        ) : null}
        {activePage === "exceptions" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ExceptionQueue locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "evidence" ? (
          <Suspense fallback={<LoadingView translate={t} />}><EvidenceBinder locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "inventory" ? (
          <Suspense fallback={<LoadingView translate={t} />}><InventoryControl translate={t} /></Suspense>
        ) : null}
        {activePage === "retailSettlement" ? (
          <Suspense fallback={<LoadingView translate={t} />}><RetailSettlementStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "bankStatement" ? (
          <Suspense fallback={<LoadingView translate={t} />}><BankStatementStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "manufacturingCost" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ManufacturingCostStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "professionalInvoicePayment" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ProfessionalInvoicePaymentStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "individualCashflow" ? (
          <Suspense fallback={<LoadingView translate={t} />}><IndividualCashflowStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "mapping" ? (
          <Suspense fallback={<LoadingView translate={t} />}><MappingStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "rules" ? (
          <Suspense fallback={<LoadingView translate={t} />}><RuleStudio locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "live" ? (
          <Suspense fallback={<LoadingView translate={t} />}><LiveStudio locale={preferences.locale} translate={t} onSignIn={() => navigate("adminAudit")} /></Suspense>
        ) : null}
        {activePage === "adminAudit" ? (
          <Suspense fallback={<LoadingView translate={t} />}><AdminAudit locale={preferences.locale} translate={t} /></Suspense>
        ) : null}
        {activePage === "notifications" ? (
          <Suspense fallback={<LoadingView translate={t} />}><NotificationInbox locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "receivables" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ReceivablesWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "budgetControl" ? (
          <Suspense fallback={<LoadingView translate={t} />}><BudgetControlWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "inventoryReceipt" ? (
          <Suspense fallback={<LoadingView translate={t} />}><InventoryReceiptPosting locale={preferences.locale} /></Suspense>
        ) : null}

        {activePage === "salesRevenue" ? (
          <Suspense fallback={<LoadingView translate={t} />}><SalesRevenueWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "procurementOperations" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ProcurementWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "enterpriseFinance" ? (
          <Suspense fallback={<LoadingView translate={t} />}><EnterpriseFinanceWorkspace locale={preferences.locale} shellIdentity /></Suspense>
        ) : null}
        {activePage === "durableJobs" ? (
          <Suspense fallback={<LoadingView translate={t} />}><JobOperationsWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "consolidatedStatements" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ConsolidatedStatementsPage locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "masterProductionSchedule" ? (
          <Suspense fallback={<LoadingView translate={t} />}><MasterProductionSchedulePage locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "shopFloorTraceability" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ShopFloorTraceabilityPage locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "crmSubscriptions" || (activePage as string) === "crmContracts" ? (
          <Suspense fallback={<LoadingView translate={t} />}><CrmSubscriptionWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "hcmLeave" ? (
          <Suspense fallback={<LoadingView translate={t} />}><HcmLeaveWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {(activePage as string) === "governedAssistant" ? (
          <Suspense fallback={<LoadingView translate={t} />}><GovernedAssistantWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        {activePage === "projectMilestones" || (activePage as string) === "projectMilestoneBilling" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ProjectMilestoneWorkspace locale={preferences.locale} /></Suspense>
        ) : null}
        </> : null}
        </WorkspaceErrorBoundary>
        </div>
      </div>

      <MobileDock
        canView={access.canView}
        translate={t}
        onMenu={() => setMobileMenuOpen(true)}
        onQuickAction={() => setOpenPanel(openPanel === "quick" ? null : "quick")}
        activePage={activePage}
        onNavigate={navigate}
      />
      {commandOpen ? <CommandPalette translate={t} onClose={closeCommandPalette} onNavigate={navigate} canView={access.canView} /> : null}
    </div>
  );
}
