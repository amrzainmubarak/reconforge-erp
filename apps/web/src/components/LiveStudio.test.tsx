import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { translate } from "../i18n";
import { LiveStudio } from "./LiveStudio";

const metric = { id: "m1", workspace_id: "w1", metric_key: "match_rate", period_name: "2026-07", value: 88, value_text: "88.00", lineage: "approved matches", computed_at: new Date().toISOString(), name: "Match rate", description: "Rate" };
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("renders loading then live exact metric and lineage", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(200, { metrics: [metric] })));
  render(<LiveStudio translate={(key) => translate("en", key)} />);
  expect(screen.getByText("Loading authorized metrics…")).toBeInTheDocument();
  expect(await screen.findByText("Match rate")).toBeInTheDocument();
  expect(screen.getByText("88.00")).toBeInTheDocument();
  expect(screen.getByText("approved matches")).toBeInTheDocument();
});

test("renders an explicit empty authorized state", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(200, { metrics: [] })));
  render(<LiveStudio translate={(key) => translate("en", key)} />);
  expect(await screen.findByText("The authorized workspace returned no metrics.")).toBeInTheDocument();
});

test("renders permission failure and retries only the guarded endpoint", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response(403, {}))
    .mockResolvedValueOnce(response(200, { metrics: [metric] }));
  vi.stubGlobal("fetch", fetcher);
  render(<LiveStudio translate={(key) => translate("en", key)} />);
  expect(await screen.findByText("Live Studio metrics.read permission is required.")).toBeInTheDocument();
  expect(screen.queryByText("Synthetic local demo data only")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry authorized request" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("Match rate")).toBeInTheDocument();
  expect(fetcher.mock.calls.every(([url]) => String(url).includes("/api/v1/metrics/dashboard"))).toBe(true);
});
