/** @jsxImportSource @opentui/solid */
/** @jsxRuntime automatic */
import type { TuiPlugin, TuiSlotContext } from "@opencode-ai/plugin/tui"
import { createMemo, createSignal, onCleanup } from "solid-js"
import { useTerminalDimensions } from "@opentui/solid"
import { execFile } from "node:child_process"
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)
const REFRESH_MS = 500
const RUNTIME_PATH = join(homedir(), ".agent-dj", "opencode_runtime.json")

const C_DIM = "#6C7086"
const DEFAULT_PALETTE = ["#888888", "#C1C1C1", "#486E6F"] as const

// Leave room for model/agent labels on the left of the prompt row.
const WIDTH_FRACTION = 0.42
const MIN_CHIP_COLS = 12
const MAX_CHIP_COLS = 64

type RuntimeConfig = {
  command?: string[]
  env?: Record<string, string>
  palette?: string[]
}

type TickPayload = {
  glyph?: string
  artists?: string
  name?: string
  title?: string
  progress?: string
  duration?: string
  line?: string
}

type Layout = {
  glyph: string
  artists: string
  dash: string
  name: string
  dot: string
  time: string
  fallback: string
  structured: boolean
}

/** Terminal column width (ASCII=1, most non-ASCII≈2). VS15/VS16 = 0. */
export function displayColumns(value: string): number {
  let width = 0
  for (const ch of value) {
    const cp = ch.codePointAt(0) ?? 0
    // Variation selectors (text/emoji presentation) are zero-width.
    if (cp >= 0xfe00 && cp <= 0xfe0f) continue
    width += cp > 0xff ? 2 : 1
  }
  return width
}

/** Truncate to max columns, appending … when cut. */
export function ellipsize(value: string, maxColumns: number): string {
  if (maxColumns <= 0) return ""
  if (displayColumns(value) <= maxColumns) return value
  if (maxColumns === 1) return "…"
  const budget = maxColumns - 1
  let out = ""
  let used = 0
  for (const ch of value) {
    const cp = ch.codePointAt(0) ?? 0
    const w = cp > 0xff ? 2 : 1
    if (used + w > budget) break
    out += ch
    used += w
  }
  return out ? `${out}…` : "…"
}

/**
 * Fit chip into maxCols. Prefer keeping time + glyph; truncate song first, then artist.
 */
export function layoutChip(
  payload: TickPayload | null,
  maxCols: number,
): Layout | null {
  if (!payload) return null
  const glyph = payload.glyph || "♪\uFE0E"
  const artists = payload.artists || ""
  const name = payload.name || ""
  const progress = payload.progress || ""
  const duration = payload.duration || ""
  const time = progress && duration ? `${progress}/${duration}` : ""
  const structured = Boolean((artists || name) && time)

  if (!structured) {
    const line = payload.line || ""
    if (!line) return null
    return {
      glyph: "",
      artists: "",
      dash: "",
      name: "",
      dot: "",
      time: "",
      fallback: ellipsize(line, maxCols),
      structured: false,
    }
  }

  const gaps = 5
  const fixed =
    displayColumns(glyph) +
    displayColumns("—") +
    displayColumns("·") +
    displayColumns(time) +
    gaps

  let budget = maxCols - fixed
  if (budget < 2) {
    const t = ellipsize(time, maxCols)
    if (!t) return null
    return {
      glyph: "",
      artists: "",
      dash: "",
      name: "",
      dot: "",
      time: t,
      fallback: "",
      structured: true,
    }
  }

  let a = artists
  let n = name
  const totalText = displayColumns(a) + displayColumns(n)
  if (totalText > budget) {
    const minSong = Math.min(4, Math.max(0, budget - 3))
    const maxSong = Math.max(
      minSong,
      budget - Math.min(displayColumns(a), Math.floor(budget * 0.45)),
    )
    n = ellipsize(n, maxSong)
    budget -= displayColumns(n)
    a = ellipsize(a, Math.max(0, budget))
  }

  return {
    glyph,
    artists: a,
    dash: a || n ? "—" : "",
    name: n,
    dot: "·",
    time,
    fallback: "",
    structured: true,
  }
}

