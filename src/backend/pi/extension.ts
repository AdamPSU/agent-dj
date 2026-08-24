import { execFile } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";

const execFileAsync = promisify(execFile);
const REFRESH_MS = 500;
const COLOR_MS = 90;
const APP_DIR = join(homedir(), ".agent-dj");
const RUNTIME_PATH = join(APP_DIR, "pi_runtime.json");
const CONFIG_PATH = join(APP_DIR, "config.json");
const PAUSED = "\u23f8\uFE0E spotify paused";
const RESET = "\x1b[39m";
const COLORS = [
  "\x1b[38;2;255;240;242m", // pastel red
  "\x1b[38;2;255;245;235m", // pastel orange
  "\x1b[38;2;255;254;235m", // pastel yellow
  "\x1b[38;2;239;253;243m", // pastel green
  "\x1b[38;2;239;247;255m", // pastel blue
  "\x1b[38;2;246;239;255m", // pastel violet
];

/** Indent + whimsical pastel, cycling with time. */
export function paintLine(plain: string, width: number, now = Date.now()): string {
  const color = COLORS[Math.floor(now / COLOR_MS) % COLORS.length]!;
  const body = truncateToWidth(plain, Math.max(1, width - 1));
  return ` ${color}${body}${RESET}`;
}

type Placement = "above" | "below";

type RuntimeConfig = {
  command?: string[];
  placement?: string;
};

function readJson(path: string): Record<string, unknown> {
  try {
    const data = JSON.parse(readFileSync(path, "utf8"));
    return data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function writeJson(path: string, data: Record<string, unknown>): void {
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n", { mode: 0o600 });
}

function asPlacement(value: unknown): Placement | undefined {
  const v = String(value ?? "").trim().toLowerCase();
  return v === "above" || v === "below" ? v : undefined;
}

function loadPlacement(): Placement {
  return (
    asPlacement(readJson(CONFIG_PATH).pi_placement) ??
    asPlacement(readJson(RUNTIME_PATH).placement) ??
    "below"
  );
}

function savePlacement(next: Placement): void {
  writeJson(CONFIG_PATH, { ...readJson(CONFIG_PATH), pi_placement: next });
  writeJson(RUNTIME_PATH, { ...readJson(RUNTIME_PATH), placement: next });
}

function widgetPlacement(placement: Placement): "aboveEditor" | "belowEditor" {
  return placement === "above" ? "aboveEditor" : "belowEditor";
}

async function tickPlain(): Promise<string> {
  const runtime = readJson(RUNTIME_PATH) as RuntimeConfig;
  const home = process.env.HOME || homedir();
  const command =
    Array.isArray(runtime.command) && runtime.command.length > 0
      ? runtime.command
      : [join(home, ".local/bin/dj"), "tick"];
  const [bin, ...rest] = command;
  if (!bin) return PAUSED;
  const args = rest.includes("--json") || rest.includes("-j") ? rest : [...rest, "--json"];
  try {
    const { stdout } = await execFileAsync(bin, args, {
      timeout: 5000,
      windowsHide: true,
      maxBuffer: 64 * 1024,
    });
    const raw = String(stdout || "").trim();
    if (!raw.startsWith("{")) return PAUSED;
    const payload = JSON.parse(raw) as { is_playing?: boolean; line?: string };
    if (payload.is_playing && payload.line) return payload.line;
    return payload.line || PAUSED;
  } catch {
    return PAUSED;
  }
}

const SEP = "\x1b[38;2;110;110;110m";

function lastUserText(ctx: { sessionManager: { getBranch: () => any[] } }): string {
  const branch = ctx.sessionManager.getBranch();
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = branch[i];
    const msg = entry?.type === "message" ? entry.message : entry;
    if (msg?.role !== "user") continue;
    const content = msg.content;
    const text = typeof content === "string"
      ? content
      : Array.isArray(content)
        ? content.map((part: { text?: string }) => part?.text ?? "").join(" ")
        : "";
    const out = text.replace(/\s+/g, " ").trim();
    if (out) return out;
  }
  return "";
}

function paintLastPrompt(text: string, width: number): string[] {
  if (!text) return [];
  const prefix = ` ${SEP}↳${RESET} `;
  const body = truncateToWidth(text, Math.max(1, width - 3));
  return [`${prefix}${SEP}${body}${RESET}`];
}

export default function (pi: ExtensionAPI) {
  let tickTimer: ReturnType<typeof setInterval> | undefined;
  let colorTimer: ReturnType<typeof setInterval> | undefined;
  let ui: { setWidget: (...args: any[]) => void } | undefined;
  let tui: { requestRender: () => void } | undefined;
  let sessionCtx: { sessionManager: { getBranch: () => any[] } } | undefined;
  let plain = PAUSED;
  let lastPrompt = "";

  function mount() {
    if (!ui) return;
    const placement = widgetPlacement(loadPlacement());
    ui.setWidget(
      "agent-dj",
      (nextTui) => {
        tui = nextTui;
        return {
          dispose() {},
          invalidate() {},
          render(width: number) {
            return [paintLine(plain, width)];
          },
        };
      },
      { placement },
    );
    // Keep ↳ after the song: re-append powerline's last-prompt widget.
    if (placement === "belowEditor") {
      ui.setWidget(
        "powerline-last-prompt",
        () => ({
          dispose() {},
          invalidate() {},
          render(width: number) {
            return paintLastPrompt(lastPrompt, width);
          },
        }),
        { placement: "belowEditor" },
      );
    }
  }

  async function refresh() {
    plain = await tickPlain();
    if (sessionCtx) lastPrompt = lastUserText(sessionCtx);
    mount();
  }

  function stop() {
    if (tickTimer) clearInterval(tickTimer);
    if (colorTimer) clearInterval(colorTimer);
    tickTimer = undefined;
    colorTimer = undefined;
    ui?.setWidget("agent-dj", undefined);
    ui = undefined;
    tui = undefined;
    sessionCtx = undefined;
  }

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    stop();
    ui = ctx.ui;
    sessionCtx = ctx;
    void refresh();
    tickTimer = setInterval(() => void refresh(), REFRESH_MS);
    colorTimer = setInterval(() => tui?.requestRender(), COLOR_MS);
  });

  pi.on("session_shutdown", () => {
    stop();
  });

  pi.registerCommand("dj", {
    description: "Now-playing widget. /dj placement above|below|toggle",
    handler: async (args, ctx) => {
      const raw = (args || "").trim();
      const match = /^(?:placement(?:\s+(above|below|toggle))?)?$/.exec(raw);
      if (!match) {
        ctx.ui.notify("usage: /dj placement above|below|toggle", "warning");
        return;
      }
      const requested = match[1];
      if (!requested) {
        ctx.ui.notify(`Now playing placement: ${loadPlacement()}`, "info");
        return;
      }
      const current = loadPlacement();
      const next =
        requested === "toggle" ? (current === "above" ? "below" : "above") : requested;
      savePlacement(next);
      ui = ctx.ui;
      sessionCtx = ctx;
      void refresh();
      ctx.ui.notify(`Now playing placement: ${next}`, "info");
    },
  });
}
