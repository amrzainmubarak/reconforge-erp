import { useEffect, useState } from "react";

import type { AccessibilityPreferences, Density, Locale, ThemePreference } from "./types";

const defaultAccessibility: AccessibilityPreferences = {
  largerText: false,
  highContrast: false,
  colorSafe: false,
  reducedMotion: false,
  focusOutlines: true,
};

function readChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const value = window.localStorage.getItem(key);
  return value && allowed.includes(value as T) ? (value as T) : fallback;
}

function readAccessibility(): AccessibilityPreferences {
  const value = window.localStorage.getItem("reconforge.accessibility");
  if (!value) return defaultAccessibility;
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return defaultAccessibility;
    const candidate = parsed as Record<string, unknown>;
    return {
      largerText: typeof candidate.largerText === "boolean" ? candidate.largerText : defaultAccessibility.largerText,
      highContrast: typeof candidate.highContrast === "boolean" ? candidate.highContrast : defaultAccessibility.highContrast,
      colorSafe: typeof candidate.colorSafe === "boolean" ? candidate.colorSafe : defaultAccessibility.colorSafe,
      reducedMotion: typeof candidate.reducedMotion === "boolean" ? candidate.reducedMotion : defaultAccessibility.reducedMotion,
      focusOutlines: typeof candidate.focusOutlines === "boolean" ? candidate.focusOutlines : defaultAccessibility.focusOutlines,
    };
  } catch {
    return defaultAccessibility;
  }
}

export function usePreferences() {
  const [locale, setLocale] = useState<Locale>(() => readChoice("reconforge.locale", ["en", "ar"], "en"));
  const [theme, setTheme] = useState<ThemePreference>(() =>
    readChoice("reconforge.theme", ["light", "dark", "system"], "system"),
  );
  const [density, setDensity] = useState<Density>(() =>
    readChoice("reconforge.density", ["comfortable", "compact"], "comfortable"),
  );
  const [accessibility, setAccessibility] = useState<AccessibilityPreferences>(readAccessibility);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = locale === "ar" ? "rtl" : "ltr";
    root.dataset.theme = theme;
    root.dataset.density = density;
    root.dataset.largeText = String(accessibility.largerText);
    root.dataset.highContrast = String(accessibility.highContrast);
    root.dataset.colorSafe = String(accessibility.colorSafe);
    root.dataset.reducedMotion = String(accessibility.reducedMotion);
    root.dataset.focusOutlines = String(accessibility.focusOutlines);
    window.localStorage.setItem("reconforge.locale", locale);
    window.localStorage.setItem("reconforge.theme", theme);
    window.localStorage.setItem("reconforge.density", density);
    window.localStorage.setItem("reconforge.accessibility", JSON.stringify(accessibility));
  }, [accessibility, density, locale, theme]);

  const updateAccessibility = (key: keyof AccessibilityPreferences, value: boolean) => {
    setAccessibility((current) => ({ ...current, [key]: value }));
  };

  return {
    locale,
    setLocale,
    theme,
    setTheme,
    density,
    setDensity,
    accessibility,
    updateAccessibility,
  };
}
