import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import App from "./App";
import type { EvidenceBinderContract, ExceptionQueueContract, InventoryControlContract, StudioOverview } from "./types";

const overview: StudioOverview = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY",
  generated_at: "2026-06-01T09:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  workspace: {
    name: "Finance Controls Workspace",
    current_period: "2026-05",
    entity_count: 3,
    evidence_count: 3,
    close_task_count: 2,
  },
  metrics: [
    { key: "close_completion", label: "Close completion", value: 40, format: "percent", tone: "positive", lineage: "Synthetic tasks" },
    { key: "unresolved_high_risk_exceptions", label: "High-risk exceptions", value: 2, format: "count", tone: "critical", lineage: "Synthetic queue" },
    { key: "evidence_coverage", label: "Evidence coverage", value: 100, format: "percent", tone: "positive", lineage: "Synthetic evidence" },
    { key: "match_rate", label: "Match rate", value: 75, format: "percent", tone: "positive", lineage: "Synthetic matching" },
    { key: "control_effectiveness", label: "Control effectiveness", value: 66.67, format: "percent", tone: "warning", lineage: "Synthetic controls" },
    { key: "period_readiness", label: "Period readiness", value: 40, format: "percent", tone: "warning", lineage: "Synthetic readiness" },
  ],
  executive_brief: { readiness_score: 40, readiness_status: "attention", high_risk_count: 1, open_exception_count: 2, blocked_task_count: 0, completed_task_count: 1 },
  control_domains: [
    { domain: "close", score: 40, status: "attention", lineage: "Synthetic tasks" },
    { domain: "evidence", score: 100, status: "strong", lineage: "Synthetic evidence" },
    { domain: "matching", score: 75, status: "watch", lineage: "Synthetic matching" },
    { domain: "controls", score: 66.67, status: "watch", lineage: "Synthetic controls" },
  ],
  entity_health: [
    { entity_code: "SYN-01", entity_name: "Synthetic Operations", region: "EMEA", currency: "USD", open_exception_count: 1, high_risk_count: 1, status: "watch" },
  ],
  risk_distribution: [
    { risk: "critical", count: 0 },
    { risk: "high", count: 1 },
    { risk: "medium", count: 1 },
    { risk: "low", count: 0 },
  ],
  status_distribution: [{ status: "Open", count: 2 }],
  entities: [{ entity_code: "SYN-01", entity_name: "Synthetic Operations", region: "EMEA", currency: "USD" }],
  close_tasks: [
    { task_id: "CLOSE-1", period_name: "2026-05", name: "Load synthetic trial balance", status: "Complete", owner: "Synthetic Lead" },
    { task_id: "CLOSE-2", period_name: "2026-05", name: "Review synthetic exceptions", status: "In Progress", owner: "Synthetic Reviewer" },
  ],
  exceptions: [
    {
      source_type: "journal",
      period_name: "2026-05",
      entity_code: "SYN-01",
      account_code: "9999",
      control_code: "JRN-SYN",
      risk_rating: "high",
      owner: "Synthetic Reviewer",
      status: "Open",
      description: "Synthetic high-value journal requires review.",
    },
  ],
  notices: ["Synthetic local demo data only"],
};

const exceptionQueue: ExceptionQueueContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY",
  generated_at: "2026-06-01T09:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  summary: { total: 2, open: 1, high_risk: 1, unassigned: 1, entity_count: 1 },
  risk_distribution: [{ risk: "high", count: 1 }, { risk: "medium", count: 1 }],
  status_distribution: [{ status: "Open", count: 1 }, { status: "In Review", count: 1 }],
  exceptions: [
    {
      exception_id: "SYN-EXC-ABCDEF123456",
      source_type: "journal",
      period_name: "2026-05",
      entity_code: "SYN-01",
      account_code: "9999",
      control_code: "JRN-SYN",
      risk_rating: "high",
      owner: "Synthetic Reviewer",
      status: "Open",
      description: "Synthetic high-value journal requires review.",
    },
    {
      exception_id: "SYN-EXC-123456ABCDEF",
      source_type: "inventory",
      period_name: "2026-05",
      entity_code: "SYN-01",
      account_code: "1400",
      control_code: "INV-SYN",
      risk_rating: "medium",
      owner: "",
      status: "In Review",
      description: "Synthetic inventory variance needs evidence.",
    },
  ],
  notices: ["Synthetic local demo data only"],
};

