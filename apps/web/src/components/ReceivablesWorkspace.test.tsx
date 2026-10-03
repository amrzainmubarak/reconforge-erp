import { policyFor } from "../receivables-test-fixtures";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { ReceivablesWorkspace } from "./ReceivablesWorkspace";
import type { Locale } from "../types";

const customer = { id: "cus-1", customer_code: "CUS-1", name: "Synthetic customer", currency_code: "USD", monetary_policy: policyFor(), status: "Active", credit_hold: false };
const invoice = { id: "inv-1", customer_id: "cus-1", invoice_number: "INV-1", invoice_date: "2026-10-03", due_date: "2026-10-31", currency_code: "USD", monetary_policy: policyFor(), status: "Draft", created_by: "maker-id", approved_by: null, row_version: 1, subtotal_minor: 1251, tax_minor: 125, total_minor: 1376, outstanding_minor: 1376, lines: [{ description: "Synthetic service", quantity: "1.25", unit_price_minor: 1001, line_total_minor: 1251, tax_minor: 125 }] };
const identity = { id: "maker-id", username: "maker", permissions: ["receivables.manage", "receivables.approve"], principal_type: "user", authorized_scopes: { workspaces: ["workspace-a", "workspace-b"] } };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function SessionControls() {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin({ tenantId: "tenant-a", csrfToken: "proof-a", expiresAt: new Date(Date.now() + 60_000).toISOString() }, "maker", auth.revision)}>Session A</button><button onClick={() => auth.begin({ tenantId: "tenant-b", csrfToken: "proof-b", expiresAt: new Date(Date.now() + 60_000).toISOString() }, "checker", auth.revision)}>Session B</button><button onClick={() => auth.elevate(new Date(Date.now() + 30_000).toISOString(), auth.revision)}>Elevate test session</button></>;
}
function setup(fetcher: typeof fetch, locale: Locale = "en") {
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><SessionControls /><ReceivablesWorkspace locale={locale} /></BrowserSessionProvider>);
}
function routes(path: RequestInfo | URL) {
  const url = String(path);
  if (url.endsWith("/auth/me")) return response(identity);
  if (url.includes("/customers?")) return response({ customers: [customer], pagination: { total: 1 } });
  return response({ invoices: [], pagination: { total: 0 } });
}
async function enterWorkspace() {
  fireEvent.click(screen.getByText("Session A"));
  fireEvent.change(await screen.findByLabelText("Authorized workspace"), { target: { value: "workspace-a" } });
  await screen.findByRole("option", { name: /CUS-1/ });
}
function fillDraft() {
  for (const [label, value] of Object.entries({ Customer: "cus-1", "Invoice number": "INV-1", "Invoice date": "2026-10-03", "Due date": "2026-10-31", "Line description": "Synthetic service", Quantity: "1.25", "Unit price · USD": "10.01", "Line tax · USD": "1.25" })) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

test("real draft request, submitted version and creator separation are presented from responses", async () => {
  let saved: typeof invoice | null = null;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (options?.method === "POST") { saved = String(path).endsWith("/submit") ? { ...invoice, status: "Submitted", row_version: 2 } : invoice; return response(saved); }
    if (String(path).includes("/invoices?")) return response({ invoices: saved ? [saved] : [], pagination: { total: saved ? 1 : 0 } });
    return routes(path);
  });
  setup(fetcher); await enterWorkspace(); fillDraft();
  expect(screen.getByText(/13.76 USD/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByRole("button", { name: "Submit for review" });
  const create = fetcher.mock.calls.find(([, options]) => options?.method === "POST");
  expect(JSON.parse(String(create?.[1]?.body))).toMatchObject({ lines: [{ quantity: "1.25", unit_price_minor: 1001, line_total_minor: 1251, tax_minor: 125 }], tax_minor: 125 });
  fireEvent.click(screen.getByRole("button", { name: "Submit for review" }));
  await screen.findByText("A different person must approve this invoice.");
  expect(screen.queryByRole("button", { name: "Approve invoice" })).not.toBeInTheDocument();
  expect(JSON.parse(String(fetcher.mock.calls.find(([path]) => String(path).endsWith("/submit"))?.[1]?.body))).toEqual({ expected_version: 1 });
});

test("unknown draft outcome freezes one key and payload for an explicit exact retry", async () => {
  let calls = 0;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => { if (options?.method === "POST") { calls++; if (calls === 1) throw new TypeError("network"); return response(invoice); } return routes(path); });
  setup(fetcher); await enterWorkspace(); fillDraft();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByRole("button", { name: "Retry the exact request" });
  expect(calls).toBe(1);
  expect(screen.getByLabelText("Invoice number")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry the exact request" }));
  await screen.findByRole("button", { name: "Submit for review" });
  const writes = fetcher.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(2); expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
});

test("double click sends one mutation while a request is pending", async () => {
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>((done) => { resolve = done; });
  const fetcher = vi.fn((path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? pending : Promise.resolve(routes(path)));
  setup(fetcher); await enterWorkspace(); fillDraft();
  const button = screen.getByRole("button", { name: "Save draft" }); fireEvent.click(button); fireEvent.click(button);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  await act(async () => resolve(response(invoice)));
});

test("an independent authorized human reviews and explicitly confirms approval", async () => {
  const submitted = { ...invoice, status: "Submitted", row_version: 2 };
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return response({ ...identity, id: "checker-id", username: "checker", permissions: ["receivables.approve"] });
    if (options?.method === "POST") return response({ ...submitted, status: "Approved", row_version: 3, approved_by: "checker-id" });
    if (String(path).includes("/invoices?")) return response({ invoices: [submitted], pagination: { total: 1 } });
    return routes(path);
  });
  setup(fetcher); fireEvent.click(screen.getByText("Session A"));
  fireEvent.change(await screen.findByLabelText("Authorized workspace"), { target: { value: "workspace-a" } });
  fireEvent.click(await screen.findByRole("button", { name: "Review INV-1" }));
  expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve invoice" }));
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
  await screen.findByText(/server confirmed/);
  expect(JSON.parse(String(fetcher.mock.calls.find(([, options]) => options?.method === "POST")?.[1]?.body))).toEqual({ expected_version: 2 });
});

