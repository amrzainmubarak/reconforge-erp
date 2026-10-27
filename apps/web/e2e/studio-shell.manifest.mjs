import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = process.env.RECONFORGE_STUDIO_SHELL_OUT ?? fileURLToPath(new URL("../../../output/assurance-20261026/studio-shell/", import.meta.url));
const captures = readdirSync(root).filter(name => name.endsWith(".png")).sort().map(filename => {
  const bytes = readFileSync(`${root}/${filename}`);
  if (bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") throw new Error(`Invalid PNG: ${filename}`);
  return { filename, width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20), bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"), fileModifiedAtUTC: statSync(`${root}/${filename}`).mtime.toISOString() };
});
writeFileSync(`${root}/screenshot-manifest.json`, JSON.stringify({ generatedAtUTC: new Date().toISOString(), captures }, null, 2));
console.log(`Recorded raw dimensions and SHA-256 for ${captures.length} genuine PNG captures.`);