const evidenceBinder: EvidenceBinderContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY",
  generated_at: "2026-06-01T09:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  summary: { total: 1, available: 1, checksum_count: 1, synthetic_redaction_count: 1, coverage_percent: 91 },
  status_distribution: [{ status: "Available", count: 1 }],
  evidence: [
    {
      evidence_code: "SYN-EV-001",
      provenance_type: "Generated report",
      redaction_status: "Synthetic redaction",
      evidence_status: "Available",
      checksum_sha256: "a".repeat(64),
    },
  ],
  notices: ["Synthetic local demo data only"],
};

const inventoryControl: InventoryControlContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_ENTERPRISE_DEMO_ONLY",
  generated_at: "2026-06-01T09:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  summary: { item_count: 2, warehouse_count: 1, location_count: 2, movement_count: 2, posted_movement_count: 1, exception_count: 1, count_session_count: 1, reorder_signal_count: 1, valuation_document_count: 2, valuation_reversal_count: 1, open_cost_layer_count: 1, finance_draft_count: 3 },
  warehouses: [
    { warehouse_code: "SYN-MAIN", warehouse_name: "Synthetic main store", entity_code: "SYN-01", on_hand_lines: 2, negative_lines: 1 },
  ],
  on_hand: [
    { item_code: "SYN-PART-01", item_name: "Synthetic service part", uom_code: "EA", warehouse_code: "SYN-MAIN", warehouse_name: "Synthetic main store", location_code: "STOCK", entity_code: "SYN-01", lot_serial_code: "LOT-SYN-01", tracking_type: "Lot", quantity: "12.500" },
    { item_code: "SYN-PART-02", item_name: "Synthetic belt assembly", uom_code: "EA", warehouse_code: "SYN-MAIN", warehouse_name: "Synthetic main store", location_code: "QUARANTINE", entity_code: "SYN-01", lot_serial_code: "", tracking_type: "None", quantity: "-3" },
  ],
  movements: [
    { movement_number: "RCV/SYN/001", movement_type: "Receipt", status: "Posted", movement_date: "2026-05-10", entity_code: "SYN-01", from_location: "", to_location: "SYN-MAIN/STOCK", line_count: 1, quantity: "12.500" },
    { movement_number: "ADJ/SYN/002", movement_type: "Adjustment", status: "Draft", movement_date: "2026-05-11", entity_code: "SYN-01", from_location: "SYN-MAIN/QUARANTINE", to_location: "", line_count: 1, quantity: "3" },
  ],
  exceptions: [
    { exception_id: "SYN-INV-EXC-ABCDEF123456", control_code: "INV-NEGATIVE-STOCK", risk_rating: "high", item_code: "SYN-PART-02", location: "SYN-MAIN/QUARANTINE", quantity: "-3", description: "Synthetic negative stock requires review." },
  ],
  count_sessions: [
    { count_number: "COUNT/SYN/001", status: "Approved", count_date: "2026-05-20", entity_code: "SYN-01", warehouse_code: "SYN-MAIN", location_code: "STOCK", line_count: 2, counted_line_count: 2, variance_line_count: 1, adjustment_movement_number: "ADJ/SYN/002" },
  ],
  reorder_signals: [
    { signal_id: "SYN-INV-REORDER-ABCDEF123456", risk_rating: "medium", item_code: "SYN-PART-01", item_name: "Synthetic service part", uom_code: "EA", warehouse_code: "SYN-MAIN", location_code: "STOCK", on_hand_quantity: "12.500", minimum_quantity: "15.000", target_quantity: "25.000", suggested_quantity: "12.500", lead_time_days: 5 },
  ],
  valuations: [
    { valuation_number: "VAL/SYN/001", movement_number: "RCV/SYN/001", movement_type: "Receipt", status: "Approved", valuation_date: "2026-05-10", entity_code: "SYN-01", costing_method: "FIFO", currency_code: "USD", total_value: "1250.00", finance_entry_number: "IV-VAL/SYN/001", finance_entry_status: "Draft" },
    { valuation_number: "VAL/SYN/002", movement_number: "DLV/SYN/002", movement_type: "Delivery", status: "Approved", valuation_date: "2026-05-11", entity_code: "SYN-01", costing_method: "FIFO", currency_code: "USD", total_value: "300.00", finance_entry_number: "IV-VAL/SYN/002", finance_entry_status: "Draft" },
  ],
  valuation_reversals: [
    { reversal_number: "IVR/SYN/001", original_valuation_number: "VAL/SYN/002", reversal_movement_number: "REV/DLV/SYN/002", original_movement_type: "Delivery", reversal_movement_type: "Receipt", status: "Approved", reversal_date: "2026-05-12", entity_code: "SYN-01", currency_code: "USD", layer_effect: "Restore", layer_effect_count: 1, total_value: "300.00", finance_entry_number: "IVR-IVR/SYN/001", finance_entry_status: "Draft" },
  ],
  cost_layers: [
    { layer_id: "SYN-LAYER-001", valuation_number: "VAL/SYN/001", item_code: "SYN-PART-01", item_name: "Synthetic service part", uom_code: "EA", lot_serial_code: "LOT-SYN-01", entity_code: "SYN-01", currency_code: "USD", original_quantity: "12.500", remaining_quantity: "9.500", original_value: "1250.00", remaining_value: "950.00", layer_status: "Open" },
  ],
  notices: ["Synthetic inventory-control data only"],
};

