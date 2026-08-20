import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "./i18n";

const LOCALES = ["en", "ar"] as const;

describe("i18n locale parity", () => {
  it("keeps every locale dictionary key set aligned with English keys", () => {
    const enKeys = Object.keys(messages.en).sort();

    for (const locale of LOCALES) {
      const localeKeys = Object.keys(messages[locale]).sort();
      expect(localeKeys).toEqual(enKeys);
    }
  });

  it("returns non-empty strings for every defined locale key", () => {
    const enKeys = Object.keys(messages.en) as MessageKey[];

    for (const locale of LOCALES) {
      for (const key of enKeys) {
        const value = messages[locale][key];
        expect(typeof value).toBe("string");
        expect(value).not.toBe("");
        expect(value.trim().length).toBeGreaterThan(0);
      }
    }
  });
});