test("ordinary validation rejection retains draft input without inventing success", async () => {
  setup(vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? response({ error: { code: "receivables_request_invalid" } }, 400) : routes(path)));
  await enterWorkspace(); fillDraft(); fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByText(/server rejected/);
  expect(screen.getByLabelText("Invoice number")).toHaveValue("INV-1");
  expect(screen.getByLabelText("Invoice number")).not.toBeDisabled();
  expect(screen.queryByText(/server confirmed/)).not.toBeInTheDocument();
});

test("reviewing an existing invoice collapses the new invoice form without losing an unsaved draft", async () => {
  setup(vi.fn(async (path: RequestInfo | URL) => String(path).includes("/invoices?") ? response({ invoices: [invoice], pagination: { total: 1 } }) : routes(path)));
  await enterWorkspace(); fillDraft();
  const summary = screen.getByText("New invoice");
  expect(summary.closest("details")).toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Review INV-1" }));
  await waitFor(() => expect(summary.closest("details")).not.toHaveAttribute("open"));
  expect(screen.getByLabelText("Invoice number")).not.toBeVisible();
  fireEvent.click(summary);
  await waitFor(() => expect(screen.getByLabelText("Invoice number")).toBeVisible());
  expect(screen.getByLabelText("Invoice number")).toHaveValue("INV-1");
});