function artifactFor(input: RequestInfo | URL): StudioOverview | ExceptionQueueContract | EvidenceBinderContract | InventoryControlContract {
  const url = String(input);
  if (url.includes("studio-exceptions.json")) return exceptionQueue;
  if (url.includes("studio-evidence.json")) return evidenceBinder;
  if (url.includes("studio-inventory.json")) return inventoryControl;
  return overview;
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => ({ ok: true, json: async () => artifactFor(input) })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const controlRoomHeading = async () =>
  screen.findByRole("heading", {
    level: 1,
    name: /Control room|مركز الرقابة|لوحة التحكم|Dashboard/i,
  }, { timeout: 20_000 });

test("renders governed synthetic dashboard data", { timeout: 30_000 }, async () => {
  render(<App />);

  expect(screen.getByText("Loading local synthetic control data…")).toBeInTheDocument();
  expect(await controlRoomHeading()).toBeInTheDocument();
  expect(screen.getAllByText("40%").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("Guided control story")).toBeInTheDocument();
  expect(screen.getByText("Decision brief")).toBeInTheDocument();
  expect(screen.getByText("Entity readiness")).toBeInTheDocument();
  expect(screen.getByText("Synthetic high-value journal requires review.")).toBeInTheDocument();
  expect(screen.getAllByText("Synthetic preview").length).toBeGreaterThan(0);
});

test("follows the guided showcase from executive signal to the exception contract", async () => {
  render(<App />);
  await controlRoomHeading();

  fireEvent.click(screen.getByRole("button", { name: /Triage exceptions/ }));

  expect(await screen.findByRole("heading", { level: 1, name: "Exception queue" })).toBeInTheDocument();
  expect(screen.getByText("Synthetic inventory variance needs evidence.")).toBeInTheDocument();
  expect(window.location.pathname).toBe("/exceptions");
});

test("opens the keyboard command palette", async () => {
  render(<App />);
  await controlRoomHeading();

  fireEvent.keyDown(window, { key: "k", ctrlKey: true });

  const dialog = screen.getByRole("dialog", { name: "Command palette" });
  expect(dialog).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: /Exceptions/ })).toBeInTheDocument();
});

