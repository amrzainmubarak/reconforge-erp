import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { billingEvidenceFixture, billingPlanFixture } from "../project-time-billing-test-fixture";
import { ProjectTimeBillingPage } from "./ProjectTimeBillingPage";

const session = { tenantId: String((billingEvidenceFixture().qualified_scope as Record<string, unknown>).tenant_id), csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, username: "poster", isCurrent: () => true, recover: () => false }) }));
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn() }));
const identity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: ["project_time_billing.read", "project_time_billing.review", "project_time_billing.post", "finance_core.read", "finance_core.validate", "finance_core.post", "people_project_payroll.read", "receivables.read", "receivables.manage", "receivables.approve", "receivables.receive"] };
afterEach(() => { vi.unstubAllGlobals(); vi.mocked(loadBudgetIdentity).mockReset(); });
async function choose(plan: Record<string, unknown>, actor = identity) {
  vi.mocked(loadBudgetIdentity).mockResolvedValue(actor);
  vi.stubGlobal("fetch", vi.fn(async (url: unknown) => new Response(JSON.stringify(String(url).includes("/plans/") ? { plan } : String(url).includes("/evidence") ? { evidence: billingEvidenceFixture() } : String(url).includes("project-time-billing/catalog") ? { items: [{ id: plan.id }], prices: [], has_more: false, after: "" } : { items: [], has_more: false }))));
  render(<ProjectTimeBillingPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  const selector = screen.getByRole("combobox", { name: "Original source plan" });
  await waitFor(() => expect(selector.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(selector, { target: { value: plan.id } });
}
it("refuses corrupted native source before exposing posting", async () => {
  await choose({ ...billingPlanFixture(1), plan_digest: "0".repeat(64) });
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Publish source and native GL" })).not.toBeInTheDocument();
});
it("holds all financial actions until actual WebCrypto source verification completes", async () => {
  const digest = crypto.subtle.digest.bind(crypto.subtle);
  let release!: (value: ArrayBuffer) => void;
  vi.spyOn(crypto.subtle, "digest").mockImplementationOnce(async (...args) => {
    const real = await digest(...args);
    return new Promise<ArrayBuffer>(resolve => { release = () => resolve(real); });
  });
  await choose(billingPlanFixture(1));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(screen.queryByRole("button", { name: "Publish source and native GL" })).not.toBeInTheDocument();
  release(new ArrayBuffer(0));
  expect(await screen.findByRole("button", { name: "Publish source and native GL" })).toBeEnabled();
});
it("replays the exact lost posting command and requires native evidence before success", async () => {
  await choose(billingPlanFixture(1));
  await screen.findByRole("button", { name: "Publish source and native GL" });
  const requests: string[] = [], posted = billingPlanFixture(2);
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push(String(init.body)); if (requests.length === 1) throw new TypeError("Synthetic lost response"); return new Response(JSON.stringify({ plan: posted })); }
    return new Response(JSON.stringify(String(url).includes("/plans/") ? { plan: posted } : String(url).includes("/evidence") ? { evidence: billingEvidenceFixture() } : String(url).includes("project-time-billing/catalog") ? { items: [], prices: [], has_more: false, after: "" } : { items: [], has_more: false }));
  }));
  fireEvent.click(screen.getByRole("button", { name: "Publish source and native GL" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry exact command" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0]).toBe(requests[1]);
  await screen.findByText(/Posted with verified native effect/);
  expect(screen.getByText("62.36 USD")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry exact command" })).not.toBeInTheDocument();
});
it("retains the original pending command when a valid native ACK belongs to another source", async () => {
  const original = billingPlanFixture(1), other = billingPlanFixture(2, true);
  await choose(original);
  await screen.findByRole("button", { name: "Publish source and native GL" });
  const requests: { url: string; body: string }[] = [], reads: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push({ url: String(url), body: String(init.body) }); return new Response(JSON.stringify({ plan: other })); }
    reads.push(String(url));
    return new Response(JSON.stringify(String(url).includes("/evidence") ? { evidence: billingEvidenceFixture() } : { plan: other }));
  }));
  fireEvent.click(screen.getByRole("button", { name: "Publish source and native GL" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry exact command" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  await screen.findByRole("button", { name: "Retry exact command" });
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0].url).toBe(`/api/v1/project-time-billing/plans/${original.id}/post`);
  expect(JSON.parse(requests[0].body).expected_plan_digest).toBe(original.plan_digest);
  expect(reads).toEqual([]);
  expect(screen.queryByText(/Verified source saved/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Posted with verified native effect/)).not.toBeInTheDocument();
});
it("accepts the original review ACK followed by a legitimately advanced verified GET", async () => {
  const reviewed = billingPlanFixture(1), posted = billingPlanFixture(2);
  await choose(billingPlanFixture(0), { ...identity, id: "checker" });
  await screen.findByRole("button", { name: "Review exact original source" });
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => new Response(JSON.stringify(init?.method === "POST" ? { plan: reviewed } : String(url).includes("/plans/") ? { plan: posted } : String(url).includes("/evidence") ? { evidence: billingEvidenceFixture() } : { items: [], prices: [], has_more: false, after: "" }))));
  fireEvent.click(screen.getByRole("button", { name: "Review exact original source" }));
  await screen.findByText(/Posted with verified native effect/);
  expect(screen.queryByRole("button", { name: "Retry exact command" })).not.toBeInTheDocument();
});
it("hides financial source operations when independent Finance read is absent", async () => {
  vi.mocked(loadBudgetIdentity).mockResolvedValue({ ...identity, permissions: identity.permissions.filter(value => value !== "finance_core.read") });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [], prices: [], has_more: false }))));
  render(<ProjectTimeBillingPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  expect(screen.queryByRole("combobox", { name: "Original source plan" })).not.toBeInTheDocument();
});
it("renders RTL and explicitly states country tax support is zero", () => {
  vi.mocked(loadBudgetIdentity).mockResolvedValue(identity);
  const view = render(<ProjectTimeBillingPage locale="ar" />);
  expect(view.container.querySelector("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByText(/حزم ضريبة الدول: صفر/)).toBeInTheDocument();
});
