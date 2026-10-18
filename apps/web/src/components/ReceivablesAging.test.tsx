import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { policyFor } from "../receivables-test-fixtures";
import type { ArCustomer, ArInvoice } from "../receivables-data";
import type { Locale } from "../types";
import { ReceivablesAging } from "./ReceivablesAging";

const invoice: ArInvoice = { id: "inv", customer_id: "cus", invoice_number: "INV", invoice_date: "2026-10-03", due_date: "2026-10-31", currency_code: "USD", monetary_policy: policyFor(), status: "PartiallyPaid", created_by: "maker", approved_by: "checker", row_version: 3, subtotal_minor: 10000, tax_minor: 0, total_minor: 10000, outstanding_minor: 3500, lines: [{ description: "Synthetic", quantity: "1", unit_price_minor: 10000, line_total_minor: 10000, tax_minor: 0 }] };
const customer: ArCustomer = { id: "cus", customer_code: "CUS", name: "Synthetic", currency_code: "USD", monetary_policy: policyFor(), status: "Active", credit_hold: false };
const payload = () => ({ schema_version: 1, as_of_date: "2026-11-15", currency_groups: [{ currency_code: "USD", items: [{ invoice_id: "inv", invoice_number: "INV", customer_code: "CUS", customer_name: "Synthetic", currency_code: "USD", invoice_date: "2026-10-03", due_date: "2026-10-31", total_minor: 10000, outstanding_minor: 3500, days_overdue: 15, bucket: "1-30" }], bucket_totals_minor: { Current: 0, "1-30": 3500, "31-60": 0, "61-90": 0, "90+": 0 }, total_outstanding_minor: 3500 }] });
const denied = vi.fn();
function Harness({ locale = "en", workspace = "work", disabled = false, paid = false }: { locale?: Locale; workspace?: string; disabled?: boolean; paid?: boolean }) {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin({ tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, "reader", auth.revision)}>Session</button><button onClick={() => auth.clear(auth.revision)}>Expire</button>{auth.session && <ReceivablesAging invoice={paid ? { ...invoice, outstanding_minor: 0, status: "Paid" } : invoice} customer={customer} workspace={workspace} locale={locale} disabled={disabled} onDenied={denied} />}</>;
}
function start(locale: Locale = "en") {
  fireEvent.change(screen.getByLabelText(locale === "ar" ? "تاريخ احتساب أعمار الذمم" : "Aging as-of date"), { target: { value: "2026-11-15" } });
  fireEvent.click(screen.getByRole("button", { name: locale === "ar" ? "قراءة أعمار الذمم الحالية" : "Read current receivables aging" }));
}
test.each(["en", "ar"] as const)("%s reads only after a human action and displays exact native minor units", async locale => {
  const fetcher = vi.fn(async (_path: RequestInfo | URL, _options?: RequestInit) => new Response(JSON.stringify(payload()))); vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><Harness locale={locale} /></BrowserSessionProvider>); fireEvent.click(screen.getByText("Session")); expect(fetcher).not.toHaveBeenCalled(); start(locale);
  const result = await screen.findByRole("region", { name: locale === "ar" ? "نتيجة أعمار الذمم المصرح بها" : "Authorized receivables aging result" });
  expect(result).toHaveTextContent("3500 USD"); expect(result).toHaveTextContent("2026-11-15"); expect(result).toHaveTextContent("INV");
  expect(screen.getByRole("region", { name: locale === "ar" ? "أعمار الذمم المدينة في مساحة العمل" : "Workspace receivables aging" })).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
  expect(fetcher).toHaveBeenCalledOnce(); expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "GET" });
});
test("a paid invoice has an explicit empty state with no invented total", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ schema_version: 1, as_of_date: "2026-11-15", currency_groups: [] }))));
  render(<BrowserSessionProvider><Harness paid /></BrowserSessionProvider>); fireEvent.click(screen.getByText("Session")); start();
  expect(await screen.findByText("No approved open invoices were returned in this workspace.")).toBeVisible();
  expect(screen.queryByText(/3500/)).not.toBeInTheDocument();
});
test.each(["malformed", "wrong-selected-invoice", "gross", "invoice-date", "coherent-due-date", "denied"])("%s refuses the read and focuses a safe error", async kind => {
  denied.mockClear(); const value = payload(); if (kind === "malformed") ++value.currency_groups[0].total_outstanding_minor;
  if (kind === "wrong-selected-invoice") value.currency_groups[0].items[0].invoice_number = "OTHER";
  if (kind === "gross") ++value.currency_groups[0].items[0].total_minor;
  if (kind === "invoice-date") value.currency_groups[0].items[0].invoice_date = "2026-10-02";
  if (kind === "coherent-due-date") { value.currency_groups[0].items[0].due_date = "2026-10-30"; value.currency_groups[0].items[0].days_overdue = 16; }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(kind === "denied" ? { error: { code: "permission_denied", message: "PRIVATE" } } : value), { status: kind === "denied" ? 403 : 200 })));
  render(<BrowserSessionProvider><Harness /></BrowserSessionProvider>); fireEvent.click(screen.getByText("Session")); start();
  const alert = await screen.findByRole("alert");
  await waitFor(() => expect(alert).toHaveFocus());
  expect(alert).not.toHaveTextContent("PRIVATE"); expect(screen.queryByRole("region", { name: "Authorized receivables aging result" })).not.toBeInTheDocument();
  expect(denied).toHaveBeenCalledTimes(kind === "denied" ? 1 : 0);
});
test.each(["scope", "session", "financial-lock"])("a late response cannot restore data after %s changes", async kind => {
  let release!: (response: Response) => void;
  const fetcher = vi.fn((_path: RequestInfo | URL, _options?: RequestInit) => new Promise<Response>(resolve => { release = resolve; })); vi.stubGlobal("fetch", fetcher);
  const view = render(<BrowserSessionProvider><Harness /></BrowserSessionProvider>); fireEvent.click(screen.getByText("Session")); start();
  expect(await screen.findByRole("status")).toHaveTextContent("Loading authorized records");
  if (kind === "session") fireEvent.click(screen.getByText("Expire"));
  else view.rerender(<BrowserSessionProvider><Harness workspace={kind === "scope" ? "other" : "work"} disabled={kind === "financial-lock"} /></BrowserSessionProvider>);
  await act(async () => release(new Response(JSON.stringify(payload()))));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Authorized receivables aging result" })).not.toBeInTheDocument());
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
});
