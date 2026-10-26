import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "./browserSession";
import { canViewPage, useNavigationAccess } from "./navigation-access";
import { pageFromPath, pathForPage } from "./studio-routes";
import { navigationGroups } from "./components/Navigation";

afterEach(() => vi.unstubAllGlobals());
const session = { tenantId: "SYN-TENANT", csrfToken: "SYN-CSRF", expiresAt: "2099-01-01T00:00:00Z" };
function Probe() {
  const auth = useBrowserSession(), access = useNavigationAccess();
  return <><button onClick={() => auth.begin(session, "synthetic-user", auth.revision)}>Login</button><button onClick={() => auth.clear(auth.revision)}>Logout</button><button onClick={access.retry}>Retry</button><output aria-label="Access">{JSON.stringify({ loading: access.loading, error: access.error, permissions: access.permissions, crm: access.canView("crmSubscriptions") })}</output></>;
}
const state = () => JSON.parse(screen.getByLabelText("Access").textContent!);

it("preserves all 53 unique destinations in eight groups and round-trips every internal route", () => {
  expect(navigationGroups).toHaveLength(8);
  const items = navigationGroups.flatMap(group => group.items);
  expect(items).toHaveLength(53);
  expect(new Set(items.map(item => item.key)).size).toBe(53);
  for (const item of items) if (item.page) expect(pageFromPath(pathForPage(item.page))).toBe(item.page);
  expect(pageFromPath("/erp")).toBe("enterpriseFinance");
  expect(pageFromPath("/crm-contracts")).toBe("crmSubscriptions");
  expect(pageFromPath("/project-milestone-billing")).toBe("projectMilestones");
});

it("never infers permission from a role name or pending capability response", () => {
  expect(canViewPage("crmSubscriptions", null)).toBe(false);
  expect(canViewPage("crmSubscriptions", ["admin", "sales_rep"])).toBe(false);
  expect(canViewPage("crmSubscriptions", ["sales.manage"])).toBe(true);
  expect(canViewPage("adminAudit", [])).toBe(true);
  expect(canViewPage("procurementOperations", ["finance_core.read"])).toBe(false);
  expect(canViewPage("procurementOperations", ["finance_core.read", "inventory.read", "payables.read"])).toBe(true);
  expect(canViewPage("projectMilestones", ["finance_core.read"])).toBe(false);
  expect(canViewPage("projectMilestones", ["project_time_billing.read"])).toBe(true);
});

it("loads fresh server permissions using same-origin cookie identity and no CSRF disclosure", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ permissions: ["sales.manage"], roles: ["untrusted-label"] })));
  vi.stubGlobal("fetch", fetcher); render(<Probe />, { wrapper: BrowserSessionProvider });
  fireEvent.click(screen.getByText("Login"));
  await waitFor(() => expect(state().crm).toBe(true));
  expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/me", expect.objectContaining({ credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-ReconForge-Tenant": "SYN-TENANT" } }));
  expect(state().permissions).toEqual(["sales.manage"]);
});

it.each([new Response("unavailable", { status: 503 }), new Response(JSON.stringify({ permissions: [true] })), new Response(JSON.stringify({ roles: ["admin"] }))])("fails closed on unavailable or invalid permissions %#", async response => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response)); render(<Probe />, { wrapper: BrowserSessionProvider });
  fireEvent.click(screen.getByText("Login"));
  await waitFor(() => expect(state().error).toBe(true));
  expect(state().crm).toBe(false);
});

it("ignores delayed permissions after logout and prevents old identity permissions entering a successor session", async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; })).mockResolvedValueOnce(new Response(JSON.stringify({ permissions: [] }))));
  render(<Probe />, { wrapper: BrowserSessionProvider }); fireEvent.click(screen.getByText("Login"));
  expect(state().crm).toBe(false); fireEvent.click(screen.getByText("Logout")); fireEvent.click(screen.getByText("Login"));
  await waitFor(() => expect(state().loading).toBe(false));
  await act(async () => complete(new Response(JSON.stringify({ permissions: ["sales.manage"] }))));
  expect(state().permissions).toEqual([]); expect(state().crm).toBe(false);
});

it("recovers through an explicit retry without retaining failed permissions", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(new Response(JSON.stringify({ permissions: ["sales.manage"] }))));
  render(<Probe />, { wrapper: BrowserSessionProvider }); fireEvent.click(screen.getByText("Login"));
  await waitFor(() => expect(state().error).toBe(true)); fireEvent.click(screen.getByText("Retry"));
  expect(state().crm).toBe(false); await waitFor(() => expect(state().crm).toBe(true));
});
