/** A prepared command binds one route and exact payload until its outcome is known.
 * Keep this object for transport/5xx/response-contract retries. Never regenerate its
 * key or expected version after a possibly committed request.
 */
export interface PreparedScopedCommand {
  readonly path: string;
  readonly body: Readonly<Record<string, string | number>>;
}

export function prepareScopedCommand(path: string, body: Record<string, string | number>): PreparedScopedCommand {
  if (!path.startsWith("/api/v1/") || path.includes("?") || Object.hasOwn(body, "command_id")) throw new Error("scoped_command_invalid");
  return Object.freeze({ path, body: Object.freeze({ ...body, command_id: crypto.randomUUID() }) });
}
