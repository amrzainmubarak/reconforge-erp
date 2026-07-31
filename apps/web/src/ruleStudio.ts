export type RuleStatus = "draft" | "tested" | "approved";

export interface RuleTestCase {
  id: string;
  left_amount: string;
  right_amount: string;
  expected_match: boolean;
}

export interface RuleSpec {
  schema_version: 1;
  reconciliation_id: string;
  strategy: "exact" | "tolerance";
  amount_tolerance: string;
  test_cases: RuleTestCase[];
}

export interface RuleTestResult {
  passed: boolean;
  digest: string;
  total: number;
  passedCount: number;
  failures: string[];
}

export interface ApprovalResult {
  status: "approved";
  version: number;
  reviewer: string;
  reason: string;
  testedDigest: string;
}

const amountPattern = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const identifierPattern = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const topLevelKeys = new Set(["schema_version", "reconciliation_id", "strategy", "amount_tolerance", "test_cases"]);
const caseKeys = new Set(["id", "left_amount", "right_amount", "expected_match"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertClosedKeys(value: Record<string, unknown>, allowed: Set<string>, label: string) {
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  if (extra.length) throw new Error(`${label} contains unsupported fields: ${extra.sort().join(", ")}.`);
}

export function parseRuleSpec(text: string): RuleSpec {
  if (new TextEncoder().encode(text).byteLength > 64 * 1024) throw new Error("Rule draft exceeds the 64 KiB safety limit.");
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error("Rule draft must be valid JSON."); }
  if (!isObject(value)) throw new Error("Rule draft must be a JSON object.");
  assertClosedKeys(value, topLevelKeys, "Rule draft");
  if (value.schema_version !== 1) throw new Error("schema_version must be 1.");
  if (typeof value.reconciliation_id !== "string" || !identifierPattern.test(value.reconciliation_id)) throw new Error("reconciliation_id is invalid.");
  if (value.strategy !== "exact" && value.strategy !== "tolerance") throw new Error("strategy must be exact or tolerance.");
  if (typeof value.amount_tolerance !== "string" || !amountPattern.test(value.amount_tolerance) || value.amount_tolerance.startsWith("-")) throw new Error("amount_tolerance must be non-negative exact decimal text.");
  if (!Array.isArray(value.test_cases) || value.test_cases.length < 1 || value.test_cases.length > 100) throw new Error("test_cases must contain 1-100 cases.");
  const ids = new Set<string>();
  const cases = value.test_cases.map((candidate, index): RuleTestCase => {
    if (!isObject(candidate)) throw new Error(`test_cases[${index}] must be an object.`);
    assertClosedKeys(candidate, caseKeys, `test_cases[${index}]`);
    if (typeof candidate.id !== "string" || !identifierPattern.test(candidate.id) || ids.has(candidate.id)) throw new Error(`test_cases[${index}].id is invalid or duplicated.`);
    ids.add(candidate.id);
    for (const key of ["left_amount", "right_amount"] as const) if (typeof candidate[key] !== "string" || !amountPattern.test(candidate[key])) throw new Error(`test_cases[${index}].${key} must be exact decimal text.`);
    if (typeof candidate.expected_match !== "boolean") throw new Error(`test_cases[${index}].expected_match must be boolean.`);
    return { id: candidate.id, left_amount: candidate.left_amount as string, right_amount: candidate.right_amount as string, expected_match: candidate.expected_match };
  });
  return { schema_version: 1, reconciliation_id: value.reconciliation_id, strategy: value.strategy, amount_tolerance: value.amount_tolerance, test_cases: cases };
}

function decimalParts(value: string): [bigint, number] {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = unsigned.split(".");
  const units = BigInt(`${whole}${fraction}`) * (negative ? -1n : 1n);
  return [units, fraction.length];
}

function withinTolerance(left: string, right: string, tolerance: string): boolean {
  const [leftUnits, leftScale] = decimalParts(left);
  const [rightUnits, rightScale] = decimalParts(right);
  const [toleranceUnits, toleranceScale] = decimalParts(tolerance);
  const scale = Math.max(leftScale, rightScale, toleranceScale);
  const expand = (units: bigint, currentScale: number) => units * (10n ** BigInt(scale - currentScale));
  const difference = expand(leftUnits, leftScale) - expand(rightUnits, rightScale);
  const absolute = difference < 0n ? -difference : difference;
  return absolute <= expand(toleranceUnits, toleranceScale);
}

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
}

export function canonicalRuleText(spec: RuleSpec): string {
  return JSON.stringify(stable(spec));
}

async function sha256(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export async function runRuleTests(text: string): Promise<RuleTestResult> {
  const spec = parseRuleSpec(text);
  const failures: string[] = [];
  for (const testCase of spec.test_cases) {
    const matched = spec.strategy === "exact"
      ? withinTolerance(testCase.left_amount, testCase.right_amount, "0")
      : withinTolerance(testCase.left_amount, testCase.right_amount, spec.amount_tolerance);
    if (matched !== testCase.expected_match) failures.push(testCase.id);
  }
  return { passed: failures.length === 0, digest: await sha256(canonicalRuleText(spec)), total: spec.test_cases.length, passedCount: spec.test_cases.length - failures.length, failures };
}

export function diffRuleSpecs(baselineText: string, draftText: string): string[] {
  const baseline = parseRuleSpec(baselineText) as unknown as Record<string, unknown>;
  const draft = parseRuleSpec(draftText) as unknown as Record<string, unknown>;
  const changes: string[] = [];
  const walk = (before: unknown, after: unknown, path: string) => {
    if (JSON.stringify(stable(before)) === JSON.stringify(stable(after))) return;
    if (isObject(before) && isObject(after)) {
      for (const key of [...new Set([...Object.keys(before), ...Object.keys(after)])].sort()) walk(before[key], after[key], path ? `${path}.${key}` : key);
    } else if (Array.isArray(before) && Array.isArray(after)) {
      for (let index = 0; index < Math.max(before.length, after.length); index += 1) walk(before[index], after[index], `${path}[${index}]`);
    } else changes.push(path);
  };
  walk(baseline, draft, "");
  return changes;
}

export function approveTestedRule(input: { version: number; author: string; reviewer: string; reason: string; currentDigest: string; testResult: RuleTestResult | null }): ApprovalResult {
  const author = input.author.trim().toLocaleLowerCase();
  const reviewer = input.reviewer.trim().toLocaleLowerCase();
  if (!reviewer) throw new Error("Reviewer is required.");
  if (author === reviewer) throw new Error("Author cannot approve their own rule draft.");
  if (!input.reason.trim()) throw new Error("Approval reason is required.");
  if (!input.testResult?.passed) throw new Error("The current rule draft must pass its tests before approval.");
  if (input.currentDigest !== input.testResult.digest) throw new Error("The tested rule digest does not match the current draft.");
  return { status: "approved", version: input.version, reviewer: input.reviewer.trim(), reason: input.reason.trim(), testedDigest: input.currentDigest };
}