test("navigates to the native exception queue and filters its versioned contract", async () => {
  render(<App />);
  await controlRoomHeading();

  const primaryNavigation = screen.getByRole("navigation", { name: "Primary navigation" });
  fireEvent.click(within(primaryNavigation).getByRole("button", { name: /Exceptions/ }));

  expect(await screen.findByRole("heading", { level: 1, name: "Exception queue" })).toBeInTheDocument();
  expect(screen.getByText("Synthetic inventory variance needs evidence.")).toBeInTheDocument();
  expect(window.location.pathname).toBe("/exceptions");

  fireEvent.change(screen.getByRole("textbox", { name: "Filter exceptions" }), { target: { value: "ABCDEF123456" } });
  expect(screen.queryByText("Synthetic inventory variance needs evidence.")).not.toBeInTheDocument();
  expect(screen.getByText("Synthetic high-value journal requires review.")).toBeInTheDocument();
});

test("navigates to the native evidence binder without exposing source paths", async () => {
  render(<App />);
  await controlRoomHeading();

  const primaryNavigation = screen.getByRole("navigation", { name: "Primary navigation" });
  fireEvent.click(within(primaryNavigation).getByRole("button", { name: /Evidence binder/ }));

  expect(await screen.findByRole("heading", { level: 1, name: "Evidence binder" })).toBeInTheDocument();
  expect(screen.getByText("SYN-EV-001")).toBeInTheDocument();
  expect(screen.getByText("aaaaaaaaaaaa…aaaaaaaa")).toBeInTheDocument();
  expect(screen.queryByText(/source_path/i)).not.toBeInTheDocument();
  expect(window.location.pathname).toBe("/evidence");
});

test("navigates to the inventory control center and filters its exact local contract", async () => {
  render(<App />);
  await controlRoomHeading();

  const primaryNavigation = screen.getByRole("navigation", { name: "Primary navigation" });
  fireEvent.click(within(primaryNavigation).getByRole("button", { name: /Inventory controls/ }));

  expect(await screen.findByRole("heading", { level: 1, name: "Inventory control center" })).toBeInTheDocument();
  expect(screen.getByText("12.500")).toBeInTheDocument();
  expect(screen.getByText("Synthetic belt assembly")).toBeInTheDocument();
  expect(window.location.pathname).toBe("/inventory");

  fireEvent.change(screen.getByRole("textbox", { name: "Filter inventory records" }), { target: { value: "service part" } });
  expect(screen.queryByText("Synthetic belt assembly")).not.toBeInTheDocument();
  expect(screen.getByText("Synthetic service part")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Controls" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Filter inventory records" }), { target: { value: "" } });
  expect(screen.getByText("Synthetic negative stock requires review.")).toBeInTheDocument();
  expect(screen.queryByText(/private_cost/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Counts" }));
  expect(screen.getByText("COUNT/SYN/001")).toBeInTheDocument();
  expect(screen.getByText("ADJ/SYN/002")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Reorder advice" }));
  expect(screen.getByText(/SYN-INV-REORDER-ABCDEF123456/)).toBeInTheDocument();
  expect(screen.getAllByText("12.500").length).toBeGreaterThan(0);

  fireEvent.click(screen.getByRole("tab", { name: "FIFO valuation" }));
  expect(screen.getAllByText("VAL/SYN/001").length).toBeGreaterThan(0);
  expect(screen.getByText("IV-VAL/SYN/001")).toBeInTheDocument();
  expect(screen.getByText("IVR/SYN/001")).toBeInTheDocument();
  expect(screen.getByText("IVR-IVR/SYN/001")).toBeInTheDocument();
  expect(screen.getByText("SYN-LAYER-001")).toBeInTheDocument();
});

test("rejects malformed exact inventory quantities", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => String(input).includes("studio-inventory.json")
        ? { ...inventoryControl, on_hand: [{ ...inventoryControl.on_hand[0], quantity: "12.5000001" }] }
        : overview,
    })),
  );
  window.history.replaceState({}, "", "/inventory");

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByText("The local Studio inventory control artifact does not match schema version 1.")).toBeInTheDocument();
});

