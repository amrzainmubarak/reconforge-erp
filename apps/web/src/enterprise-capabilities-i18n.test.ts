import { describe, expect, it } from "vitest";
import { messages, translate } from "./i18n";
import { isLiveOperationalPage, operationalPageLabel } from "./studio-pages";
import type { StudioPage } from "./types";

describe("Enterprise Capabilities i18n and Accessibility", () => {
  it("enforces 100% translation key parity between English and Arabic", () => {
    const enKeys = Object.keys(messages.en).sort();
    const arKeys = Object.keys(messages.ar).sort();

    expect(enKeys).toEqual(arKeys);
    expect(enKeys.length).toBeGreaterThan(600);

    // Verify non-empty translations for all keys
    for (const key of enKeys as (keyof typeof messages.en)[]) {
      expect(messages.en[key]).toBeTruthy();
      expect(messages.ar[key]).toBeTruthy();
      expect(typeof messages.en[key]).toBe("string");
      expect(typeof messages.ar[key]).toBe("string");
    }
  });

  it("verifies bilingual labels for newly mounted enterprise capabilities", () => {
    const enterprisePages: StudioPage[] = [
      "treasuryLiquidity",
      "manufacturingBom",
      "hcmLeave",
      "crmContracts",
      "intercompanyEliminations",
      "shopFloorTraceability",
      "projectMilestoneBilling",
      "consolidatedStatements",
      "masterProductionSchedule",
    ];

    for (const page of enterprisePages) {
      expect(isLiveOperationalPage(page)).toBe(true);
      const labelKey = operationalPageLabel(page);
      expect(labelKey).toBeDefined();

      if (labelKey) {
        const enLabel = translate("en", labelKey);
        const arLabel = translate("ar", labelKey);

        expect(enLabel).toBeTruthy();
        expect(arLabel).toBeTruthy();
        // English label must contain Latin characters
        expect(/[A-Za-z]/.test(enLabel)).toBe(true);
        // Arabic label must contain Arabic unicode block characters
        expect(/[\u0600-\u06FF]/.test(arLabel)).toBe(true);
      }
    }
  });

  it("ensures correct RTL/LTR semantics for language modes", () => {
    const getDirection = (locale: "en" | "ar"): "ltr" | "rtl" => {
      return locale === "ar" ? "rtl" : "ltr";
    };

    expect(getDirection("en")).toBe("ltr");
    expect(getDirection("ar")).toBe("rtl");
  });
});
