import type { FinanceScope } from "./enterprise-finance-data";
import { monetaryStockRoot } from "./monetary-paths";
import { monetaryBalanceFields, monetaryDate, monetaryDecimal, monetaryDigest, monetaryInteger, monetaryInvalid, monetaryMinor,
  monetaryNullableText, monetaryObject, monetaryRequest, monetaryScope, monetaryText, parseMonetaryPolicyPair, parseMonetaryRate,
  validateMonetaryBalance, type MonetaryBalanceFields, type MonetaryPolicy, type MonetaryRate } from "./monetary-public-data";
import type { PreparedScopedCommand } from "./scoped-command";
import { stockStages, type StockOptions, type StockStage } from "./stock-sales-data";
import type { BrowserAdminSession } from "./types";

export interface MonetaryTaxDeclaration {
  policy_id: string; country_code: string; transaction_class: string; effective_from: string; effective_to: string;
  rate: string; account_code: string; source: string; version: string;
}
export interface MonetaryTaxComponent extends MonetaryTaxDeclaration { policy_digest: string; transaction_tax_minor: string; functional_tax_minor: string }
export interface MonetaryOrigin {
  schema_version: "stock-monetary-origin-v1"; id: string; fx_source_id: string; recognition_plan_id: string; invoice_id: string; source_digest: string;
  country_code: string; transaction_class: string; original_rate: MonetaryRate | null;
  transaction_net_minor: string; transaction_tax_minor: string; transaction_gross_minor: string;
  functional_net_minor: string; functional_tax_minor: string; functional_gross_minor: string; tax_components: MonetaryTaxComponent[];
  receivable_account_code: string; revenue_account_code: string; cash_account_code: string; refund_liability_account_code: string;
  gain_account_code: string; loss_account_code: string; journal_code: string; period_id: string; invoice_number: string; invoice_date: string; due_date: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; entry_id: string; posting_effect_id: string | null;
}
export interface MonetaryStockCollection {
  id: string; sequence: number; status: "Prepared" | "Reviewed" | "Posted"; plan_digest: string; amount_minor: string;
  functional_cash_minor: string; functional_receivable_released_minor: string; functional_fx_gain_minor: string; functional_fx_loss_minor: string;
  settlement_rate: MonetaryRate | null; receipt_number: string; receipt_date: string; period_id: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; entry_id: string | null; posting_effect_id: string | null; receipt_id: string | null;
}
export interface MonetaryStockEvent { version: number; actor_id: string; operation: string; reason: string; status: StockStage; audit_event_id: string }
export interface MonetaryStock extends FinanceScope {
  schema_version: "stock-sales-monetary-v2"; id: string; number: string; status: StockStage; row_version: number; source_digest: string;
  customer_code: string; customer_reference: string; item_code: string; warehouse_code: string; location_code: string;
  quantity: string; quantity_scaled: string; quantity_precision: number; unit_price_minor: string; discount_basis_points: number; net_unit_price_minor: string;
  transaction_net_minor: string; description: string; order_date: string; transaction_policy: MonetaryPolicy; functional_policy: MonetaryPolicy;
  created_by: string; approved_by: string | null; issue_preparer_id: string | null; issue_reviewer_id: string | null; issue_digest: string | null;
  functional_cogs_minor: string | null; cogs_entry_id: string | null; cogs_effect_id: string | null; movement_id: string | null; valuation_id: string | null;
  cost_admission_policy: "partial-return-restituted-v1" | null; monetary_origin: MonetaryOrigin | null;
  balance: MonetaryBalanceFields | null; collection: MonetaryStockCollection | null; events: MonetaryStockEvent[];
}
export type MonetaryStockOptions = Omit<StockOptions, "accounts"> & {
  accounts: (Omit<StockOptions["accounts"][number], "account_type"> & { account_type: "Asset" | "Income" | "Expense" | "Liability" })[];
};
const stockFields = ["schema_version", "id", "workspace_id", "organization_id", "legal_entity_id", "number", "status", "row_version", "source_digest",
  "customer_code", "customer_reference", "item_code", "warehouse_code", "location_code", "quantity", "quantity_scaled", "quantity_precision",
  "unit_price_minor", "discount_basis_points", "net_unit_price_minor", "transaction_net_minor", "description", "order_date", "transaction_policy", "functional_policy",
  "created_by", "approved_by", "issue_preparer_id", "issue_reviewer_id", "issue_digest", "functional_cogs_minor", "cogs_entry_id", "cogs_effect_id", "movement_id", "valuation_id",
  "cost_admission_policy", "monetary_origin", "balance", "collection", "events"] as const;
