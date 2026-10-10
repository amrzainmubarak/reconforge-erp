import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { commerceFixture } from "../stock-commerce-test-fixtures";
import { CommercialCollectionsPanel } from "./CommercialCollectionsPanel";

afterEach(() => vi.unstubAllGlobals());
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const session = { tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const identity = { id: "maker", human: true, stepUp: true, permissions: ["sales.manage", "sales.approve", "receivables.manage", "finance_core.manage", "finance_core.validate", "finance_core.post"], workspaces: ["work"], organizations: ["org"], entities: ["entity"] };
function tranche() { return { ...commerceFixture("Invoiced").lines[0].tranches[0], invoice_id: "invoice", invoice_status: "Approved", collected_minor: "0", outstanding_minor: "13500", receivable_account_code: "AR", pending_collection: null }; }
const props = { locale: "en" as const, session, scope, identity, options: null, disabled: false, onPendingChange: vi.fn(), onCommitted: vi.fn() };
it("requires a reviewer independent of preparation and a third poster", () => {
  const row = { ...tranche(), pending_collection: { id: "CA1-" + "a".repeat(32), plan_digest: "f".repeat(64), phase: 1 as const, amount_minor: "10000", preparer_actor_id: "maker", reviewer_actor_id: "checker" } };
  const view = render(<CommercialCollectionsPanel {...props} tranche={row} />);
  expect(screen.getByRole("button", { name: "Post invoice installment" })).toBeDisabled();
  view.rerender(<CommercialCollectionsPanel {...props} identity={{ ...identity, id: "checker" }} tranche={row} />);
  expect(screen.getByRole("button", { name: "Post invoice installment" })).toBeDisabled();
  view.rerender(<CommercialCollectionsPanel {...props} identity={{ ...identity, id: "poster" }} tranche={row} />);
  expect(screen.getByRole("button", { name: "Post invoice installment" })).toBeEnabled();
});
it("retries exactly the retained reviewed command after a lost committed response", async () => {
  const row = { ...tranche(), pending_collection: { id: "CA1-" + "a".repeat(32), plan_digest: "f".repeat(64), phase: 1 as const, amount_minor: "10000", preparer_actor_id: "maker", reviewer_actor_id: "checker" } };
  const attempts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    attempts.push(String(init?.body));
    if (attempts.length === 1) throw new TypeError("Synthetic lost ACK");
    return new Response(JSON.stringify({ plan: { ...scope, ...row.pending_collection, source_id: "invoice", allocated_before_minor: "0", status: "Posted", receipt_id: "receipt", posting_effect_id: "effect" } }), { headers: { "Content-Type": "application/json" } });
  }));
  render(<CommercialCollectionsPanel {...props} identity={{ ...identity, id: "poster" }} tranche={row} />);
  fireEvent.change(screen.getByLabelText("Collection reason"), { target: { value: "Retained three-person review" } });
  fireEvent.click(screen.getByRole("button", { name: "Post invoice installment" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry retained collection command" }));
  await waitFor(() => expect(attempts).toHaveLength(2));
  expect(attempts[0]).toBe(attempts[1]);
  await screen.findByText(/Native receipt and cash effect posted/);
});
it("renders Arabic RTL and retains exact invoice residual", () => {
  render(<CommercialCollectionsPanel {...props} locale="ar" tranche={{ ...tranche(), outstanding_minor: "9007199254740993" }} />);
  expect(screen.getByRole("region", { name: "تحصيل هذه الفاتورة على دفعات" })).toHaveAttribute("dir", "rtl");
  expect(screen.getByText("9007199254740993")).toBeInTheDocument();
});
