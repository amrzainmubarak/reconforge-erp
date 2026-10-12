import type { Locale } from "./types";

export const localeFormatProfiles = {
  en: { numberLocale: "en-US", dateLocale: "en-CA" },
  ar: { numberLocale: "ar-EG", dateLocale: "ar-EG" },
} as const;

type MetricValueFormat = "percent" | "count" | "days";

export function formatCount(value: number, locale: Locale): string {
  return new Intl.NumberFormat(localeFormatProfiles[locale].numberLocale).format(value);
}

/** Localize canonical decimal text without rounding its magnitude or scale. */
export function formatExactDecimal(value: string, locale: Locale): string {
  if (value !== value.trim() || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) throw new RangeError("Expected canonical decimal text.");
  const negative = value.startsWith("-");
  const [integer, fraction] = (negative ? value.slice(1) : value).split(".");
  const formatter = new Intl.NumberFormat(localeFormatProfiles[locale].numberLocale);
  let magnitude = formatter.format(BigInt(integer));
  if (fraction !== undefined) {
    // These constants provide locale symbols; the source fraction stays text.
    const separator = formatter.formatToParts(0.1).find((part) => part.type === "decimal")!.value;
    const digits = Array.from({ length: 10 }, (_, digit) => formatter.format(digit));
    magnitude += separator + fraction.replace(/[0-9]/g, (digit) => digits[digit.charCodeAt(0) - 48]);
  }
  // A sign template preserves negative zero and locale bidi marks without float conversion.
  return formatter.formatToParts(negative ? -1n : 1n).map((part) => part.type === "integer" ? magnitude : part.value).join("");
}

export function formatMetricValue(value: number, format: MetricValueFormat, locale: Locale): string {
  const localeTag = localeFormatProfiles[locale].numberLocale;
  if (format === "percent") {
    const fractionDigits = Number.isInteger(value) ? 0 : 1;
    return new Intl.NumberFormat(localeTag, {
      style: "percent",
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value / 100);
  }
  if (format === "days") {
    return `${new Intl.NumberFormat(localeTag, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value)}d`;
  }
  return new Intl.NumberFormat(localeTag, { maximumFractionDigits: 0 }).format(value);
}

export function formatDate(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(localeFormatProfiles[locale].dateLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "UTC",
  }).format(value instanceof Date ? value : new Date(value));
}