const originFields = ["schema_version", "id", "fx_source_id", "recognition_plan_id", "invoice_id", "source_digest", "country_code", "transaction_class", "original_rate",
  "transaction_net_minor", "transaction_tax_minor", "transaction_gross_minor", "functional_net_minor", "functional_tax_minor", "functional_gross_minor", "tax_components",
  "receivable_account_code", "revenue_account_code", "cash_account_code", "refund_liability_account_code", "gain_account_code", "loss_account_code", "journal_code", "period_id",
  "invoice_number", "invoice_date", "due_date", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id"] as const;
const taxFields = ["policy_id", "country_code", "transaction_class", "effective_from", "effective_to", "rate", "account_code", "source", "version", "policy_digest", "transaction_tax_minor", "functional_tax_minor"] as const;
const collectionFields = ["id", "sequence", "status", "plan_digest", "amount_minor", "functional_cash_minor", "functional_receivable_released_minor", "functional_fx_gain_minor", "functional_fx_loss_minor",
  "settlement_rate", "receipt_number", "receipt_date", "period_id", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id", "receipt_id"] as const;
const eventFields = ["version", "actor_id", "operation", "reason", "status", "audit_event_id"] as const;
const firstEvents = [["create", "Draft"], ["submit", "Submitted"], ["approve", "Approved"], ["reserve", "Reserved"], ["prepare-issue", "IssuePrepared"],
  ["review-issue", "IssueReviewed"], ["deliver", "Delivered"], ["prepare-invoice", "InvoicePrepared"], ["review-invoice", "InvoiceReviewed"], ["invoice", "Invoiced"]] as const;

function origin(value: unknown, stock: Record<string, unknown>, identity: boolean): MonetaryOrigin {
  const row = monetaryObject(value, originFields);
  if (row.schema_version !== "stock-monetary-origin-v1") monetaryInvalid();
  for (const key of originFields) if (!["schema_version", "original_rate", "tax_components", "reviewer_actor_id", "posted_actor_id", "posting_effect_id"].includes(key) && !key.endsWith("_minor")) monetaryText(row[key], 200);
  for (const key of ["reviewer_actor_id", "posted_actor_id", "posting_effect_id"]) monetaryNullableText(row[key]);
  monetaryDigest(row.source_digest); monetaryDate(row.invoice_date); monetaryDate(row.due_date);
  if ((row.due_date as string) < (row.invoice_date as string) || (row.invoice_date as string) < (stock.order_date as string)
      || !/^[A-Z]{2}$/.test(row.country_code as string)) monetaryInvalid();
  row.original_rate = parseMonetaryRate(row.original_rate, row.invoice_date as string, identity);
  for (const key of originFields.filter(key => key.endsWith("_minor"))) monetaryMinor(row[key]);
  if (row.transaction_net_minor !== stock.transaction_net_minor || row.functional_net_minor === "0") monetaryInvalid();
  for (const prefix of ["transaction", "functional"]) if (BigInt(row[`${prefix}_net_minor`] as string) + BigInt(row[`${prefix}_tax_minor`] as string) !== BigInt(row[`${prefix}_gross_minor`] as string)) monetaryInvalid();
  if (identity && ["net", "tax", "gross"].some(key => row[`transaction_${key}_minor`] !== row[`functional_${key}_minor`])) monetaryInvalid();
  if (!Array.isArray(row.tax_components) || row.tax_components.length > 8) monetaryInvalid();
  const seen = new Set<string>();
  const components = row.tax_components.map(item => {
    const tax = monetaryObject(item, taxFields);
    for (const key of taxFields.filter(key => !key.endsWith("_minor"))) monetaryText(tax[key], 200);
    monetaryDigest(tax.policy_digest); monetaryDecimal(tax.rate, true); monetaryDate(tax.effective_from); monetaryDate(tax.effective_to);
    if (seen.has(tax.policy_id as string) || tax.country_code !== row.country_code || tax.transaction_class !== row.transaction_class
        || (tax.effective_from as string) > (row.invoice_date as string) || (tax.effective_to as string) < (row.invoice_date as string)) monetaryInvalid();
    seen.add(tax.policy_id as string); monetaryMinor(tax.transaction_tax_minor); monetaryMinor(tax.functional_tax_minor);
    if (identity && tax.transaction_tax_minor !== tax.functional_tax_minor) monetaryInvalid();
    return tax as unknown as MonetaryTaxComponent;
  });
  if (components.reduce((sum, tax) => sum + BigInt(tax.transaction_tax_minor), 0n).toString() !== row.transaction_tax_minor
      || components.reduce((sum, tax) => sum + BigInt(tax.functional_tax_minor), 0n).toString() !== row.functional_tax_minor) monetaryInvalid();
  if (row.reviewer_actor_id !== null && row.reviewer_actor_id === row.preparer_actor_id || (row.posted_actor_id === null) !== (row.posting_effect_id === null)
      || row.posted_actor_id !== null && (row.reviewer_actor_id === null || [row.preparer_actor_id, row.reviewer_actor_id].includes(row.posted_actor_id))) monetaryInvalid();
  return { ...row, tax_components: components } as unknown as MonetaryOrigin;
}
function collection(value: unknown, identity: boolean): MonetaryStockCollection {
  const row = monetaryObject(value, collectionFields);
  for (const key of ["id", "receipt_number", "period_id", "preparer_actor_id"]) monetaryText(row[key]);
  for (const key of ["reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id", "receipt_id"]) monetaryNullableText(row[key]);
  monetaryInteger(row.sequence, 256, 1); monetaryDigest(row.plan_digest); monetaryDate(row.receipt_date);
  row.settlement_rate = parseMonetaryRate(row.settlement_rate, row.receipt_date as string, identity);
  for (const key of collectionFields.filter(key => key.endsWith("_minor"))) monetaryMinor(row[key], key === "amount_minor");
  const cash = BigInt(row.functional_cash_minor as string), loss = BigInt(row.functional_fx_loss_minor as string), gain = BigInt(row.functional_fx_gain_minor as string);
  if (loss > 0n && gain > 0n || cash + loss !== BigInt(row.functional_receivable_released_minor as string) + gain || (row.entry_id === null) !== (cash + loss === 0n)
      || !["Prepared", "Reviewed", "Posted"].includes(row.status as string)) monetaryInvalid();
  if (identity && (row.functional_cash_minor !== row.amount_minor || row.functional_receivable_released_minor !== row.amount_minor || gain !== 0n || loss !== 0n)) monetaryInvalid();
  const reviewed = row.status !== "Prepared", posted = row.status === "Posted";
  if ((row.reviewer_actor_id !== null) !== reviewed || (row.posted_actor_id !== null) !== posted || (row.receipt_id !== null) !== posted
      || (row.posting_effect_id !== null) !== (posted && cash + loss > 0n)
      || reviewed && row.reviewer_actor_id === row.preparer_actor_id || posted && [row.preparer_actor_id, row.reviewer_actor_id].includes(row.posted_actor_id)) monetaryInvalid();
  return row as unknown as MonetaryStockCollection;
}
function quoted(quantity: string, precision: number, unit: string, discount: number, request = false): { quantity: bigint; netUnit: bigint; total: bigint } {
  if (!/^(0|[1-9][0-9]{0,18})(\.[0-9]{1,6})?$/.test(quantity)) monetaryInvalid();
  const [whole, fraction = ""] = quantity.split(".");
  if (fraction.length > precision && (!request || /[1-9]/.test(fraction.slice(precision)))) monetaryInvalid();
  const scaled = BigInt(whole + fraction.slice(0, precision).padEnd(precision, "0")), scale = 10n ** BigInt(precision);
  if (scaled <= 0n) monetaryInvalid();
  const netUnit = (BigInt(unit) * BigInt(10000 - discount) + 5000n) / 10000n;
  return { quantity: scaled, netUnit, total: (scaled * netUnit * 2n + scale) / (2n * scale) };
}
export function parseMonetaryStock(value: unknown, scope: FinanceScope, id?: string): MonetaryStock {
  const row = monetaryObject(value, stockFields); monetaryScope(row, scope);
  if (row.schema_version !== "stock-sales-monetary-v2" || !stockStages.includes(row.status as StockStage) || id && row.id !== id) monetaryInvalid();
  for (const key of ["id", "number", "customer_code", "customer_reference", "item_code", "warehouse_code", "location_code", "quantity", "created_by"]) monetaryText(row[key]);
  monetaryText(row.description, 500); monetaryDate(row.order_date); monetaryDigest(row.source_digest);
  if (row.issue_digest !== null) monetaryDigest(row.issue_digest);
  monetaryInteger(row.row_version, 1024, 1); monetaryInteger(row.quantity_precision, 6); monetaryInteger(row.discount_basis_points, 9999);
  for (const key of ["quantity_scaled", "unit_price_minor", "net_unit_price_minor", "transaction_net_minor"]) monetaryMinor(row[key], true);
  const quote = quoted(row.quantity as string, row.quantity_precision as number, row.unit_price_minor as string, row.discount_basis_points as number);
  if (quote.quantity.toString() !== row.quantity_scaled || quote.netUnit.toString() !== row.net_unit_price_minor || quote.total.toString() !== row.transaction_net_minor) monetaryInvalid();
  [row.transaction_policy, row.functional_policy] = parseMonetaryPolicyPair(row.transaction_policy, row.functional_policy);
  const identity = (row.transaction_policy as MonetaryPolicy).currency_code === (row.functional_policy as MonetaryPolicy).currency_code;
  for (const key of ["approved_by", "issue_preparer_id", "issue_reviewer_id", "cogs_entry_id", "cogs_effect_id", "movement_id", "valuation_id"]) monetaryNullableText(row[key]);
  if (row.cost_admission_policy !== null && row.cost_admission_policy !== "partial-return-restituted-v1") monetaryInvalid();
  if (!Array.isArray(row.events) || row.events.length !== row.row_version) monetaryInvalid();
  const events: MonetaryStockEvent[] = [];
  for (const [index, item] of row.events.entries()) {
    const event = monetaryObject(item, eventFields);
    if (monetaryInteger(event.version, 1024, 1) !== index + 1) monetaryInvalid();
    for (const key of ["actor_id", "operation", "status", "audit_event_id"]) monetaryText(event[key]); monetaryText(event.reason, 500);
    if (event.operation === "cancel") {
      if (index !== (row.events as unknown[]).length - 1 || !index || !["Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed"].includes(events[index - 1].status) || event.status !== "Cancelled") monetaryInvalid();
    } else if (index < firstEvents.length) {
      if (event.operation !== firstEvents[index][0] || event.status !== firstEvents[index][1]) monetaryInvalid();
    } else if (event.operation === "prepare-collection") {
      if (!["Invoiced", "Paid"].includes(events[index - 1].status) || event.status !== "CollectionPrepared") monetaryInvalid();
    } else if (event.operation === "review-collection") {
      if (events[index - 1].status !== "CollectionPrepared" || event.status !== "CollectionReviewed" || event.actor_id === events[index - 1].actor_id) monetaryInvalid();
    } else if (event.operation !== "collect" || events[index - 1].status !== "CollectionReviewed" || !["Invoiced", "Paid"].includes(event.status as string)
        || [events[index - 1].actor_id, events[index - 2].actor_id].includes(event.actor_id as string)) monetaryInvalid();
    events.push(event as unknown as MonetaryStockEvent);
  }
  if (events.at(-1)?.status !== row.status || row.created_by !== events[0].actor_id) monetaryInvalid();
  const byOperation = new Map(events.map(event => [event.operation, event]));
  if (row.approved_by !== (byOperation.get("approve")?.actor_id ?? null) || row.approved_by !== null && row.approved_by === row.created_by) monetaryInvalid();
  const issued = byOperation.has("prepare-issue"), delivered = byOperation.has("deliver"), invoicing = byOperation.has("prepare-invoice"), recognized = byOperation.has("invoice");
  if ((row.issue_digest !== null) !== issued || (row.functional_cogs_minor !== null) !== issued
      || row.issue_preparer_id !== (byOperation.get("prepare-issue")?.actor_id ?? null) || row.issue_reviewer_id !== (byOperation.get("review-issue")?.actor_id ?? null)
      || row.issue_reviewer_id !== null && row.issue_reviewer_id === row.issue_preparer_id) monetaryInvalid();
  if (issued) {
    const cost = monetaryMinor(row.functional_cogs_minor);
    if (cost === "0" && row.cost_admission_policy !== "partial-return-restituted-v1" || (row.cogs_entry_id !== null) !== (cost !== "0")
        || (row.cogs_effect_id !== null) !== (delivered && cost !== "0")) monetaryInvalid();
  } else if ([row.cogs_entry_id, row.cogs_effect_id, row.cost_admission_policy].some(item => item !== null)) monetaryInvalid();
  if ((row.movement_id !== null) !== delivered || (row.valuation_id !== null) !== delivered
      || delivered && [row.issue_preparer_id, row.issue_reviewer_id].includes(byOperation.get("deliver")?.actor_id)
      || (row.monetary_origin !== null) !== invoicing || (row.balance !== null) !== recognized) monetaryInvalid();
  if (invoicing) {
    const source = origin(row.monetary_origin, row, identity);
    if (source.preparer_actor_id !== byOperation.get("prepare-invoice")?.actor_id || source.reviewer_actor_id !== (byOperation.get("review-invoice")?.actor_id ?? null)
        || source.posted_actor_id !== (byOperation.get("invoice")?.actor_id ?? null)) monetaryInvalid();
    row.monetary_origin = source;
  }
  if (recognized) {
    const balance = monetaryObject(row.balance, monetaryBalanceFields); validateMonetaryBalance(balance, identity);
    const source = row.monetary_origin as MonetaryOrigin;
    if (balance.schema_version !== "stock-monetary-balance-v1" || balance.transaction_original_gross_minor !== source.transaction_gross_minor
        || balance.functional_original_gross_minor !== source.functional_gross_minor) monetaryInvalid();
    row.balance = balance;
  }
  if ((row.collection !== null) !== byOperation.has("prepare-collection")) monetaryInvalid();
  if (row.collection !== null) {
    if (!recognized) monetaryInvalid();
    const current = collection(row.collection, identity);
    const expectedStatus = row.status === "CollectionPrepared" ? "Prepared" : row.status === "CollectionReviewed" ? "Reviewed" : "Posted";
    if (current.status !== expectedStatus || current.preparer_actor_id !== byOperation.get("prepare-collection")?.actor_id
        || current.status !== "Prepared" && current.reviewer_actor_id !== byOperation.get("review-collection")?.actor_id
        || current.status === "Posted" && current.posted_actor_id !== byOperation.get("collect")?.actor_id
        || current.status !== "Posted" && (row.balance as MonetaryBalanceFields).active_plan_id !== current.id) monetaryInvalid();
    row.collection = current;
  }
  return { ...row, events } as unknown as MonetaryStock;
}
export async function loadMonetaryStockPage(session: BrowserAdminSession, scope: FinanceScope, signal?: AbortSignal): Promise<MonetaryStock[]> {
  const row = monetaryObject(await monetaryRequest(session, scope, `${monetaryStockRoot}/orders`, undefined, signal), ["orders"]);
  if (!Array.isArray(row.orders) || row.orders.length > 100) monetaryInvalid();
  const orders = row.orders.map(value => parseMonetaryStock(value, scope));
  if (new Set(orders.map(value => value.id)).size !== orders.length) monetaryInvalid();
  return orders;
}
export async function loadMonetaryStock(session: BrowserAdminSession, scope: FinanceScope, id: string, signal?: AbortSignal): Promise<MonetaryStock> {
  return parseMonetaryStock(await monetaryRequest(session, scope, `${monetaryStockRoot}/orders/${encodeURIComponent(id)}`, undefined, signal), scope, id);
}
export async function loadMonetaryStockOptions(session: BrowserAdminSession, scope: FinanceScope, signal?: AbortSignal): Promise<MonetaryStockOptions> {
  const specs = [["customers", 100, ["customer_code", "name", "currency_code"]], ["periods", 50, ["id", "name", "start_date", "end_date"]],
    ["journals", 100, ["journal_code", "name", "currency_code"]], ["accounts", 200, ["account_code", "name", "account_type", "chart_id"]],
    ["items", 100, ["item_code", "name", "uom_code", "decimal_places"]], ["warehouses", 100, ["warehouse_code", "name"]],
    ["locations", 200, ["warehouse_code", "location_code", "name"]], ["policies", 100, ["policy_code", "name", "journal_code"]]] as const;
  const row = monetaryObject(await monetaryRequest(session, scope, `${monetaryStockRoot}/options`, undefined, signal), specs.map(spec => spec[0]));
  for (const [name, maximum, fields] of specs) {
    const values = row[name]; if (!Array.isArray(values) || values.length > maximum) monetaryInvalid();
    row[name] = values.map(value => {
      const item = monetaryObject(value, fields);
      for (const key of fields) if (key !== "decimal_places") monetaryText(item[key], 500);
      if (name === "items") monetaryInteger(item.decimal_places, 6);
      if (name === "accounts" && !["Asset", "Income", "Expense", "Liability"].includes(item.account_type as string)) monetaryInvalid();
      if (["customers", "journals"].includes(name) && !/^[A-Z]{3}$/.test(item.currency_code as string)) monetaryInvalid();
      if (name === "periods" && monetaryDate(item.start_date) > monetaryDate(item.end_date)) monetaryInvalid();
      return item;
    });
  }
  return row as unknown as MonetaryStockOptions;
}
export function monetaryStockMatchesCommand(order: MonetaryStock, command: PreparedScopedCommand): boolean {
  if (command.path === `${monetaryStockRoot}/orders`) return order.row_version === 1 && order.status === "Draft"
    && ["number", "customer_code", "customer_reference", "item_code", "warehouse_code", "location_code", "unit_price_minor", "description", "order_date", "discount_basis_points"]
      .every(key => order[key as keyof MonetaryStock] === command.body[key]) && order.transaction_policy.currency_code === command.body.currency_code
    && typeof command.body.quantity === "string" && quoted(command.body.quantity, order.quantity_precision, order.unit_price_minor, order.discount_basis_points, true).quantity.toString() === order.quantity_scaled;
  if (typeof command.body.expected_version !== "number" || order.row_version !== command.body.expected_version + 1) return false;
  const ending = command.path.slice(`${monetaryStockRoot}/orders/${encodeURIComponent(order.id)}/`.length);
  const expected: Record<string, string> = { submit: "Submitted", approve: "Approved", reserve: "Reserved", "issue/prepare": "IssuePrepared", "issue/review": "IssueReviewed", deliver: "Delivered",
    "invoice/prepare": "InvoicePrepared", "invoice/review": "InvoiceReviewed", "invoice/post": "Invoiced", "collection/prepare": "CollectionPrepared", "collection/review": "CollectionReviewed", cancel: "Cancelled" };
  if (!command.path.startsWith(`${monetaryStockRoot}/orders/${encodeURIComponent(order.id)}/`)) return false;
  const operations: Record<string, string> = { "issue/prepare": "prepare-issue", "issue/review": "review-issue", "invoice/prepare": "prepare-invoice", "invoice/review": "review-invoice", "invoice/post": "invoice",
    "collection/prepare": "prepare-collection", "collection/review": "review-collection", "collection/post": "collect" };
  const event = order.events.at(-1);
  if (!event || event.operation !== (operations[ending] ?? ending) || event.reason !== command.body.reason) return false;
  if (ending === "invoice/prepare") {
    const origin = order.monetary_origin, taxes = command.body.taxes;
    if (!origin || origin.invoice_number !== "FX1-" + command.body.invoice_number
        || (["invoice_date", "due_date", "journal_code", "period_id", "receivable_account_code", "revenue_account_code", "cash_account_code", "refund_liability_account_code", "gain_account_code", "loss_account_code", "country_code", "transaction_class"] as const).some(key => origin[key] !== command.body[key])
        || !sameRate(origin.original_rate, command.body.original_rate) || !Array.isArray(taxes) || taxes.length !== origin.tax_components.length) return false;
    const fields = ["policy_id", "country_code", "transaction_class", "effective_from", "effective_to", "rate", "account_code", "source", "version"] as const;
    if (origin.tax_components.some((tax, index) => { const requested = taxes[index]; return !requested || typeof requested !== "object" || Array.isArray(requested) || fields.some(key => tax[key] !== requested[key]); })) return false;
  }
  if (ending === "collection/prepare") {
    const collection = order.collection;
    if (!collection || collection.receipt_number !== "FX1-" + command.body.receipt_number || collection.amount_minor !== command.body.amount_minor
        || collection.receipt_date !== command.body.receipt_date || collection.period_id !== command.body.period_id || !sameRate(collection.settlement_rate, command.body.settlement_rate)) return false;
  }
  return ending === "collection/post" ? ["Invoiced", "Paid"].includes(order.status) : Object.hasOwn(expected, ending) && order.status === expected[ending];
}
function sameRate(value: MonetaryRate | null, requested: unknown): boolean {
  return value === null ? requested === null : Boolean(requested && typeof requested === "object" && !Array.isArray(requested)
    && (["rate", "source", "effective_at"] as const).every(key => value[key] === (requested as Record<string, unknown>)[key]));
}
export async function executeMonetaryStockCommand(session: BrowserAdminSession, scope: FinanceScope, command: PreparedScopedCommand): Promise<MonetaryStock> {
  const result = parseMonetaryStock(await monetaryRequest(session, scope, command.path, command), scope);
  if (!monetaryStockMatchesCommand(result, command)) monetaryInvalid();
  return result;
}