test("rejects an unlinked valuation reversal even when each row is structurally valid", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => String(input).includes("studio-inventory.json")
        ? {
            ...inventoryControl,
            valuation_reversals: [
              { ...inventoryControl.valuation_reversals[0], original_valuation_number: "VAL/SYN/MISSING" },
            ],
          }
        : overview,
    })),
  );
  window.history.replaceState({}, "", "/inventory");

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByText("The local Studio inventory control artifact does not match schema version 1.")).toBeInTheDocument();
});

test("rejects malformed evidence contract records", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => String(input).includes("studio-evidence.json")
        ? { ...evidenceBinder, evidence: [{ ...evidenceBinder.evidence[0], checksum_sha256: "unsafe" }] }
        : overview,
    })),
  );
  window.history.replaceState({}, "", "/evidence");

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByText("The local Studio evidence binder artifact does not match schema version 1.")).toBeInTheDocument();
});

test("switches to Arabic RTL and persists accessibility preferences", async () => {
  render(<App />);
  await controlRoomHeading();

  fireEvent.click(screen.getByTestId("locale-toggle"));
  await screen.findByRole("heading", { level: 1, name: "مركز الرقابة" });
  expect(document.documentElement).toHaveAttribute("dir", "rtl");

  fireEvent.click(screen.getByRole("button", { name: "إمكانية الوصول" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "نص أكبر" }));

  await waitFor(() => expect(document.documentElement.dataset.largeText).toBe("true"));
  expect(window.localStorage.getItem("reconforge.accessibility")).toContain('"largerText":true');
});

test("shows a safe retry state when the local artifact fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByRole("button", { name: /Try again/ })).toBeInTheDocument();
  expect(screen.getByText("reconforge demo studio-data")).toBeInTheDocument();
});

test("rejects malformed nested contract data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...overview,
        exceptions: [{ ...overview.exceptions[0], description: { unsafe: "object" } }],
      }),
    }),
  );

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByText("The local Studio overview artifact does not match schema version 1.")).toBeInTheDocument();
});

test("rejects an executive brief that disagrees with its governed metrics", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...overview,
        executive_brief: { ...overview.executive_brief, high_risk_count: 999 },
      }),
    }),
  );

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  expect(screen.getByText("The local Studio overview artifact does not match schema version 1.")).toBeInTheDocument();
});

test("ignores invalid persisted accessibility value types", async () => {
  window.localStorage.setItem(
    "reconforge.accessibility",
    JSON.stringify({ largerText: "yes", highContrast: true, focusOutlines: false }),
  );

  render(<App />);
  await controlRoomHeading();

  expect(document.documentElement.dataset.largeText).toBe("false");
  expect(document.documentElement.dataset.highContrast).toBe("true");
  expect(document.documentElement.dataset.focusOutlines).toBe("false");
});

test("cycles and persists the theme preference", async () => {
  render(<App />);
  await controlRoomHeading();

  fireEvent.click(screen.getByRole("button", { name: "Theme: System" }));

  await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
  expect(window.localStorage.getItem("reconforge.theme")).toBe("light");
});

test("discloses the bounded synthetic workspace", async () => {
  render(<App />);
  await controlRoomHeading();

  fireEvent.click(screen.getByLabelText("Workspace details"));

  expect(screen.getByText("Only workspace in this preview")).toBeVisible();
});

test("renders explicit empty states for an empty synthetic snapshot", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...overview,
        metrics: [],
        executive_brief: { ...overview.executive_brief, readiness_score: 0, high_risk_count: 0, open_exception_count: 0, blocked_task_count: 0, completed_task_count: 0 },
        control_domains: [],
        risk_distribution: [],
        status_distribution: [],
        close_tasks: [],
        exceptions: [],
      }),
    }),
  );

  render(<App />);

  await controlRoomHeading();
  expect(screen.getAllByText("No records in this synthetic snapshot.").length).toBeGreaterThanOrEqual(4);
});
