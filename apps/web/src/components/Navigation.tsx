import {
  Activity,
  Archive,
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
  PackageSearch,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ComponentType } from "react";

import type { MessageKey } from "../i18n";
import type { StudioPage } from "../types";

export interface NavigationItem {
  key: string;
  label: MessageKey;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" | "false" }>;
  href?: string;
  page?: StudioPage;
  status?: "foundation" | "planned";
}

export interface NavigationGroup {
  label: MessageKey;
  items: NavigationItem[];
}

const currentStudio = import.meta.env.VITE_CURRENT_STUDIO_URL ?? "http://127.0.0.1:8601";

export const navigationGroups: NavigationGroup[] = [
  {
    label: "overview",
    items: [{ key: "dashboard", label: "dashboard", icon: Gauge, page: "dashboard" }],
  },
  {
    label: "finance",
    items: [
      { key: "reconciliation", label: "reconciliation", icon: Activity, href: `${currentStudio}/reconciliation`, status: "foundation" },
      { key: "exceptions", label: "exceptions", icon: ShieldCheck, page: "exceptions", status: "foundation" },
      { key: "evidence", label: "evidence", icon: Archive, page: "evidence", status: "foundation" },
      { key: "close", label: "close", icon: ClipboardCheck, href: `${currentStudio}/close`, status: "foundation" },
      { key: "retail-settlement", label: "retailSettlement", icon: CreditCard, page: "retailSettlement", status: "foundation" },
    ],
  },
  {
    label: "operations",
    items: [
      { key: "inventory", label: "inventory", icon: Boxes, page: "inventory", status: "foundation" },
      { key: "manufacturing", label: "manufacturing", icon: Factory, href: `${currentStudio}/wip`, status: "foundation" },
    ],
  },
  {
    label: "platform",
    items: [
      { key: "reports", label: "reports", icon: FileChartColumn, href: `${currentStudio}/downloads`, status: "foundation" },
      { key: "packs", label: "packs", icon: PackageSearch, href: `${currentStudio}/control-packs`, status: "foundation" },
      { key: "mapping", label: "mappingStudio", icon: FileInput, page: "mapping", status: "foundation" },
      { key: "rules", label: "ruleStudio", icon: Code2, page: "rules", status: "foundation" },
      { key: "live", label: "liveStudio", icon: RadioTower, page: "live", status: "foundation" },
      { key: "admin-audit", label: "adminAudit", icon: ShieldCheck, page: "adminAudit", status: "foundation" },
      { key: "settings", label: "settings", icon: Settings, status: "planned" },
      { key: "developer", label: "developer", icon: Code2, href: `${currentStudio}/docs`, status: "foundation" },
    ],
  },
];

interface SidebarProps {
  translate: (key: MessageKey) => string;
  collapsed: boolean;
  mobileOpen: boolean;
  onCollapse: () => void;
  onMobileClose: () => void;
  activePage: StudioPage;
  onNavigate: (page: StudioPage) => void;
}

export function Sidebar({ translate, collapsed, mobileOpen, onCollapse, onMobileClose, activePage, onNavigate }: SidebarProps) {
  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""} ${mobileOpen ? "sidebar--mobile-open" : ""}`}>
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
            <strong>{translate("local")}</strong>
            <small>{translate("preview")}</small>
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

      <nav className="desktop-navigation" aria-label={translate("primaryNavigation")}>
        {navigationGroups.map((group) => (
          <div className="nav-group" key={group.label}>
            <p className="nav-group-label">{translate(group.label)}</p>
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
                    aria-current={activePage === item.page ? "page" : undefined}
                    key={item.key}
                    onClick={() => {
                      onNavigate(item.page as StudioPage);
                      onMobileClose();
                    }}
                  >
                    {content}
                  </button>
                );
              }
              if (item.href) {
                return (
                  <a className="nav-item" href={item.href} target="_blank" rel="noreferrer" key={item.key} onClick={onMobileClose}>
                    {content}
                  </a>
                );
              }
              return (
                <button className="nav-item" type="button" disabled key={item.key} title={translate("planned")}>
                  {content}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="local-state">
          <span className="status-dot" aria-hidden="true" />
          <span>
            <strong>{translate("readOnly")}</strong>
            <small>{translate("localNote")}</small>
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
  translate: (key: MessageKey) => string;
  onMenu: () => void;
  onQuickAction: () => void;
  activePage: StudioPage;
  onNavigate: (page: StudioPage) => void;
}

export function MobileDock({ translate, onMenu, onQuickAction, activePage, onNavigate }: MobileDockProps) {
  return (
    <nav className="mobile-dock" aria-label={translate("mobileNav")}>
      <button type="button" className={`mobile-dock-item ${activePage === "dashboard" ? "mobile-dock-item--active" : ""}`} onClick={() => onNavigate("dashboard")}>
        <Gauge size={20} aria-hidden="true" />
        <span>{translate("dashboard")}</span>
      </button>
      <button type="button" className={`mobile-dock-item ${activePage === "exceptions" ? "mobile-dock-item--active" : ""}`} onClick={() => onNavigate("exceptions")}>
        <ShieldCheck size={20} aria-hidden="true" />
        <span>{translate("exceptions")}</span>
      </button>
      <button type="button" className="mobile-create" onClick={onQuickAction} aria-label={translate("quickCreate")}>
        <Sparkles size={21} />
      </button>
      <a href={`${currentStudio}/close`} target="_blank" rel="noreferrer" className="mobile-dock-item">
        <ClipboardCheck size={20} aria-hidden="true" />
        <span>{translate("close")}</span>
      </a>
      <button type="button" className="mobile-dock-item" onClick={onMenu}>
        <PanelLeftOpen size={20} aria-hidden="true" />
        <span>{translate("menu")}</span>
      </button>
    </nav>
  );
}
