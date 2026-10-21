import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const buf = readFileSync(new URL("../dist/cairn-widget.js", import.meta.url));
const gz = gzipSync(buf, { level: 9 }).length;
const budget = 60 * 1024;
console.log(`cairn-widget.js: ${(buf.length / 1024).toFixed(1)} KB, ${(gz / 1024).toFixed(1)} KB gzipped (budget 60 KB)`);
if (gz > budget) {
  console.error("Widget exceeds the 60 KB gzipped budget (PRD F1).");
  process.exit(1);
}
