import { isMonetaryPath } from "./monetary-paths";

/** A prepared command binds one route and exact payload until its outcome is known.
 * Keep this object for transport/5xx/response-contract retries. Never regenerate its
 * key or expected version after a possibly committed request.
 */
export type ScopedJsonValue = string | number | boolean | null | readonly ScopedJsonValue[] | { readonly [key: string]: ScopedJsonValue };

export interface PreparedScopedCommand {
  readonly path: string;
  readonly body: Readonly<Record<string, ScopedJsonValue> & { command_id: string }>;
}

export function isPartialReturnV2Path(path: string, mutation: boolean): boolean {
  const root = "/api/v2/customer-partial-returns", id = "CR(?:2|F2|2R|F2R)-[a-f0-9]{32}";
  if (mutation) return path === `${root}/plans` || new RegExp(`^${root}/plans/${id}/(?:review|post|cancel)$`).test(path)
    || new RegExp(`^${root}/plans/CR2-[a-f0-9]{32}/refunds$`).test(path)
    || new RegExp(`^${root}/plans/CR(?:2|F2)-[a-f0-9]{32}/reversals$`).test(path);
  if (path === `${root}/plans` || new RegExp(`^${root}/plans/${id}$`).test(path)) return true;
  const source = new RegExp(`^${root}/sources/([^/?#]+)/balance$`).exec(path);
  if (!source) return false;
  try {
    const value = decodeURIComponent(source[1]);
    return Boolean(value && value.length <= 160 && value === value.trim() && ![".", ".."].includes(value)
      && !/[\\/?#\x00-\x1f\x7f]/.test(value) && encodeURIComponent(value) === source[1]);
  } catch { return false; }
}

export function prepareScopedCommand(path: string, body: Record<string, ScopedJsonValue>): PreparedScopedCommand {
  if ((!path.startsWith("/api/v1/") && !isPartialReturnV2Path(path, true) && !isMonetaryPath(path, true)) || path.includes("?") || Object.hasOwn(body, "command_id")) throw new Error("scoped_command_invalid");
  let nodes = 0;
  const ancestors = new Set<object>();
  function copy(value: ScopedJsonValue, depth: number): ScopedJsonValue {
    if (++nodes > 20000 || depth > 12) throw new Error("scoped_command_invalid");
    if (value === null || typeof value === "boolean" || typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER) return value;
    if (typeof value !== "object" || ancestors.has(value)) throw new Error("scoped_command_invalid");
    ancestors.add(value);
    try {
      if (Array.isArray(value)) {
        if (value.length > 20000 || Object.keys(value).length !== value.length) throw new Error("scoped_command_invalid");
        return Object.freeze(value.map((item) => copy(item, depth + 1)));
      }
      if (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) throw new Error("scoped_command_invalid");
      const result: Record<string, ScopedJsonValue> = {};
      for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(value))) {
        if (!descriptor.enumerable || !("value" in descriptor) || ["__proto__", "constructor", "prototype"].includes(key)) throw new Error("scoped_command_invalid");
        result[key] = copy(descriptor.value as ScopedJsonValue, depth + 1);
      }
      return Object.freeze(result);
    } finally { ancestors.delete(value); }
  }
  const captured = copy(body, 0) as Readonly<Record<string, ScopedJsonValue>>;
  if (JSON.stringify(captured).length > 2000000) throw new Error("scoped_command_invalid");
  return Object.freeze({ path, body: Object.freeze({ ...captured, command_id: crypto.randomUUID() }) });
}
