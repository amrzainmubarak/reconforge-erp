import { describe, expect, it } from "vitest";

import { formatCount, formatDate, formatMetricValue } from "./locale-format";

const english = "en";
const arabic = "ar";

describe("locale-format", () => {
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
