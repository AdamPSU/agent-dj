/**
 * Lightweight checks for OpenCode chip truncation helpers.
 * Run: node src/tests/test_opencode_layout.mjs
 */
import assert from "node:assert/strict"
import { pathToFileURL } from "node:url"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { readFileSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..")
const src = join(root, "src/backend/opencode/plugin/src/index.tsx")

const raw = readFileSync(src, "utf8")
const start = raw.indexOf("/** Terminal column width")
const end = raw.indexOf("function loadRuntime")
assert.ok(start > 0 && end > start, "helpers block not found")

// Strip TS type annotations for plain Node ESM eval.
let helpers = raw.slice(start, end)
helpers = helpers
  .replaceAll("export function", "function")
  .replace(/: string/g, "")
  .replace(/: number/g, "")
  .replace(/: TickPayload \| null/g, "")
  .replace(/: Layout \| null/g, "")
  .replace(/\): Layout/g, ")")
  .replace(/\): number/g, ")")
  .replace(/\): string/g, ")")

const tmp = join(tmpdir(), `dj-layout-${process.pid}.mjs`)
writeFileSync(tmp, `${helpers}\nexport { displayColumns, ellipsize, layoutChip }\n`)

const mod = await import(pathToFileURL(tmp).href)
const { displayColumns, ellipsize, layoutChip } = mod

assert.equal(displayColumns("abc"), 3)
assert.equal(ellipsize("hello world", 8), "hello w…")
assert.equal(ellipsize("hi", 10), "hi")

const wide = layoutChip(
  {
    glyph: "♪",
    artists: "beabadoobee",
    name: "Take A Bite",
    progress: "0:17",
    duration: "2:38",
  },
  80,
)
assert.equal(wide.artists, "beabadoobee")
assert.equal(wide.name, "Take A Bite")
assert.equal(wide.time, "0:17/2:38")

const narrow = layoutChip(
  {
    glyph: "♪",
    artists: "beabadoobee",
    name: "Take A Bite Of Something Extremely Long",
    progress: "0:17",
    duration: "2:38",
  },
  28,
)
assert.ok(narrow.name.includes("…") || narrow.artists.includes("…"))
assert.equal(narrow.time, "0:17/2:38")

const tiny = layoutChip(
  {
    glyph: "♪",
    artists: "A",
    name: "B",
    progress: "1:00",
    duration: "2:00",
  },
  10,
)
assert.ok(tiny.time)

rmSync(tmp, { force: true })
console.log("ok")
