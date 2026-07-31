export const canonicalFields = ["transaction_id", "amount", "currency", "business_date"] as const;
export type CanonicalField = (typeof canonicalFields)[number];
export type ColumnMapping = Record<CanonicalField, string>;

export interface PreviewTable {
  headers: string[];
  rows: string[][];
  truncated: boolean;
}

export interface MappingIssue {
  row: number;
  field: CanonicalField;
  code: "missing_mapping" | "duplicate_mapping" | "missing_value" | "malformed_amount" | "invalid_currency" | "invalid_date";
  value: string;
}

const exactAmount = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const currency = /^[A-Z]{3}$/;
const businessDate = /^\d{4}-\d{2}-\d{2}$/;
const MAX_BYTES = 256 * 1024;
const MAX_ROWS = 200;
const MAX_COLUMNS = 100;

export function parsePreview(text: string): PreviewTable {
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new Error("Preview exceeds the 256 KiB safety limit.");
  if (text.includes("\0")) throw new Error("Preview contains a null byte.");
  const delimiter = text.includes("\t") && !text.includes(",") ? "\t" : ",";
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else field += character;
    } else if (character === '"' && field === "") quoted = true;
    else if (character === delimiter) { record.push(field); field = ""; }
    else if (character === "\n") {
      record.push(field.replace(/\r$/, ""));
      if (record.some((value) => value !== "")) records.push(record);
      record = []; field = "";
      if (records.length > MAX_ROWS + 1) break;
    } else field += character;
  }
  if (quoted) throw new Error("Preview contains an unclosed quoted field.");
  if (field !== "" || record.length > 0) {
    record.push(field.replace(/\r$/, ""));
    if (record.some((value) => value !== "")) records.push(record);
  }
  if (records.length < 2) throw new Error("Preview requires one header and at least one data row.");
  const headers = records[0].map((value) => value.trim());
  if (headers.length > MAX_COLUMNS) throw new Error("Preview exceeds the 100-column safety limit.");
  if (headers.some((value) => value === "")) throw new Error("Every source column requires a header.");
  if (new Set(headers).size !== headers.length) throw new Error("Source column headers must be unique.");
  const rows = records.slice(1, MAX_ROWS + 1).map((row) => headers.map((_, index) => row[index] ?? ""));
  return { headers, rows, truncated: records.length > MAX_ROWS + 1 };
}

export function validateMapping(table: PreviewTable, mapping: ColumnMapping): MappingIssue[] {
  const issues: MappingIssue[] = [];
  const indexByHeader = new Map(table.headers.map((header, index) => [header, index]));
  for (const field of canonicalFields) {
    if (!mapping[field] || !indexByHeader.has(mapping[field])) {
      issues.push({ row: 0, field, code: "missing_mapping", value: "" });
    }
  }
  const selected = canonicalFields.map((field) => mapping[field]).filter(Boolean);
  for (const field of canonicalFields) {
    if (mapping[field] && selected.filter((header) => header === mapping[field]).length > 1) {
      issues.push({ row: 0, field, code: "duplicate_mapping", value: mapping[field] });
    }
  }
  if (issues.length > 0) return issues;
  table.rows.forEach((row, rowIndex) => {
    canonicalFields.forEach((target) => {
      const value = row[indexByHeader.get(mapping[target]) as number].trim();
      if (value === "") issues.push({ row: rowIndex + 1, field: target, code: "missing_value", value });
      else if (target === "amount" && !exactAmount.test(value)) issues.push({ row: rowIndex + 1, field: target, code: "malformed_amount", value });
      else if (target === "currency" && !currency.test(value)) issues.push({ row: rowIndex + 1, field: target, code: "invalid_currency", value });
      else if (target === "business_date" && (!businessDate.test(value) || !isCalendarDate(value))) issues.push({ row: rowIndex + 1, field: target, code: "invalid_date", value });
    });
  });
  return issues;
}

function isCalendarDate(value: string): boolean {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function emptyMapping(): ColumnMapping {
  return { transaction_id: "", amount: "", currency: "", business_date: "" };
}