test("an unknown cash request survives parent refresh and invoice creation controls", async () => {
  const approved = { ...invoice, status: "Approved", row_version: 3, approved_by: "checker" };
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    const url = String(path);
    if (options?.method === "POST") throw new TypeError("Receipt outcome unknown");
    if (url.includes("/invoices?")) return response({ invoices: [approved], pagination: { total: 1 } });
    if (url.includes("/invoices/")) return response(approved);
    if (url.includes("/customers/")) return response(customer);
    if (url.includes("/receipts?")) return response({ receipts: [], pagination: { total: 0 } });
    if (url.includes("/credit-exposure/")) return response({ customer_id: customer.id, currency_code: "USD", exposure_minor: 1376 });
    return routes(path);
  });
  setup(fetcher); fireEvent.click(screen.getByText("Session A")); fireEvent.click(screen.getByText("Elevate test session"));
  fireEvent.change(await screen.findByLabelText("Authorized workspace"), { target: { value: "workspace-a" } });
  fireEvent.click(await screen.findByRole("button", { name: "Review INV-1" }));
  const cash = within(screen.getByRole("region", { name: "Cash receipts and allocations" }));
  await cash.findByLabelText("Receipt number");
  for (const [label, value] of Object.entries({ "Receipt number": "RCPT-UNKNOWN", "Receipt date": "2026-10-03", "Received amount · USD": "10.00", "Apply now to this invoice · USD": "4.00" })) fireEvent.change(cash.getByLabelText(label), { target: { value } });
  fireEvent.click(cash.getByRole("button", { name: "Review cash action" })); fireEvent.click(cash.getByRole("button", { name: "Confirm financial action" }));
  await cash.findByRole("button", { name: "Retry the exact request" });
  expect(screen.getByRole("button", { name: "Refresh records" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Review INV-1" })).toBeDisabled();
  fireEvent.click(screen.getByText("New invoice"));
  expect(screen.getByLabelText("Invoice number")).toBeDisabled();
  expect(await screen.findByRole("button", { name: "Save draft" })).toBeDisabled();
  expect(cash.getByRole("button", { name: "Retry the exact request" })).toBeVisible();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});

test("workspace switch discards drafts and late mutation success", async () => {
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>((done) => { resolve = done; });
  setup(vi.fn((path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? pending : Promise.resolve(routes(path))));
  await enterWorkspace(); fillDraft(); fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  fireEvent.change(screen.getByLabelText("Authorized workspace"), { target: { value: "workspace-b" } });
  await screen.findByRole("option", { name: /CUS-1/ });
  await act(async () => resolve(response(invoice)));
  expect(screen.getByLabelText("Invoice number")).toHaveValue("");
  expect(screen.queryByRole("region", { name: "Invoice review" })).not.toBeInTheDocument();
  expect(screen.queryByText(/server confirmed/)).not.toBeInTheDocument();
});

test("session expiry drops financial state and never replays a failed mutation", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? response({ error: { code: "invalid_token" } }, 401) : routes(path));
  setup(fetcher); await enterWorkspace(); fillDraft(); fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByRole("heading", { name: "Sign in" });
  expect(screen.queryByLabelText("Invoice number")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});

test("tenant switch ignores a stale identity response and clears private forms", async () => {
  let resolve!: (value: Response) => void;
  const first = new Promise<Response>((done) => { resolve = done; });
  const fetcher = vi.fn((path: RequestInfo | URL, options?: RequestInit) => new Headers(options?.headers).get("X-ReconForge-Tenant") === "tenant-a" ? first : Promise.resolve(routes(path)));
  setup(fetcher); fireEvent.click(screen.getByText("Session A")); fireEvent.click(screen.getByText("Session B"));
  await screen.findByLabelText("Authorized workspace");
  await act(async () => resolve(response({ ...identity, authorized_scopes: { workspaces: ["secret-workspace"] } })));
  expect(screen.queryByRole("option", { name: "secret-workspace" })).not.toBeInTheDocument();
  expect(screen.getByText("tenant-b")).toBeVisible();
});

test("Arabic view has RTL, labeled controls and no fabricated records", async () => {
  setup(vi.fn(async (path: RequestInfo | URL) => routes(path)), "ar");
  expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password");
  fireEvent.click(screen.getByText("Session A"));
  fireEvent.change(await screen.findByLabelText("مساحة العمل المصرح بها"), { target: { value: "workspace-a" } });
  await waitFor(() => expect(within(screen.getByRole("main")).getByText("لا يوجد فواتير في هذه الصفحة.")).toBeVisible());
  expect(screen.getByLabelText("الكمية")).toHaveAttribute("inputmode", "decimal");
  const table = screen.getByRole("region", { name: "جدول الفواتير" });
  expect(table).toHaveAttribute("tabindex", "0");
  expect(table).toHaveAttribute("aria-describedby", "ar-table-instructions");
  table.focus();
  expect(table).toHaveFocus();
});

test.each([["en", "JPY", 0, "1234", "1,234 JPY"], ["ar", "KWD", 3, "١٫٢٣٤", "١٫٢٣٤ KWD"]] as const)("%s invoice input uses retained %s precision and exact transport", async (locale, currency, precision, entered, displayed) => {
  const scopedCustomer = { ...customer, currency_code: currency, monetary_policy: policyFor(currency, precision) };
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (options?.method === "POST") return response({ error: { code: "synthetic_validation" } }, 400);
    if (String(path).includes("/customers?")) return response({ customers: [scopedCustomer], pagination: { total: 1 } });
    return routes(path);
  });
  setup(fetcher, locale); fireEvent.click(screen.getByText("Session A"));
  fireEvent.change(await screen.findByLabelText(locale === "ar" ? "مساحة العمل المصرح بها" : "Authorized workspace"), { target: { value: "workspace-a" } });
  await screen.findByRole("option", { name: /CUS-1/ });
  fireEvent.change(screen.getByLabelText(locale === "ar" ? "العميل" : "Customer"), { target: { value: "cus-1" } });
  const price = screen.getByLabelText(`${locale === "ar" ? "سعر الوحدة" : "Unit price"} · ${currency}`);
  expect(price).toHaveAttribute("inputmode", "decimal"); expect(price).toHaveAttribute("aria-describedby", "ar-minor-note");
  price.focus(); expect(price).toHaveFocus(); fireEvent.change(price, { target: { value: entered } });
  expect(screen.getAllByText(displayed).length).toBeGreaterThan(0);
  fireEvent.submit(price.closest("form")!);
  await waitFor(() => expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1));
  const body = JSON.parse(String(fetcher.mock.calls.find(([, options]) => options?.method === "POST")?.[1]?.body));
  expect(body.lines[0]).toMatchObject({ unit_price_minor: 1234, line_total_minor: 1234, tax_minor: 0 });
  expect(body).not.toHaveProperty("monetary_policy");
});

test("older API monetary metadata absence keeps historical raw reads but disables new effects", async () => {
  const oldCustomer = { ...customer, monetary_policy: undefined }, oldInvoice = { ...invoice, monetary_policy: undefined };
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (options?.method === "POST") throw new Error("Unexpected mutation");
    if (String(path).includes("/customers?")) return response({ customers: [oldCustomer], pagination: { total: 1 } });
    if (String(path).includes("/invoices?")) return response({ invoices: [oldInvoice], pagination: { total: 1 } });
    return routes(path);
  });
  setup(fetcher); await enterWorkspace();
  fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "cus-1" } });
  expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  expect(screen.getByLabelText("Unit price · USD")).toBeDisabled();
  expect(screen.getByText(/Historical currency precision is unverified/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Review INV-1" }));
  expect(screen.getAllByText("1,376 USD · minor units").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
});
