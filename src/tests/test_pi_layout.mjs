/**
 * Pi widget indent + cost-gray.
 * Run: node src/tests/test_pi_layout.mjs
 */
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const src = join(dirname(fileURLToPath(import.meta.url)), "../backend/pi/extension.ts")
const raw = readFileSync(src, "utf8")
assert.match(raw, /38;2;255;240;242/)
assert.match(raw, /38;2;246;239;255/)
assert.match(raw, /COLOR_MS = 90/)
assert.match(raw, /return ` \$\{color\}/)
console.log("ok")
