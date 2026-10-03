import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { ReceivablesCash } from "./ReceivablesCash";
import type { Locale } from "../types";

const invoice = { id: "inv", customer_id: "cus", invoice_number: "INV", invoice_date: "2026-10-03", due_date: "2026-10-03", currency_code: "USD", status: "Approved", created_by: "maker", approved_by: "checker", row_version: 3, subtotal_minor: 1376, tax_minor: 0, total_minor: 1376, outstanding_minor: 1376, lines: [{ description: "Synthetic", quantity: "1", unit_price_minor: 1376, line_total_minor: 1376, tax_minor: 0 }] };
const customer = { id: "cus", customer_code: "CUS", name: "Synthetic", currency_code: "USD", status: "Active", credit_hold: false };
const receipt = { id: "rct", customer_id: "cus", receipt_number: "RCT", receipt_date: "2026-10-03", currency_code: "USD", amount_minor: 1000, allocated_minor: 400, unallocated_minor: 600, row_version: 1, status: "Posted", allocations: [{ invoice_id: "inv", amount_minor: 400 }] };
const identity = { id: "cashier", username: "cashier", permissions: ["receivables.manage"], human: true, workspaces: ["work"] };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const deny = vi.fn(), changed = vi.fn(), locked = vi.fn();
function Harness({ locale = "en", human = true }: { locale?: Locale; human?: boolean }) {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin({ tenantId: "tenant", csrfToken: "csrf", expiresAt: new Date(Date.now() + 60_000).toISOString() }, "cashier", auth.revision)}>Session</button><button onClick={() => auth.elevate(new Date(Date.now() + 30_000).toISOString(), auth.revision)}>Elevate</button><button onClick={() => auth.clear(auth.revision)}>Expire</button>{auth.session ? <ReceivablesCash key={auth.revision} invoiceId="inv" workspace="work" identity={{ ...identity, human }} locale={locale} onAccessRefresh={deny} onChanged={changed} onLockChange={locked} /> : null}</>;
}
function reads(path: string, currentReceipt = receipt) {
  if (path.includes("/customers/")) return response(customer);
  if (path.includes("/invoices/")) return response(invoice);
  if (path.includes("/credit-exposure/")) return response({ customer_id: "cus", currency_code: "USD", exposure_minor: 1376 });
  if (path.includes("/receipts?")) return response({ receipts: [currentReceipt], pagination: { total: 1 } });
  return response(currentReceipt);
}
async function setup(fetcher: typeof fetch, human = true) {
  vi.stubGlobal("fetch", fetcher); render(<BrowserSessionProvider><Harness human={human} /></BrowserSessionProvider>);
  fireEvent.click(screen.getByText("Session")); fireEvent.click(screen.getByText("Elevate"));
  await screen.findByText(/Synthetic/);
}
function fill() {
  for (const [label, value] of Object.entries({ "Receipt number": "RCT", "Receipt date": "2026-10-03", "Received amount · minor units": "1000", "Apply now to this invoice · minor units": "400" })) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
test("receipt requires explicit review; unknown outcome freezes exact payload/key and reads current record after retry", async () => {
  let calls = 0;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => { if (options?.method === "POST") { if (++calls === 1) throw new TypeError("lost"); return response(receipt); } return reads(String(path)); });
  await setup(fetcher); fill(); fireEvent.click(screen.getByRole("button", { name: "Review cash action" }));
  expect(calls).toBe(0); expect(screen.getByRole("region", { name: "Review cash action" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Confirm financial action" }));
  await screen.findByRole("button", { name: "Retry the exact request" });
  expect(calls).toBe(1); expect(screen.getByLabelText("Receipt number")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry the exact request" }));
  await screen.findByText(/server confirmed the cash action/);
  const writes = fetcher.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(2); expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
  expect(writes[0][1]).toMatchObject({ credentials: "same-origin", headers: expect.objectContaining({ "X-ReconForge-Tenant": "tenant", "X-ReconForge-Workspace": "work", "X-ReconForge-CSRF": "csrf" }) });
});
test("unknown allocation performs GET recovery, requires acknowledgement and never retries the mutation", async () => {
  let allocated = false;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => { if (options?.method === "POST") { allocated = true; throw new TypeError("lost after commit"); } return reads(String(path), allocated ? { ...receipt, row_version: 2, allocated_minor: 600, unallocated_minor: 400, allocations: [{ invoice_id: "inv", amount_minor: 600 }] } : receipt); });
  await setup(fetcher);
  fireEvent.change(screen.getByLabelText("Select a recorded receipt"), { target: { value: "rct" } }); fireEvent.click(screen.getByRole("button", { name: "Read receipt" }));
  const input = await screen.findByLabelText("Additional allocation · minor units"); fireEvent.change(input, { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: "Review allocation" })); fireEvent.click(screen.getByRole("button", { name: "Confirm financial action" }));
  fireEvent.click(await screen.findByRole("button", { name: "Refresh authoritative receipt and invoice" }));
  await screen.findByRole("button", { name: "Use these current balances" });
  expect(screen.queryByText(/server confirmed the cash action/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("Additional allocation · minor units")).toBeDisabled();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});
test("three unknown receipt attempts stop further retries", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => { if (options?.method === "POST") throw new TypeError("unknown"); return reads(String(path)); });
  await setup(fetcher); fill(); fireEvent.click(screen.getByRole("button", { name: "Review cash action" })); fireEvent.click(screen.getByRole("button", { name: "Confirm financial action" }));
  for (let index = 0; index < 2; index++) fireEvent.click(await screen.findByRole("button", { name: "Retry the exact request" }));
  await screen.findByText(/Three attempts reached/);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(3);
  expect(screen.queryByRole("button", { name: "Retry the exact request" })).not.toBeInTheDocument();
});
test("permission denial clears private records and refreshes effective access", async () => {
  deny.mockClear();
  await setup(vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? response({ error: { code: "permission_denied" } }, 403) : reads(String(path))));
  fill(); fireEvent.click(screen.getByRole("button", { name: "Review cash action" })); fireEvent.click(screen.getByRole("button", { name: "Confirm financial action" }));
  await waitFor(() => expect(deny).toHaveBeenCalledOnce()); expect(screen.queryByText(/Synthetic/)).not.toBeInTheDocument();
});
test("a late mutation response after session expiry cannot restore private data or success", async () => {
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>((done) => { resolve = done; });
  await setup(vi.fn((path: RequestInfo | URL, options?: RequestInit) => options?.method === "POST" ? pending : Promise.resolve(reads(String(path)))));
  fill(); fireEvent.click(screen.getByRole("button", { name: "Review cash action" })); fireEvent.click(screen.getByRole("button", { name: "Confirm financial action" })); fireEvent.click(screen.getByText("Expire"));
  await act(async () => resolve(response(receipt)));
  expect(screen.queryByText(/Synthetic|server confirmed the cash action/)).not.toBeInTheDocument();
});
test("service identity has read-only cash UI", async () => {
  await setup(vi.fn(async (path: RequestInfo | URL) => reads(String(path))), false);
  expect(screen.getByText(/require an authorized human/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Review cash action" })).not.toBeInTheDocument();
});

test("receipt evidence identity is disclosed on demand while balances remain visible", async () => {
  await setup(vi.fn(async (path: RequestInfo | URL) => reads(String(path))));
  fireEvent.change(screen.getByLabelText("Select a recorded receipt"), { target: { value: "rct" } });
  fireEvent.click(screen.getByRole("button", { name: "Read receipt" }));
  const summary = await screen.findByText("Evidence details");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("rct")).not.toBeVisible();
  expect(screen.getByLabelText("Additional allocation · minor units")).toBeVisible();
  fireEvent.click(summary);
  await waitFor(() => expect(screen.getByText("rct")).toBeVisible());
});
