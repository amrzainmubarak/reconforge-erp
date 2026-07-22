import { Check, Command, MoonStar, Search, Sun, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { MessageKey } from "../i18n";
import type { AccessibilityPreferences, Density, StudioPage, ThemePreference } from "../types";
import { navigationGroups } from "./Navigation";

interface AccessibilityPanelProps {
  translate: (key: MessageKey) => string;
  accessibility: AccessibilityPreferences;
  density: Density;
  theme: ThemePreference;
  onAccessibility: (key: keyof AccessibilityPreferences, value: boolean) => void;
  onDensity: (density: Density) => void;
  onTheme: (theme: ThemePreference) => void;
}

export function AccessibilityPanel({
  translate,
  accessibility,
  density,
  theme,
  onAccessibility,
  onDensity,
  onTheme,
}: AccessibilityPanelProps) {
  const toggles: Array<[keyof AccessibilityPreferences, MessageKey]> = [
    ["largerText", "largerText"],
    ["highContrast", "highContrast"],
    ["colorSafe", "colorSafe"],
    ["reducedMotion", "reducedMotion"],
    ["focusOutlines", "focusOutlines"],
  ];
  return (
    <section className="floating-panel accessibility-panel" aria-label={translate("accessibility")}>
      <div className="floating-panel-header">
        <strong>{translate("accessibility")}</strong>
        <span>WCAG</span>
      </div>

      <fieldset className="segmented-field">
        <legend>{translate("theme")}</legend>
        <div className="segmented-control">
          {(["light", "dark", "system"] as const).map((choice) => (
            <button
              className={theme === choice ? "is-selected" : ""}
              type="button"
              onClick={() => onTheme(choice)}
              aria-pressed={theme === choice}
              key={choice}
            >
              {choice === "dark" ? <MoonStar size={14} /> : <Sun size={14} />}
              {translate(choice)}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="segmented-field">
        <legend>{translate("density")}</legend>
        <div className="segmented-control segmented-control--two">
          {(["comfortable", "compact"] as const).map((choice) => (
            <button
              className={density === choice ? "is-selected" : ""}
              type="button"
              onClick={() => onDensity(choice)}
              aria-pressed={density === choice}
              key={choice}
            >
              {translate(choice)}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="toggle-list">
        {toggles.map(([key, label]) => (
          <label className="toggle-row" key={key}>
            <span>{translate(label)}</span>
            <input
              type="checkbox"
              checked={accessibility[key]}
              onChange={(event) => onAccessibility(key, event.currentTarget.checked)}
            />
            <span className="toggle-track" aria-hidden="true"><Check size={12} /></span>
          </label>
        ))}
      </div>
    </section>
  );
}

interface CommandPaletteProps {
  translate: (key: MessageKey) => string;
  onClose: () => void;
  onNavigate: (page: StudioPage) => void;
}

export function CommandPalette({ translate, onClose, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const commands = useMemo(
    () =>
      navigationGroups.flatMap((group) =>
        group.items.map((item) => ({
          ...item,
          group: translate(group.label),
          translatedLabel: translate(item.label),
        })),
      ),
    [translate],
  );
  const filtered = commands.filter((command) =>
    `${command.translatedLabel} ${command.group}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="command-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={translate("commandPalette")}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="command-search-row">
          <Search size={19} aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={translate("search")}
            aria-label={translate("search")}
          />
          <button className="icon-button" type="button" onClick={onClose} aria-label={translate("closeDialog")}>
            <X size={17} />
          </button>
        </div>
        <div className="command-results">
          {filtered.length ? (
            filtered.map((item) => {
              const Icon = item.icon;
              const content = (
                <>
                  <span className="command-icon"><Icon size={17} /></span>
                  <span>
                    <strong>{item.translatedLabel}</strong>
                    <small>{item.group}</small>
                  </span>
                  <span className={`command-status command-status--${item.status ?? "active"}`}>
                    {item.status ? translate(item.status) : translate("dashboard")}
                  </span>
                </>
              );
              if (item.page) {
                return (
                  <button className="command-row" type="button" onClick={() => { onNavigate(item.page as StudioPage); onClose(); }} key={item.key}>
                    {content}
                  </button>
                );
              }
              if (item.href) {
                return (
                  <a className="command-row" href={item.href} target="_blank" rel="noreferrer" onClick={onClose} key={item.key}>
                    {content}
                  </a>
                );
              }
              return (
                <div className="command-row command-row--disabled" aria-disabled="true" key={item.key}>
                  {content}
                </div>
              );
            })
          ) : (
            <div className="command-empty">
              <Command size={22} />
              <p>{translate("commandEmpty")}</p>
            </div>
          )}
        </div>
        <footer className="command-footer">
          <span><kbd>Tab</kbd> {translate("moveFocus")}</span>
          <span><kbd>Esc</kbd> {translate("closeDialog")}</span>
        </footer>
      </section>
    </div>
  );
}
