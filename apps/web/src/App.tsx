import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { MobileDock, Sidebar } from "./components/Navigation";
import { AccessibilityPanel, CommandPalette } from "./components/Overlays";
import { ErrorView, LoadingView } from "./components/StateViews";
import { NoticesPanel, ProfilePanel, QuickPanel, Topbar, type OpenPanel } from "./components/Topbar";
import { loadStudioOverview } from "./data";
import { translate, type MessageKey } from "./i18n";
import { usePreferences } from "./preferences";
import type { StudioOverview, StudioPage, ThemePreference } from "./types";

const themes: ThemePreference[] = ["system", "light", "dark"];
const Dashboard = lazy(() => import("./components/Dashboard").then((module) => ({ default: module.Dashboard })));
const ExceptionQueue = lazy(() => import("./components/ExceptionQueue").then((module) => ({ default: module.ExceptionQueue })));
const EvidenceBinder = lazy(() => import("./components/EvidenceBinder").then((module) => ({ default: module.EvidenceBinder })));
const InventoryControl = lazy(() => import("./components/InventoryControl").then((module) => ({ default: module.InventoryControl })));
const RetailSettlementStudio = lazy(() => import("./components/RetailSettlementStudio").then((module) => ({ default: module.RetailSettlementStudio })));
const BankStatementStudio = lazy(() => import("./components/BankStatementStudio").then((module) => ({ default: module.BankStatementStudio })));
const ManufacturingCostStudio = lazy(() => import("./components/ManufacturingCostStudio").then((module) => ({ default: module.ManufacturingCostStudio })));
const ProfessionalInvoicePaymentStudio = lazy(() => import("./components/ProfessionalInvoicePaymentStudio").then((module) => ({ default: module.ProfessionalInvoicePaymentStudio })));
const MappingStudio = lazy(() => import("./components/MappingStudio").then((module) => ({ default: module.MappingStudio })));
const RuleStudio = lazy(() => import("./components/RuleStudio").then((module) => ({ default: module.RuleStudio })));
const LiveStudio = lazy(() => import("./components/LiveStudio").then((module) => ({ default: module.LiveStudio })));
const AdminAudit = lazy(() => import("./components/AdminAudit").then((module) => ({ default: module.AdminAudit })));

function pageFromPath(pathname: string): StudioPage {
  const normalized = pathname.replace(/\/+$/, "");
  if (normalized.endsWith("/exceptions")) return "exceptions";
  if (normalized.endsWith("/evidence")) return "evidence";
  if (normalized.endsWith("/inventory")) return "inventory";
  if (normalized.endsWith("/retail-settlement")) return "retailSettlement";
  if (normalized.endsWith("/bank-statement")) return "bankStatement";
  if (normalized.endsWith("/manufacturing-cost")) return "manufacturingCost";
  if (normalized.endsWith("/professional-invoice-payment")) return "professionalInvoicePayment";
  if (normalized.endsWith("/mapping")) return "mapping";
  if (normalized.endsWith("/rules")) return "rules";
  if (normalized.endsWith("/live")) return "live";
  if (normalized.endsWith("/admin-audit")) return "adminAudit";
  return "dashboard";
}

function pathForPage(page: StudioPage): string {
  const base = import.meta.env.BASE_URL.replace(/\/+$/, "");
  const routeNames: Partial<Record<StudioPage, string>> = {
    retailSettlement: "retail-settlement",
    bankStatement: "bank-statement",
    manufacturingCost: "manufacturing-cost",
    professionalInvoicePayment: "professional-invoice-payment",
    adminAudit: "admin-audit",
  };
  return page === "dashboard" ? `${base}/` || "/" : `${base}/${routeNames[page] ?? page}`;
}

export default function App() {
  const preferences = usePreferences();
  const t = useCallback((key: MessageKey) => translate(preferences.locale, key), [preferences.locale]);
  const [data, setData] = useState<StudioOverview | null>(null);
  const [error, setError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const commandReturnFocus = useRef<HTMLElement | null>(null);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const [activePage, setActivePage] = useState<StudioPage>(() => pageFromPath(window.location.pathname));

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadStudioOverview(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "The local Studio artifact could not be loaded.");
      });
    return () => controller.abort();
  }, [loadAttempt]);

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

  const navigate = (page: StudioPage) => {
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
    <div className={`app-shell ${sidebarCollapsed ? "app-shell--collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Sidebar
        translate={t}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileMenuOpen}
        onCollapse={() => setSidebarCollapsed((current) => !current)}
        onMobileClose={() => setMobileMenuOpen(false)}
        activePage={activePage}
        onNavigate={navigate}
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
          activePage={activePage}
        />

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
        {openPanel === "notifications" && data ? <NoticesPanel notices={data.notices} translate={t} /> : null}
        {openPanel === "quick" ? <QuickPanel translate={t} onNavigate={navigate} /> : null}
        {openPanel === "profile" ? <ProfilePanel translate={t} /> : null}

        {activePage === "dashboard" && error ? <ErrorView translate={t} message={error} onRetry={() => setLoadAttempt((attempt) => attempt + 1)} /> : null}
        {activePage === "dashboard" && !error && !data ? <LoadingView translate={t} /> : null}
        {activePage === "dashboard" && data ? (
          <Suspense fallback={<LoadingView translate={t} />}>
            <Dashboard data={data} translate={t} colorSafe={preferences.accessibility.colorSafe} onNavigate={navigate} />
          </Suspense>
        ) : null}
        {activePage === "exceptions" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ExceptionQueue translate={t} /></Suspense>
        ) : null}
        {activePage === "evidence" ? (
          <Suspense fallback={<LoadingView translate={t} />}><EvidenceBinder translate={t} /></Suspense>
        ) : null}
        {activePage === "inventory" ? (
          <Suspense fallback={<LoadingView translate={t} />}><InventoryControl translate={t} /></Suspense>
        ) : null}
        {activePage === "retailSettlement" ? (
          <Suspense fallback={<LoadingView translate={t} />}><RetailSettlementStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "bankStatement" ? (
          <Suspense fallback={<LoadingView translate={t} />}><BankStatementStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "manufacturingCost" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ManufacturingCostStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "professionalInvoicePayment" ? (
          <Suspense fallback={<LoadingView translate={t} />}><ProfessionalInvoicePaymentStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "mapping" ? (
          <Suspense fallback={<LoadingView translate={t} />}><MappingStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "rules" ? (
          <Suspense fallback={<LoadingView translate={t} />}><RuleStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "live" ? (
          <Suspense fallback={<LoadingView translate={t} />}><LiveStudio translate={t} /></Suspense>
        ) : null}
        {activePage === "adminAudit" ? (
          <Suspense fallback={<LoadingView translate={t} />}><AdminAudit translate={t} /></Suspense>
        ) : null}
      </div>

      <MobileDock
        translate={t}
        onMenu={() => setMobileMenuOpen(true)}
        onQuickAction={() => setOpenPanel(openPanel === "quick" ? null : "quick")}
        activePage={activePage}
        onNavigate={navigate}
      />
      {commandOpen ? <CommandPalette translate={t} onClose={closeCommandPalette} onNavigate={navigate} /> : null}
    </div>
  );
}
