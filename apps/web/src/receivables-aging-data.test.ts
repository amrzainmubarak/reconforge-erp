import { describe, expect, it, vi } from "vitest";
import { loadArAging, parseArAging } from "./receivables-data";

export const agingFixture = () => ({ schema_version: 1, as_of_date: "2026-11-15", currency_groups: [{ currency_code: "USD", items: [{ invoice_id: "inv", invoice_number: "INV", customer_code: "CUS", customer_name: "Synthetic", currency_code: "USD", invoice_date: "2026-10-03", due_date: "2026-10-31", total_minor: 10000, outstanding_minor: 3500, days_overdue: 15, bucket: "1-30" }], bucket_totals_minor: { Current: 0, "1-30": 3500, "31-60": 0, "61-90": 0, "90+": 0 }, total_outstanding_minor: 3500 }] });

describe("closed native receivables aging", () => {
  it("retains the actual credit-adjusted residual and admits exact empty reports", () => {
    const value = agingFixture(); expect(parseArAging(value, "2026-11-15")).toEqual(value);
    expect(parseArAging({ schema_version: 1, as_of_date: "2026-11-15", currency_groups: [] }, "2026-11-15").currency_groups).toEqual([]);
  });
  it.each(["extra-top", "extra-group", "extra-item", "extra-bucket", "currency", "duplicate-invoice", "duplicate-currency", "group-order", "total", "bucket-total", "bucket", "days", "zero-item", "negative", "fractional", "boolean", "unsafe", "NaN", "Infinity", "stale-date", "calendar", "missing"])("refuses %s without zero substitution", field => {
    const value = agingFixture(), group = value.currency_groups[0], item = group.items[0];
    if (field === "extra-top") Object.assign(value, { raw_source: {} });
    if (field === "extra-group") Object.assign(group, { private_data: "unexpected" });
    if (field === "extra-item") Object.assign(item, { organization_id: "foreign" });
    if (field === "extra-bucket") Object.assign(group.bucket_totals_minor, { Unknown: 0 });
    if (field === "currency") item.currency_code = "EUR";
    if (field === "duplicate-invoice") group.items.push({ ...item });
    if (field === "duplicate-currency") value.currency_groups.push(structuredClone(group));
    if (field === "group-order") value.currency_groups.push({ ...structuredClone(group), currency_code: "EUR" });
    if (field === "total") ++group.total_outstanding_minor;
    if (field === "bucket-total") ++group.bucket_totals_minor.Current;
    if (field === "bucket") item.bucket = "Current";
    if (field === "days") ++item.days_overdue;
    if (field === "zero-item") item.outstanding_minor = 0;
    if (field === "negative") item.outstanding_minor = -1;
    if (field === "fractional") item.outstanding_minor = 0.5;
    if (field === "boolean") Object.assign(item, { outstanding_minor: true });
    if (field === "unsafe") item.outstanding_minor = 9007199254740992;
    if (field === "NaN") item.outstanding_minor = NaN;
    if (field === "Infinity") item.outstanding_minor = Infinity;
    if (field === "stale-date") value.as_of_date = "2026-11-14";
    if (field === "calendar") item.due_date = "2026-02-30";
    if (field === "missing") Reflect.deleteProperty(item, "outstanding_minor");
    expect(() => parseArAging(value, "2026-11-15")).toThrow("ar_contract_invalid");
  });
  it("keeps currencies separate and checks exact sums at the safe transport boundary", () => {
    const value = agingFixture(), group = value.currency_groups[0];
    group.items[0].total_minor = group.items[0].outstanding_minor = group.total_outstanding_minor = group.bucket_totals_minor["1-30"] = Number.MAX_SAFE_INTEGER;
    const eur = structuredClone(group); eur.currency_code = eur.items[0].currency_code = "EUR"; eur.items[0].invoice_id = "other";
    value.currency_groups.unshift(eur);
    expect(parseArAging(value, "2026-11-15").currency_groups).toHaveLength(2);
  });
  it("uses an explicit same-origin GET with the current workspace and rejects invalid dates before transport", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(agingFixture()))); vi.stubGlobal("fetch", fetcher);
    try {
      const session = { tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
      await loadArAging(session, "work", "2026-11-15");
      expect(fetcher).toHaveBeenCalledWith("/api/v1/receivables/aging-by-currency?as_of_date=2026-11-15", expect.objectContaining({ method: "GET", credentials: "same-origin", cache: "no-store", headers: expect.objectContaining({ "X-ReconForge-Tenant": "tenant", "X-ReconForge-Workspace": "work" }) }));
      await expect(loadArAging(session, "work", "2026-02-30")).rejects.toThrow("ar_contract_invalid"); expect(fetcher).toHaveBeenCalledOnce();
    } finally { vi.unstubAllGlobals(); }
  });
});
