import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { retainBrowserError, retainCaptureFailure } from "../../live/monetary-capture-diagnostics";

const folders: string[] = [];
const original = "native-customer-partial-return-monetary-originals";
const failed = "native-customer-partial-return-monetary-failed-observation-originals";
const checkpoint = { case: "foreign", capture: 5, observation: "CommittedCapture" } as const;

it("retains browser exception bytes outside financial originals with a finite private capacity", () => {
  const f = fixture(), raw = "private-browser-value-".repeat(1000);
  for (let index = 0; index < 16; ++index) expect(retainBrowserError(raw, f.root)).toBe(true);
  expect(retainBrowserError(raw, f.root)).toBe(false);
  expect(readdirSync(f.root)).toEqual([]);
  const folder = join(f.base, "monetary-browser-runtime-errors");
  for (const name of readdirSync(folder)) expect(readFileSync(join(folder, name))).toEqual(Buffer.from(raw).subarray(0, 16384));
});

it("refuses browser diagnostic traversal and linked private ancestors", () => {
  const f = fixture(), target = join(f.base, "browser-target"), link = join(f.base, "browser-link");
  mkdirSync(target); symlinkSync(target, link, process.platform === "win32" ? "junction" : "dir");
  expect(retainBrowserError("private-value", join(link, original, "foreign"))).toBe(false);
  expect(retainBrowserError("private-value", "relative/foreign")).toBe(false);
  expect(readdirSync(target)).toEqual([]);
});
function fixture() {
  const base = mkdtempSync(join(tmpdir(), "monetary-capture-test-")); folders.push(base);
  const root = join(base, original, "foreign"); mkdirSync(root, { recursive: true });
  return { base, root, failed: join(base, failed, "foreign") };
}
afterEach(() => {
  for (const path of folders.splice(0)) {
    if (!resolve(path).startsWith(resolve(tmpdir()) + "/") && !resolve(path).startsWith(resolve(tmpdir()) + "\\")) throw new Error("Temporary fixture boundary refused.");
    rmSync(path, { recursive: true, force: true });
  }
});
function summary(error: Error) { return JSON.parse(error.message.slice(error.message.indexOf("{") )); }

describe("private monetary capture child diagnostics", () => {
  it("keeps exact raw streams private and throws only typed metadata without original message, argv or cause", () => {
    const f = fixture(), hidden = "do-not-publish" + "-private-value";
    const stdout = Buffer.from("postgresql://user:" + hidden + "@host/db"), stderr = Buffer.from("authorization: " + hidden);
    const error = retainCaptureFailure({ status: 2, signal: null, message: hidden, stack: hidden, command: hidden, cause: hidden, stdout, stderr }, checkpoint, f.root);
    expect(error.name).toBe("MonetaryCaptureChildFailure"); expect(String(error)).not.toContain(hidden); expect(error.stack).not.toContain(hidden); expect(error.cause).toBeUndefined();
    const safe = summary(error); expect(safe.status).toBe(2); expect(safe.cause).toBe("capture_child_failed"); expect(safe.private_streams_retained).toBe(true);
    expect(safe.stdout.sha256).toBe(createHash("sha256").update(stdout).digest("hex"));
    const files = readdirSync(f.failed); expect(files).toHaveLength(3);
    expect(readFileSync(join(f.failed, files.find(name => name.endsWith(".stdout.bin"))!))).toEqual(stdout);
    expect(readFileSync(join(f.failed, files.find(name => name.endsWith(".stderr.bin"))!))).toEqual(stderr);
    expect(readFileSync(join(f.failed, files.find(name => name.endsWith(".json"))!), "utf8")).not.toContain(hidden);
  });
  it("accepts only the closed producer category, stage and trace identity", () => {
    const f = fixture();
    const producer = { schema_version: "monetary-capture-python-failure-v1", cause: "statement_cancelled", stage: "snapshot_read", line: 130,
      trace_retained: true, trace_bytes: 700, trace_sha256: "a".repeat(64), trace_truncated: false };
    const error = retainCaptureFailure({ status: 2, stdout: Buffer.from(JSON.stringify(producer)), stderr: Buffer.alloc(0) }, checkpoint, f.root);
    expect(summary(error).producer).toEqual(producer); expect(summary(error).cause).toBe("statement_cancelled");
    producer.cause = "private-untrusted-message";
    const refused = retainCaptureFailure({ status: 2, stdout: Buffer.from(JSON.stringify(producer)) }, checkpoint, f.root);
    expect(summary(refused).producer).toBeNull(); expect(refused.message).not.toContain(producer.cause);
  });
  it("records bounded prefixes honestly and maps actual timeout metadata without retry", () => {
    const f = fixture(), stdout = Buffer.alloc(20000, 65), stderr = Buffer.alloc(21000, 66);
    const safe = summary(retainCaptureFailure({ code: "ETIMEDOUT", status: null, signal: "SIGTERM", stdout, stderr }, checkpoint, f.root));
    expect(safe.cause).toBe("capture_timeout"); expect(safe.signal).toBe("SIGTERM"); expect(safe.status).toBeNull();
    expect(safe.stdout).toMatchObject({ bytes: 16384, observed_bytes: 20000, truncated: true });
    expect(safe.stderr).toMatchObject({ bytes: 16384, observed_bytes: 21000, truncated: true });
    for (const name of readdirSync(f.failed).filter(name => name.endsWith(".bin"))) expect(readFileSync(join(f.failed, name))).toHaveLength(16384);
  });
  it("refuses unexpected checkpoint and unsafe private ancestors without exposing their values", () => {
    const f = fixture();
    expect(retainCaptureFailure({ message: "private-value" }, { ...checkpoint, capture: 12 }, f.root).message).toBe("Monetary capture diagnostic checkpoint refused.");
    const target = join(f.base, "target"); mkdirSync(target); const link = join(f.base, "linked");
    symlinkSync(target, link, process.platform === "win32" ? "junction" : "dir");
    const root = join(link, original, "foreign");
    const safe = summary(retainCaptureFailure({ status: 2, stdout: Buffer.from("private-value") }, checkpoint, root));
    expect(safe.private_streams_retained).toBe(false); expect(JSON.stringify(safe)).not.toContain("private-value"); expect(readdirSync(target)).toEqual([]);
  });
  it("does not publish untyped status or arbitrary signal data", () => {
    const f = fixture();
    const safe = summary(retainCaptureFailure({ status: true, signal: "private-value", code: "private-value" }, checkpoint, f.root));
    expect(safe.status).toBeNull(); expect(safe.signal).toBeNull(); expect(JSON.stringify(safe)).not.toContain("private-value");
  });
  it("projects only the three checkpoint fields even when the runtime object has additional data", () => {
    const f = fixture(), extra = { ...checkpoint, secret: "private-extra-field" };
    const safe = summary(retainCaptureFailure({ status: 2 }, extra, f.root));
    expect(safe.case).toBe("foreign"); expect(safe.capture).toBe(5); expect(safe.observation).toBe("CommittedCapture");
    expect(JSON.stringify(safe)).not.toContain(extra.secret); expect(safe).not.toHaveProperty("secret");
  });
});
