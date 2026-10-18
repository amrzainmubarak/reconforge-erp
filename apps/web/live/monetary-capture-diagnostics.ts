import { createHash, randomUUID } from "node:crypto";
import { lstatSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, parse } from "node:path";

const family = "native-customer-partial-return-monetary-originals";
const failedFamily = "native-customer-partial-return-monetary-failed-observation-originals";
const limit = 16_384;
const causes = new Set(["observation_contract_refused", "observer_failed", "statement_cancelled", "permission_denied",
  "native_constraint_refused", "lock_unavailable", "deadlock_refused", "serialization_refused", "database_failure"]);
const stages = new Set(["capture_dispatch", "custody_boundary", "custody_membership", "existing_capture_decode", "snapshot_read",
  "posted_plan_affinity", "observation_business_binding", "refused_request_binding", "capture_contract", "packet_assembly"]);
const observations = new Set(["CommittedCapture", "RetainedReplay", "ScopeRefusal", "ActiveValuationRefusal", "FinalRead"]);
const signals = new Set(["SIGTERM", "SIGKILL", "SIGABRT", "SIGINT", "SIGSEGV", "SIGBREAK"]);
const hash = (value: Buffer) => createHash("sha256").update(value).digest("hex");

export type CaptureCheckpoint = { case: "identity" | "foreign"; capture: number; observation: string };

/** Browser exceptions can include source values: retain bounded bytes privately only. */
export function retainBrowserError(message: string, custodyRoot: string): boolean {
  try {
    directory(custodyRoot);
    if (!["identity", "foreign"].includes(basename(custodyRoot)) || basename(dirname(custodyRoot)) !== family) return false;
    const folder = join(dirname(dirname(custodyRoot)), "monetary-browser-runtime-errors");
    directory(folder); mkdirSync(folder, { recursive: true, mode: 0o700 }); directory(folder);
    const members = readdirSync(folder);
    if (members.length >= 16 || members.some(name => { const stat = lstatSync(join(folder, name)); return stat.isSymbolicLink() || !stat.isFile(); })) return false;
    writeFileSync(join(folder, randomUUID() + ".bin"), Buffer.from(message).subarray(0, limit), { flag: "wx", mode: 0o600 });
    return true;
  } catch { return false; }
}

function directory(path: string): void {
  if (!isAbsolute(path) || path.split(/[\\/]/).includes("..")) throw new Error("Private capture diagnostic boundary refused.");
  for (let item = path; ; item = dirname(item)) {
    const stat = lstatSync(item, { throwIfNoEntry: false });
    if (stat) {
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error("Private capture diagnostic boundary refused.");
    }
    if (item === parse(item).root) break;
  }
}

function buffer(value: unknown): Buffer {
  return Buffer.isBuffer(value) ? value : typeof value === "string" ? Buffer.from(value) : Buffer.alloc(0);
}

function producer(raw: Buffer): Record<string, unknown> | null {
  if (raw.length > 2048) return null;
  try {
    const value: unknown = JSON.parse(raw.toString("utf8"));
    if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
    const row = value as Record<string, unknown>;
    const keys = ["schema_version", "cause", "stage", "line", "trace_retained", "trace_bytes", "trace_sha256", "trace_truncated"].sort();
    if (JSON.stringify(Object.keys(row).sort()) !== JSON.stringify(keys) || row.schema_version !== "monetary-capture-python-failure-v1"
      || typeof row.cause !== "string" || !causes.has(row.cause) || typeof row.stage !== "string" || !stages.has(row.stage)
      || !Number.isInteger(row.line) || (row.line as number) < 0 || (row.line as number) > 10000
      || typeof row.trace_retained !== "boolean" || typeof row.trace_truncated !== "boolean"
      || !Number.isInteger(row.trace_bytes) || (row.trace_bytes as number) < 0 || (row.trace_bytes as number) > 8192
      || (row.trace_retained ? !(typeof row.trace_sha256 === "string" && /^[a-f0-9]{64}$/.test(row.trace_sha256) && (row.trace_bytes as number) > 0)
        : row.trace_sha256 !== null || row.trace_bytes !== 0 || row.trace_truncated !== false)) return null;
    return row;
  } catch { return null; }
}

/** Never attach the original ExecException: its message/argv/streams may contain private data. */
export function retainCaptureFailure(error: unknown, checkpoint: CaptureCheckpoint, custodyRoot: string): Error {
  if (!["identity", "foreign"].includes(checkpoint.case) || !Number.isInteger(checkpoint.capture) || checkpoint.capture < 0
    || checkpoint.capture >= (checkpoint.case === "foreign" ? 12 : 10) || !observations.has(checkpoint.observation)) {
    return new Error("Monetary capture diagnostic checkpoint refused.");
  }
  const row = error !== null && typeof error === "object" ? error as Record<string, unknown> : {};
  const streams = { stdout: buffer(row.stdout), stderr: buffer(row.stderr) };
  const retained = { stdout: streams.stdout.subarray(0, limit), stderr: streams.stderr.subarray(0, limit) };
  const status = Number.isInteger(row.status) && (row.status as number) >= -2147483648 && (row.status as number) <= 2147483647 ? row.status : null;
  const lower = status === 2 ? producer(streams.stdout) : null;
  const signal = typeof row.signal === "string" && signals.has(row.signal) ? row.signal : null;
  const cause = row.code === "ETIMEDOUT" ? "capture_timeout" : row.code === "ENOBUFS" ? "capture_output_limit"
    : row.code === "ENOENT" || row.code === "EACCES" ? "capture_spawn_failed" : lower?.cause ?? "capture_child_failed";
  const summary = {
    schema_version: "monetary-capture-child-failure-v1", case: checkpoint.case, capture: checkpoint.capture,
    observation: checkpoint.observation, status, signal, cause,
    producer: lower, stdout: { bytes: retained.stdout.length, observed_bytes: streams.stdout.length, sha256: hash(retained.stdout), truncated: retained.stdout.length !== streams.stdout.length },
    stderr: { bytes: retained.stderr.length, observed_bytes: streams.stderr.length, sha256: hash(retained.stderr), truncated: retained.stderr.length !== streams.stderr.length },
    private_streams_retained: false,
  };
  try {
    directory(custodyRoot);
    if (basename(custodyRoot) !== checkpoint.case || basename(dirname(custodyRoot)) !== family) throw new Error("Private capture diagnostic boundary refused.");
    const folder = join(dirname(dirname(custodyRoot)), failedFamily, checkpoint.case);
    directory(folder);
    mkdirSync(folder, { recursive: true, mode: 0o700 });
    directory(folder);
    const members = readdirSync(folder);
    if (members.length > 13 || members.some(name => { const stat = lstatSync(join(folder, name)); return stat.isSymbolicLink() || !stat.isFile(); })) {
      throw new Error("Private capture diagnostic capacity refused.");
    }
    const name = "capture-child-" + randomUUID().replaceAll("-", "");
    writeFileSync(join(folder, name + ".stdout.bin"), retained.stdout, { flag: "wx", mode: 0o600 });
    writeFileSync(join(folder, name + ".stderr.bin"), retained.stderr, { flag: "wx", mode: 0o600 });
    summary.private_streams_retained = true;
    writeFileSync(join(folder, name + ".json"), JSON.stringify(summary) + "\n", { flag: "wx", mode: 0o600 });
    directory(folder);
  } catch { summary.private_streams_retained = false; }
  const failure = new Error("Monetary committed-row capture failed: " + JSON.stringify(summary));
  failure.name = "MonetaryCaptureChildFailure";
  return failure;
}
