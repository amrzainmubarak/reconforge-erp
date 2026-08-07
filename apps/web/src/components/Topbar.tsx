import {
  Bell,
  Check,
  ChevronDown,
  CircleUserRound,
  Command,
  Menu,
  MoonStar,
  Plus,
  Search,
  SlidersHorizontal,
  Sun,
} from "lucide-react";

import type { MessageKey } from "../i18n";
import type { Locale, StudioPage, ThemePreference } from "../types";

export type OpenPanel = "notifications" | "quick" | "profile" | "accessibility" | null;

const pageLabels: Record<StudioPage, MessageKey> = {
  dashboard: "dashboard",
  exceptions: "exceptions",
  evidence: "evidence",
  inventory: "inventory",
  retailSettlement: "retailSettlement",
  mapping: "mappingStudio",
  rules: "ruleStudio",
  live: "liveStudio",
  adminAudit: "adminAudit",
};

interface TopbarProps {
  translate: (key: MessageKey) => string;
  locale: Locale;
  theme: ThemePreference;
  openPanel: OpenPanel;
  onPanel: (panel: OpenPanel) => void;
  onLocale: () => void;
  onTheme: () => void;
  onCommand: () => void;
  onMobileMenu: () => void;
  noticeCount: number;
  activePage: StudioPage;
}

export function Topbar({
  translate,
  locale,
  theme,
  openPanel,
  onPanel,
  onLocale,
  onTheme,
  onCommand,
  onMobileMenu,
  noticeCount,
  activePage,
}: TopbarProps) {
  return (
    <header className="topbar">
      <button className="icon-button mobile-menu-button" type="button" onClick={onMobileMenu} aria-label={translate("menu")}>
        <Menu size={20} />
      </button>
      <div className="breadcrumbs" aria-label={translate("breadcrumb")}>
        <span>{translate(activePage === "dashboard" ? "overview" : activePage === "inventory" ? "operations" : activePage === "mapping" || activePage === "rules" || activePage === "live" || activePage === "adminAudit" ? "platform" : "finance")}</span>
        <span aria-hidden="true">/</span>
        <strong>{translate(pageLabels[activePage])}</strong>
      </div>

      <button className="global-search" type="button" onClick={onCommand} aria-haspopup="dialog" aria-label={translate("search")}>
        <Search size={17} aria-hidden="true" />
        <span>{translate("search")}</span>
        <kbd>
          <Command size={12} aria-hidden="true" /> K
        </kbd>
      </button>

      <div className="topbar-actions">
        <button className="locale-button" type="button" data-testid="locale-toggle" onClick={onLocale} aria-label={translate("switchLanguage")}>
          {locale === "en" ? "AR" : "EN"}
        </button>
        <button className="icon-button" type="button" onClick={onTheme} aria-label={`${translate("theme")}: ${translate(theme)}`}>
          {theme === "dark" ? <MoonStar size={18} /> : <Sun size={18} />}
        </button>
        <div className="panel-anchor">
          <button
            className="icon-button"
            type="button"
            onClick={() => onPanel(openPanel === "accessibility" ? null : "accessibility")}
            aria-label={translate("accessibility")}
            aria-expanded={openPanel === "accessibility"}
          >
            <SlidersHorizontal size={18} />
          </button>
        </div>
        <div className="panel-anchor topbar-optional">
          <button
            className="icon-button notification-button"
            type="button"
            onClick={() => onPanel(openPanel === "notifications" ? null : "notifications")}
            aria-label={translate("notifications")}
            aria-expanded={openPanel === "notifications"}
          >
            <Bell size={18} />
            {noticeCount ? <span className="notification-count">{noticeCount}</span> : null}
          </button>
        </div>
        <div className="panel-anchor topbar-optional">
          <button
            className="quick-button"
            type="button"
            onClick={() => onPanel(openPanel === "quick" ? null : "quick")}
            aria-expanded={openPanel === "quick"}
          >
            <Plus size={17} />
            <span>{translate("quickCreate")}</span>
          </button>
        </div>
        <div className="panel-anchor">
          <button
            className="profile-button"
            type="button"
            onClick={() => onPanel(openPanel === "profile" ? null : "profile")}
            aria-label={translate("profile")}
            aria-expanded={openPanel === "profile"}
          >
            <span className="profile-avatar">FC</span>
            <span className="profile-copy topbar-optional">
              <strong>Finance Controller</strong>
              <small>{translate("readOnly")}</small>
            </span>
            <ChevronDown size={14} className="topbar-optional" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  );
}

interface NoticesPanelProps {
  notices: string[];
  translate: (key: MessageKey) => string;
}

export function NoticesPanel({ notices, translate }: NoticesPanelProps) {
  return (
    <section className="floating-panel notification-panel" aria-label={translate("notifications")}>
      <div className="floating-panel-header">
        <strong>{translate("notifications")}</strong>
        <span>{notices.length}</span>
      </div>
      {notices.map((notice) => (
        <div className="notice-row" key={notice}>
          <span className="notice-icon"><Check size={14} /></span>
          <div>
            <strong>{notice}</strong>
            <small>{translate("generated")}</small>
          </div>
        </div>
      ))}
    </section>
  );
}

export function QuickPanel({ translate, onNavigate }: { translate: (key: MessageKey) => string; onNavigate: (page: StudioPage) => void }) {
  const currentStudio = import.meta.env.VITE_CURRENT_STUDIO_URL ?? "http://127.0.0.1:8601";
  const actions = [
    { label: translate("reconciliation"), href: `${currentStudio}/reconciliation` },
    { label: translate("exceptions"), page: "exceptions" as const },
    { label: translate("import"), href: `${currentStudio}/validation` },
  ];
  return (
    <section className="floating-panel quick-panel" aria-label={translate("quickCreate")}>
      <div className="floating-panel-header">
        <strong>{translate("quickCreate")}</strong>
        <span>{translate("foundation")}</span>
      </div>
      {actions.map((action) => {
        const content = <><Plus size={15} aria-hidden="true" /><span><strong>{action.label}</strong><small>{action.page ? translate("localContract") : translate("viewCurrent")}</small></span></>;
        return action.page ? (
          <button className="quick-action-row" type="button" onClick={() => onNavigate(action.page)} key={action.label}>{content}</button>
        ) : (
          <a className="quick-action-row" href={action.href} target="_blank" rel="noreferrer" key={action.href}>{content}</a>
        );
      })}
    </section>
  );
}

export function ProfilePanel({ translate }: { translate: (key: MessageKey) => string }) {
  return (
    <section className="floating-panel profile-panel" aria-label={translate("profile")}>
      <div className="profile-panel-identity">
        <CircleUserRound size={34} />
        <div>
          <strong>Finance Controller</strong>
          <small>{translate("local")}</small>
        </div>
      </div>
      <div className="profile-panel-row">
        <span>{translate("status")}</span>
        <strong>{translate("readOnly")}</strong>
      </div>
      <div className="profile-panel-row">
        <span>{translate("source")}</span>
        <strong>{translate("preview")}</strong>
      </div>
    </section>
  );
}
