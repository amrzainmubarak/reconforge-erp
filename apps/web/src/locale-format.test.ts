import { describe, expect, it } from "vitest";

import { formatCount, formatDate, formatExactDecimal, formatMetricValue } from "./locale-format";

const english = "en";
const arabic = "ar";

describe("locale-format", () => {
  it.each([
    ["9007199254740993", "9,007,199,254,740,993", "٩٬٠٠٧٬١٩٩٬٢٥٤٬٧٤٠٬٩٩٣"],
    ["1234.123456789012345678900", "1,234.123456789012345678900", "١٬٢٣٤٫١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨٩٠٠"],
    ["-1234.05000000", "-1,234.05000000", "\u061c-١٬٢٣٤٫٠٥٠٠٠٠٠٠"],
    ["0", "0", "٠"],
    ["0.00000000", "0.00000000", "٠٫٠٠٠٠٠٠٠٠"],
    ["-0", "-0", "\u061c-٠"],
    ["-0.00", "-0.00", "\u061c-٠٫٠٠"],
    ["0.0000000000000000000100", "0.0000000000000000000100", "٠٫٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠١٠٠"],
  ])("localizes exact decimal %s without changing its digits or scale", (input, en, ar) => {
    expect(formatExactDecimal(input, english)).toBe(en);
    expect(formatExactDecimal(input, arabic)).toBe(ar);
  });

  it("preserves integers beyond floating-point range and fractions beyond Intl precision limits", () => {
    const input = `1${"0".repeat(400)}.${"1234567890".repeat(16)}00`;
    expect(formatExactDecimal(input, english)).toBe(`10${",000".repeat(133)}.${"1234567890".repeat(16)}00`);
    expect(formatExactDecimal(input, arabic)).toBe(`١٠${"٬٠٠٠".repeat(133)}٫${"١٢٣٤٥٦٧٨٩٠".repeat(16)}٠٠`);
  });

  it.each(["", "NaN", "Infinity", "-Infinity", "1e3", "+1", "01", "1.", ".1", " 1.00 ", "1\n"])("rejects noncanonical decimal %j rather than coercing it", (input) => {
    expect(() => formatExactDecimal(input, english)).toThrow(RangeError);
  });

  it("formats percent values according to locale percent options", () => {
    expect(formatMetricValue(40, "percent", english)).toBe("40%");
    expect(formatMetricValue(66.67, "percent", english)).toBe("66.7%");
    expect(formatMetricValue(66.67, "percent", arabic)).toBe(
      new Intl.NumberFormat("ar-EG", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(0.6667),
    );
  });

  it("formats counts and days with locale-specific numerals", () => {
    expect(formatCount(1200, english)).toBe("1,200");
    expect(formatCount(1200, arabic)).toBe(new Intl.NumberFormat("ar-EG").format(1200));
    expect(formatMetricValue(13.5, "days", english)).toBe("13.5d");
    expect(formatMetricValue(13.5, "days", arabic)).toBe(`${new Intl.NumberFormat("ar-EG", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(13.5)}d`);
  });

  it("uses locale date tags while staying deterministic with UTC input", () => {
    const periodStart = "2026-06-01T00:00:00Z";
    expect(formatDate(periodStart, english)).toBe(new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      timeZone: "UTC",
    }).format(new Date(periodStart)));
    expect(formatDate(periodStart, arabic)).toBe(new Intl.DateTimeFormat("ar-EG", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      timeZone: "UTC",
    }).format(new Date(periodStart)));
  });
});
