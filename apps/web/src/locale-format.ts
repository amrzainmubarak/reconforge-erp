import type { Locale } from "./types";

export const localeFormatProfiles = {
  en: { numberLocale: "en-US", dateLocale: "en-CA" },
  ar: { numberLocale: "ar-EG", dateLocale: "ar-EG" },
} as const;

type MetricValueFormat = "percent" | "count" | "days";

export function formatCount(value: number, locale: Locale): string {
  return new Intl.NumberFormat(localeFormatProfiles[locale].numberLocale).format(value);
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
