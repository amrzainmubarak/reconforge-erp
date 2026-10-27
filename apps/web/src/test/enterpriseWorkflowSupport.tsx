import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";

export const session = { tenantId: "synthetic-tenant", csrfToken: "synthetic-csrf", expiresAt: "2099-01-01T00:00:00Z" };
function SessionControls() {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin(session, "synthetic-reviewer", auth.revision)}>Start test session</button><button onClick={() => auth.clear(auth.revision)}>End test session</button></>;
}
export function renderWorkspace(element: ReactElement) { return render(<><SessionControls />{element}</>, { wrapper: BrowserSessionProvider }); }
export function setField(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
export function authorize() {
  fireEvent.click(screen.getByRole("button", { name: "Start test session" }));
  setField("Workspace ID", "synthetic-workspace"); setField("Organization ID", "synthetic-organization"); setField("Legal entity ID", "synthetic-entity");
}
export function respond(value: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value), { status }));
  vi.stubGlobal("fetch", fetcher); return fetcher;
}
export async function click(label: string) { await act(async () => fireEvent.click(screen.getByRole("button", { name: label }))); }
