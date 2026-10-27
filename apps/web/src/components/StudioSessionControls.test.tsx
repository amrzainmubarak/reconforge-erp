import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { translate } from "../i18n";
import { StudioSessionControls } from "./StudioSessionControls";

afterEach(() => vi.unstubAllGlobals());
function Login() {
  const auth = useBrowserSession();
  return <button onClick={() => auth.begin({ tenantId: "synthetic-tenant", csrfToken: "synthetic-csrf", expiresAt: "2099-01-01T00:00:00Z" }, "synthetic-user-with-a-long-readable-identity", auth.revision)}>Begin session</button>;
}
function ready() { render(<><Login /><StudioSessionControls translate={key => translate("en", key)} workspaces={["synthetic-workspace"]} onSignIn={vi.fn()} /></>, { wrapper: BrowserSessionProvider }); fireEvent.click(screen.getByText("Begin session")); }

it("shows actual identity and authorized workspace IDs without implying selected business scope", () => {
  ready(); expect(screen.getByText("synthetic-user-with-a-long-readable-identity")).toBeInTheDocument();
  expect(screen.getByText("synthetic-tenant")).toBeInTheDocument();
  expect(screen.getByText("synthetic-workspace")).toBeInTheDocument();
  expect(screen.getByText("Select the business scope inside each workspace.")).toBeInTheDocument();
});

it("clears the browser identity only after confirmed server logout", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 })); vi.stubGlobal("fetch", fetcher); ready();
  fireEvent.click(screen.getByRole("button", { name: "Sign out of Studio" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign in to Studio" })).toBeInTheDocument());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/logout", expect.objectContaining({ method: "POST", credentials: "same-origin" }));
});

it("retains identity and offers retry when server logout cannot be confirmed", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline"))); ready();
  fireEvent.click(screen.getByRole("button", { name: "Sign out of Studio" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Sign out could not be confirmed"));
  expect(screen.getByText("synthetic-user-with-a-long-readable-identity")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign out of Studio" })).toBeEnabled();
});