function loadRuntime(): RuntimeConfig {
  try {
    const raw = readFileSync(RUNTIME_PATH, "utf8")
    const parsed = JSON.parse(raw) as RuntimeConfig
    return parsed && typeof parsed === "object" ? parsed : {}
  } catch {
    return {}
  }
}

async function tickPayload(): Promise<TickPayload | null> {
  const runtime = loadRuntime()
  const home = process.env.HOME || homedir()
  const command =
    Array.isArray(runtime.command) && runtime.command.length > 0
      ? runtime.command
      : [join(home, ".local/bin/dj"), "tick", "--json"]
  const [bin, ...args] = command
  if (!bin) return null
  try {
    const { stdout } = await execFileAsync(bin, args, {
      timeout: 5000,
      windowsHide: true,
      maxBuffer: 64 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        PATH: `${join(home, ".local/bin")}:${process.env.PATH ?? ""}`,
        ...(runtime.env ?? {}),
        NO_COLOR: "1",
        DJ_TICK_FORMAT: "json",
      },
    })
    const raw = String(stdout || "").trim()
    if (!raw.startsWith("{")) return null
    return JSON.parse(raw) as TickPayload
  } catch {
    return null
  }
}

function resolvePalette(runtime: RuntimeConfig): [string, string, string] {
  const raw = runtime.palette
  const out = [...DEFAULT_PALETTE] as [string, string, string]
  if (!Array.isArray(raw)) return out
  for (let i = 0; i < 3; i++) {
    const v = String(raw[i] ?? "").trim()
    if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(v)) {
      out[i] = v.length === 4
        ? `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`
        : v
    }
  }
  return out
}

function SpotifyChip() {
  const [payload, setPayload] = createSignal<TickPayload | null>(null)
  const [palette, setPalette] = createSignal<[string, string, string]>([
    ...DEFAULT_PALETTE,
  ])
  const dims = useTerminalDimensions()
  const pull = () => {
    const runtime = loadRuntime()
    setPalette(resolvePalette(runtime))
    void tickPayload().then(setPayload)
  }
  pull()
  const id = setInterval(pull, REFRESH_MS)
  onCleanup(() => clearInterval(id))

  const maxCols = createMemo(() => {
    const width = Number(dims()?.width) || 80
    const capped = Math.floor(width * WIDTH_FRACTION)
    return Math.max(MIN_CHIP_COLS, Math.min(MAX_CHIP_COLS, capped))
  })

  const layout = createMemo(() => layoutChip(payload(), maxCols()))
  const visible = createMemo(() => Boolean(layout()))
  const colors = createMemo(() => palette())

  return (
    <box
      flexDirection="row"
      gap={1}
      flexShrink={1}
      wrapMode="none"
      visible={visible()}
      maxWidth={maxCols()}
    >
      <text fg={colors()[2]} wrapMode="none">
        {layout()?.structured ? layout()!.glyph : ""}
      </text>
      <text fg={colors()[0]} wrapMode="none">
        {layout()?.structured ? layout()!.artists : layout()?.fallback || ""}
      </text>
      <text fg={C_DIM} wrapMode="none">
        {layout()?.structured ? layout()!.dash : ""}
      </text>
      <text fg={colors()[1]} wrapMode="none">
        {layout()?.structured ? layout()!.name : ""}
      </text>
      <text fg={C_DIM} wrapMode="none">
        {layout()?.structured ? layout()!.dot : ""}
      </text>
      <text fg={colors()[2]} wrapMode="none">
        {layout()?.structured ? layout()!.time : ""}
      </text>
    </box>
  )
}

const plugin: TuiPlugin = async (api) => {
  const render = (_ctx: TuiSlotContext) => <SpotifyChip />
  api.slots.register({
    order: 60,
    slots: {
      session_prompt_right: render,
      home_prompt_right: render,
    },
  })
}

export default {
  id: "agent-dj",
  tui: plugin,
}
