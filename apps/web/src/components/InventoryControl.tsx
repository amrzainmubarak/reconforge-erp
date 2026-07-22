import {
  AlertTriangle,
  ArrowLeftRight,
  Boxes,
  CircleDollarSign,
  ClipboardCheck,
  Layers3,
  MapPin,
  PackageCheck,
  PackageSearch,
  RotateCcw,
  Search,
  ShieldAlert,
  Warehouse,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadInventoryControl } from "../data";
import type { MessageKey } from "../i18n";
import type { InventoryControlContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface InventoryControlProps {
  translate: (key: MessageKey) => string;
}

type InventoryView = "balances" | "movements" | "valuation" | "counts" | "reorder" | "controls";

function joinLocation(fromLocation: string, toLocation: string): string {
  if (fromLocation && toLocation) return `${fromLocation} → ${toLocation}`;
  return fromLocation || toLocation || "—";
}

export function InventoryControl({ translate }: InventoryControlProps) {
  const [data, setData] = useState<InventoryControlContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [warehouseCode, setWarehouseCode] = useState("");
  const [view, setView] = useState<InventoryView>("balances");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadInventoryControl(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "The local inventory contract could not be loaded.");
      });
    return () => controller.abort();
  }, [attempt]);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const balances = useMemo(() => {
    if (!data) return [];
    return data.on_hand.filter((record) => {
      const haystack = [
        record.item_code,
        record.item_name,
        record.warehouse_code,
        record.location_code,
        record.lot_serial_code,
        record.entity_code,
      ].join(" ").toLocaleLowerCase();
      return (!normalizedQuery || haystack.includes(normalizedQuery)) &&
        (!warehouseCode || record.warehouse_code === warehouseCode);
    });
  }, [data, normalizedQuery, warehouseCode]);
  const movements = useMemo(() => {
    if (!data) return [];
    return data.movements.filter((record) => {
      const haystack = [record.movement_number, record.movement_type, record.status, record.entity_code, record.from_location, record.to_location]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const controls = useMemo(() => {
    if (!data) return [];
    return data.exceptions.filter((record) => {
      const haystack = [record.exception_id, record.control_code, record.item_code, record.location, record.description]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const countSessions = useMemo(() => {
    if (!data) return [];
    return data.count_sessions.filter((record) => {
      const haystack = [record.count_number, record.status, record.entity_code, record.warehouse_code, record.location_code, record.adjustment_movement_number]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const reorderSignals = useMemo(() => {
    if (!data) return [];
    return data.reorder_signals.filter((record) => {
      const haystack = [record.signal_id, record.risk_rating, record.item_code, record.item_name, record.warehouse_code, record.location_code]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const valuations = useMemo(() => {
    if (!data) return [];
    return data.valuations.filter((record) => {
      const haystack = [record.valuation_number, record.movement_number, record.movement_type, record.status, record.entity_code, record.finance_entry_number, record.finance_entry_status]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const valuationReversals = useMemo(() => {
    if (!data) return [];
    return data.valuation_reversals.filter((record) => {
      const haystack = [record.reversal_number, record.original_valuation_number, record.reversal_movement_number, record.status, record.entity_code, record.layer_effect, record.finance_entry_number, record.finance_entry_status]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);
  const costLayers = useMemo(() => {
    if (!data) return [];
    return data.cost_layers.filter((record) => {
      const haystack = [record.layer_id, record.valuation_number, record.item_code, record.item_name, record.lot_serial_code, record.entity_code, record.layer_status]
        .join(" ")
        .toLocaleLowerCase();
      return !normalizedQuery || haystack.includes(normalizedQuery);
    });
  }, [data, normalizedQuery]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  const resultCount = view === "balances"
    ? balances.length
    : view === "movements"
      ? movements.length
      : view === "valuation"
        ? valuations.length + valuationReversals.length + costLayers.length
      : view === "counts"
        ? countSessions.length
        : view === "reorder"
          ? reorderSignals.length
          : controls.length;

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero workbench-hero--inventory">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("localInventoryLedger")}</div>
          <h1>{translate("inventoryControlTitle")}</h1>
          <p>{translate("inventoryControlIntro")}</p>
        </div>
        <div className="contract-badge"><Boxes size={18} /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <section className="workbench-stats" aria-label={translate("inventoryControlTitle")}>
        <article><span className="stat-icon"><PackageCheck size={18} /></span><strong>{data.summary.item_count}</strong><small>{translate("inventoryItems")}</small></article>
        <article><span className="stat-icon"><Warehouse size={18} /></span><strong>{data.summary.warehouse_count}</strong><small>{translate("warehouses")}</small></article>
        <article><span className="stat-icon"><MapPin size={18} /></span><strong>{data.summary.location_count}</strong><small>{translate("locations")}</small></article>
        <article><span className="stat-icon"><ArrowLeftRight size={18} /></span><strong>{data.summary.posted_movement_count}/{data.summary.movement_count}</strong><small>{translate("postedMovements")}</small></article>
        <article><span className="stat-icon"><ClipboardCheck size={18} /></span><strong>{data.summary.count_session_count}</strong><small>{translate("countSessions")}</small></article>
        <article><span className="stat-icon"><CircleDollarSign size={18} /></span><strong>{data.summary.valuation_document_count}</strong><small>{translate("valuationDocuments")}</small></article>
        <article><span className="stat-icon"><RotateCcw size={18} /></span><strong>{data.summary.valuation_reversal_count}</strong><small>{translate("valuationReversals")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><PackageSearch size={18} /></span><strong>{data.summary.reorder_signal_count}</strong><small>{translate("reorderSignals")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{data.summary.exception_count}</strong><small>{translate("inventoryExceptions")}</small></article>
      </section>

      {data.warehouses.length ? (
        <section className="inventory-warehouses" aria-label={translate("warehouses")}>
          {data.warehouses.map((warehouse) => (
            <button
              type="button"
              className={`inventory-warehouse ${warehouseCode === warehouse.warehouse_code ? "inventory-warehouse--active" : ""}`}
              key={warehouse.warehouse_code}
              onClick={() => {
                setWarehouseCode((current) => current === warehouse.warehouse_code ? "" : warehouse.warehouse_code);
                setView("balances");
              }}
              aria-pressed={warehouseCode === warehouse.warehouse_code}
            >
              <span className="inventory-warehouse-icon"><Warehouse size={18} /></span>
              <span><strong>{warehouse.warehouse_name}</strong><small>{warehouse.warehouse_code} · {warehouse.entity_code}</small></span>
              <span className={warehouse.negative_lines ? "inventory-warehouse-alert" : "inventory-warehouse-ok"}>
                {warehouse.negative_lines ? `${warehouse.negative_lines} ${translate("negativeLines")}` : translate("noNegativeLines")}
              </span>
            </button>
          ))}
        </section>
      ) : null}

      <section className="panel workbench-panel">
        <div className="inventory-toolbar">
          <div className="inventory-tabs" role="tablist" aria-label={translate("inventoryControlTitle")}>
            {(["balances", "movements", "valuation", "counts", "reorder", "controls"] as const).map((tab) => (
              <button
                type="button"
                role="tab"
                aria-selected={view === tab}
                className={view === tab ? "inventory-tab inventory-tab--active" : "inventory-tab"}
                key={tab}
                onClick={() => setView(tab)}
              >
                {translate(tab)}
              </button>
            ))}
          </div>
          <label className="filter-search inventory-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterInventory")} aria-label={translate("filterInventory")} />
          </label>
          <span className="result-count" aria-live="polite"><strong>{resultCount}</strong> {translate("results")}</span>
        </div>

        {view === "balances" && balances.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("inventoryItem")}</th><th>{translate("warehouseLocation")}</th><th>{translate("entity")}</th><th>{translate("tracking")}</th><th>{translate("lotSerial")}</th><th>{translate("onHand")}</th></tr></thead>
              <tbody>{balances.map((record) => (
                <tr key={`${record.warehouse_code}/${record.location_code}/${record.item_code}/${record.lot_serial_code}`}>
                  <td><span className="exception-title"><Layers3 size={15} />{record.item_name}</span><small>{record.item_code}</small></td>
                  <td>{record.warehouse_code}<small>{record.location_code}</small></td>
                  <td>{record.entity_code}</td>
                  <td><span className="status-chip">{record.tracking_type}</span></td>
                  <td>{record.lot_serial_code || "—"}</td>
                  <td><strong className={record.quantity.startsWith("-") ? "inventory-negative" : "inventory-quantity"}>{record.quantity}</strong> <small>{record.uom_code}</small></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "movements" && movements.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("movement")}</th><th>{translate("movementDate")}</th><th>{translate("entity")}</th><th>{translate("route")}</th><th>{translate("lines")}</th><th>{translate("quantity")}</th><th>{translate("status")}</th></tr></thead>
              <tbody>{movements.map((record) => (
                <tr key={record.movement_number}>
                  <td><span className="exception-title"><ArrowLeftRight size={15} />{record.movement_number}</span><small>{record.movement_type}</small></td>
                  <td>{record.movement_date}</td>
                  <td>{record.entity_code}</td>
                  <td>{joinLocation(record.from_location, record.to_location)}</td>
                  <td>{record.line_count}</td>
                  <td><strong>{record.quantity}</strong></td>
                  <td><span className={`status-chip inventory-status--${record.status.toLowerCase()}`}>{record.status}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "valuation" && valuations.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("valuationDocument")}</th><th>{translate("movement")}</th><th>{translate("movementDate")}</th><th>{translate("entity")}</th><th>{translate("costingMethod")}</th><th>{translate("valuationTotal")}</th><th>{translate("financeDraft")}</th><th>{translate("status")}</th></tr></thead>
              <tbody>{valuations.map((record) => (
                <tr key={record.valuation_number}>
                  <td><span className="exception-title"><CircleDollarSign size={15} />{record.valuation_number}</span></td>
                  <td>{record.movement_number}<small>{record.movement_type}</small></td>
                  <td>{record.valuation_date}</td>
                  <td>{record.entity_code}</td>
                  <td><span className="status-chip">{record.costing_method}</span></td>
                  <td><strong>{record.total_value}</strong> <small>{record.currency_code}</small></td>
                  <td>{record.finance_entry_number || "—"}<small>{record.finance_entry_status || translate("notPrepared")}</small></td>
                  <td><span className={`status-chip inventory-status--${record.status.toLowerCase()}`}>{record.status}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "valuation" && valuationReversals.length ? (
          <div className="table-scroll workbench-table inventory-table inventory-valuation-reversals" tabIndex={0}>
            <table>
              <thead><tr><th>{translate("reversalDocument")}</th><th>{translate("originalValuation")}</th><th>{translate("movement")}</th><th>{translate("movementDate")}</th><th>{translate("layerEffect")}</th><th>{translate("valuationTotal")}</th><th>{translate("financeDraft")}</th><th>{translate("status")}</th></tr></thead>
              <tbody>{valuationReversals.map((record) => (
                <tr key={record.reversal_number}>
                  <td><span className="exception-title"><RotateCcw size={15} />{record.reversal_number}</span></td>
                  <td>{record.original_valuation_number}<small>{record.original_movement_type}</small></td>
                  <td>{record.reversal_movement_number}<small>{record.reversal_movement_type}</small></td>
                  <td>{record.reversal_date}<small>{record.entity_code}</small></td>
                  <td><span className="status-chip">{record.layer_effect}</span><small>{record.layer_effect_count} {translate(record.layer_effect_count === 1 ? "effect" : "effects")}</small></td>
                  <td><strong>{record.total_value}</strong> <small>{record.currency_code}</small></td>
                  <td>{record.finance_entry_number || "—"}<small>{record.finance_entry_status || translate("notPrepared")}</small></td>
                  <td><span className={`status-chip inventory-status--${record.status.toLowerCase()}`}>{record.status}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "valuation" && costLayers.length ? (
          <div className="table-scroll workbench-table inventory-table inventory-valuation-layers" tabIndex={0}>
            <table>
              <thead><tr><th>{translate("costLayer")}</th><th>{translate("inventoryItem")}</th><th>{translate("entity")}</th><th>{translate("lotSerial")}</th><th>{translate("originalQuantity")}</th><th>{translate("remainingQuantity")}</th><th>{translate("remainingValue")}</th><th>{translate("status")}</th></tr></thead>
              <tbody>{costLayers.map((record) => (
                <tr key={record.layer_id}>
                  <td><span className="exception-title"><Layers3 size={15} />{record.layer_id}</span><small>{record.valuation_number}</small></td>
                  <td>{record.item_name}<small>{record.item_code}</small></td>
                  <td>{record.entity_code}</td>
                  <td>{record.lot_serial_code || "—"}</td>
                  <td>{record.original_quantity} <small>{record.uom_code}</small></td>
                  <td><strong>{record.remaining_quantity}</strong> <small>{record.uom_code}</small></td>
                  <td><strong>{record.remaining_value}</strong> <small>{record.currency_code}</small></td>
                  <td><span className="status-chip">{record.layer_status}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "counts" && countSessions.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("countSession")}</th><th>{translate("movementDate")}</th><th>{translate("warehouseLocation")}</th><th>{translate("countProgress")}</th><th>{translate("varianceLines")}</th><th>{translate("draftAdjustment")}</th><th>{translate("status")}</th></tr></thead>
              <tbody>{countSessions.map((record) => (
                <tr key={record.count_number}>
                  <td><span className="exception-title"><ClipboardCheck size={15} />{record.count_number}</span><small>{record.entity_code}</small></td>
                  <td>{record.count_date}</td>
                  <td>{record.warehouse_code}<small>{record.location_code}</small></td>
                  <td><strong>{record.counted_line_count}/{record.line_count}</strong></td>
                  <td><strong className={record.variance_line_count ? "inventory-negative" : "inventory-quantity"}>{record.variance_line_count}</strong></td>
                  <td>{record.adjustment_movement_number || "—"}</td>
                  <td><span className={`status-chip inventory-status--${record.status.toLowerCase()}`}>{record.status}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "reorder" && reorderSignals.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("inventoryItem")}</th><th>{translate("warehouseLocation")}</th><th>{translate("onHand")}</th><th>{translate("reorderMinimum")}</th><th>{translate("reorderTarget")}</th><th>{translate("suggestedQuantity")}</th><th>{translate("leadTime")}</th><th>{translate("risk")}</th></tr></thead>
              <tbody>{reorderSignals.map((record) => (
                <tr key={record.signal_id}>
                  <td><span className="exception-title"><PackageSearch size={15} />{record.item_name}</span><small>{record.item_code} · {record.signal_id}</small></td>
                  <td>{record.warehouse_code}<small>{record.location_code}</small></td>
                  <td>{record.on_hand_quantity} <small>{record.uom_code}</small></td>
                  <td>{record.minimum_quantity}</td>
                  <td>{record.target_quantity}</td>
                  <td><strong>{record.suggested_quantity}</strong> <small>{record.uom_code}</small></td>
                  <td>{record.lead_time_days} {translate("days")}</td>
                  <td><span className={`risk-chip risk-chip--${record.risk_rating}`}>{record.risk_rating}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {view === "controls" && controls.length ? (
          <div className="table-scroll workbench-table inventory-table" tabIndex={0} role="tabpanel">
            <table>
              <thead><tr><th>{translate("exception")}</th><th>{translate("inventoryItem")}</th><th>{translate("warehouseLocation")}</th><th>{translate("quantity")}</th><th>{translate("risk")}</th></tr></thead>
              <tbody>{controls.map((record) => (
                <tr key={record.exception_id}>
                  <td><span className="exception-title"><ShieldAlert size={15} />{record.description}</span><small>{record.exception_id} · {record.control_code}</small></td>
                  <td>{record.item_code}</td>
                  <td>{record.location || "—"}</td>
                  <td>{record.quantity || "—"}</td>
                  <td><span className={`risk-chip risk-chip--${record.risk_rating}`}>{record.risk_rating}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}

        {resultCount === 0 ? <p className="empty-panel">{translate("empty")}</p> : null}
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("inventoryBoundary")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
