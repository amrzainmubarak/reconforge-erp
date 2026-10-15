/** Fixed protocol routes. No body/header selector may upgrade an old source. */
export const monetaryStockRoot = "/api/v2/stock-sales";
export const monetaryPartialRoot = "/api/v3/customer-partial-returns";

function segment(value: string): boolean {
  try {
    const decoded = decodeURIComponent(value);
    return Boolean(decoded && decoded.length <= 160 && decoded === decoded.trim() && ![".", ".."].includes(decoded)
      && !/[\\/?#\x00-\x1f\x7f]/.test(decoded) && encodeURIComponent(decoded) === value);
  } catch { return false; }
}

export function isMonetaryStockPath(path: string, mutation: boolean): boolean {
  const root = monetaryStockRoot;
  if (path === `${root}/orders`) return true;
  if (!mutation && path === `${root}/options`) return true;
  const match = new RegExp(`^${root}/orders/([^/?#]+)(?:/(submit|approve|reserve|deliver|cancel|(?:issue|invoice|collection)/(?:prepare|review|post)))?$`).exec(path);
  if (!match || !segment(match[1])) return false;
  if (!mutation) return match[2] === undefined;
  return Boolean(match[2] && match[2] !== "issue/post");
}

export function isMonetaryPartialPath(path: string, mutation: boolean): boolean {
  const root = monetaryPartialRoot, id = "CR(?:3|F3|3R|F3R)-[a-f0-9]{32}";
  if (path === `${root}/plans`) return true;
  if (mutation) return new RegExp(`^${root}/plans/${id}/(?:review|post|cancel)$`).test(path)
    || new RegExp(`^${root}/plans/CR3-[a-f0-9]{32}/refunds$`).test(path)
    || new RegExp(`^${root}/plans/CR(?:3|F3)-[a-f0-9]{32}/reversals$`).test(path);
  if (new RegExp(`^${root}/plans/${id}$`).test(path)) return true;
  const match = new RegExp(`^${root}/sources/([^/?#]+)/balance$`).exec(path);
  return Boolean(match && segment(match[1]));
}

export function isMonetaryPath(path: string, mutation: boolean): boolean {
  return isMonetaryStockPath(path, mutation) || isMonetaryPartialPath(path, mutation);
}
