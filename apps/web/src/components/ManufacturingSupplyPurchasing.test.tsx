import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import original from "../fixtures/manufacturing-supply-original-budget-read.json";
import originalPurchase from "../fixtures/manufacturing-supply-original-purchase-read.json";
import { parseSupplyPlan, supplyOperationPermissions } from "../manufacturing-supply-data";
import { ManufacturingSupplyPurchasing } from "./ManufacturingSupplyPurchasing";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, isCurrent: () => true }) }));
const identity = { id: "maker", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: [...new Set(Object.values(supplyOperationPermissions).flat())] };
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
afterEach(() => vi.unstubAllGlobals());

async function purchasing(budget: unknown = original.budget_detail, status = 200) {
  vi.stubGlobal("crypto", webcrypto);
  const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(budget), { status })); vi.stubGlobal("fetch", fetcher);
  const source = await parseSupplyPlan(original.source, scope), failure = vi.fn(), submit = vi.fn();
  render(<ManufacturingSupplyPurchasing locale="en" source={source} scope={scope} identity={identity} ready={true} submit={submit} onReadFailure={failure} />);
  return { fetcher, failure, submit, source };
}

it("enables real shortage sourcing when original native policy places the currency on the budget envelope", async () => {
  expect(original.origin_proof_sha256).toBe("9f49c6c5c523a0f0d7e65a457c727fc741bcec367cd3d6b98ce6098f90476590");
  expect(original.source.monetary_policy.currency_code).toBe("USD"); expect(original.budget_detail.monetary_policy).not.toHaveProperty("currency_code");
  const { fetcher, failure } = await purchasing();
  await waitFor(() => expect(screen.getByRole("button", { name: "Create exact shortage requisition" })).toBeEnabled());
  expect(screen.getByRole("textbox", { name: "Supplier code" })).toBeEnabled(); expect(failure).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][0]).toContain(`/api/v1/budget-control/envelopes/${original.source.budget_id}?`);
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "GET", headers: { "X-ReconForge-Tenant": "synthetic", "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" } });
});

it.each(["currency", "precision", "rounding", "registry_version", "registry_digest", "budget_id", "scope"])("refuses changed original budget binding %s before any native sourcing command", async change => {
  const budget = structuredClone(original.budget_detail);
  if (change === "currency") budget.currency_code = "EUR";
  if (change === "precision") budget.monetary_policy.precision = 3;
  if (change === "rounding") budget.monetary_policy.rounding_policy = "ROUND_HALF_EVEN";
  if (change === "registry_version") budget.monetary_policy.registry_version = "foreign-registry";
  if (change === "registry_digest") budget.monetary_policy.registry_digest = "0".repeat(64);
  if (change === "budget_id") budget.id = "BUD-FOREIGN";
  if (change === "scope") budget.legal_entity_id = "sibling";
  const { fetcher, failure, submit } = await purchasing(budget);
  await screen.findByText("Original purchase evidence is unavailable. Refresh before any command.");
  expect(screen.getByRole("textbox", { name: "Supplier code" })).toBeDisabled(); expect(failure).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledTimes(1); expect(submit).not.toHaveBeenCalled();
});

it.each([401, 403, 404])("keeps native sourcing disabled and propagates current budget read refusal %s", async status => {
  const { failure, submit } = await purchasing({ error: { code: "budget_scope_denied" } }, status);
  await screen.findByText("Original purchase evidence is unavailable. Refresh before any command.");
  expect(screen.getByRole("textbox", { name: "Supplier code" })).toBeDisabled(); expect(failure.mock.calls[0][0]).toMatchObject({ status });
  expect(submit).not.toHaveBeenCalled();
});

it("waits for delayed actual original purchase evidence then sends the selected nonfirst KG line and exact quantity", async () => {
  vi.stubGlobal("crypto", webcrypto); const failure = vi.fn(), submit = vi.fn();
  let release!: (value: Response) => void;
  const requested: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const path = String(url); requested.push(path);
    if (path.includes("/budget-control/")) return new Response(JSON.stringify(originalPurchase.budget_detail));
    if (path.includes("/requisitions/")) return new Response(JSON.stringify(originalPurchase.sourcing));
    return new Promise<Response>(resolve => { release = resolve; });
  }));
  const source = await parseSupplyPlan(originalPurchase.source, scope);
  render(<ManufacturingSupplyPurchasing locale="en" source={source} scope={scope} identity={identity} ready={true} submit={submit} onReadFailure={failure} />);
  await waitFor(() => expect(requested.some(path => path.includes("/purchases/"))).toBe(true));
  expect(screen.queryByRole("combobox", { name: "Original purchase line" })).not.toBeInTheDocument(); expect(submit).not.toHaveBeenCalled();
  await act(async () => release(new Response(JSON.stringify(originalPurchase.purchase))));
  const select = await screen.findByRole("combobox", { name: "Original purchase line" }); await waitFor(() => expect(select).toBeEnabled());
  const material = originalPurchase.purchase.lines.find(row => row.item_code === "MATERIAL")!;
  expect(material.quantity_precision).toBe(3); expect(material.quantity_text).toBe("2.500");
  fireEvent.change(select, { target: { value: material.id } }); expect(select).toHaveValue(material.id);
  const form = screen.getByRole("form", { name: "Prepare actual partial receipt" });
  for (const [name, value] of Object.entries({ "Exact received quantity": "2.500", "Receipt date": "2026-10-06", Reason: "Actual original selected mass receipt" })) fireEvent.change(within(form).getByLabelText(name), { target: { value } });
  fireEvent.click(within(form).getByRole("button", { name: "Prepare actual partial receipt" }));
  expect(failure).not.toHaveBeenCalled(); expect(submit).toHaveBeenCalledWith(expect.stringContaining(`/purchases/${originalPurchase.purchase.order.id}/receive-prepare`), expect.objectContaining({ line_id: material.id, quantity: "2.500", expected_version: originalPurchase.purchase.order.row_version }));
});
