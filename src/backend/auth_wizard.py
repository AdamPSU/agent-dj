"""Interactive Spotify auth and multi-agent statusline enable."""

from __future__ import annotations

import sys
from typing import Any

from backend import config, spotify
from backend.agents import AgentId, prompt_agents
from backend.claude import statusline as claude_statusline
from backend.opencode import statusline as opencode_statusline
from backend.pi import statusline as pi_statusline
from backend.ui import blank, confirm_step, dim, fail, header, ok, prompt_step


def _bind_tty() -> None:
    if sys.stdin.isatty():
        return
    try:
        sys.stdin = open("/dev/tty", encoding="utf-8")  # noqa: SIM115
    except OSError:
        print(
            "dj auth requires an interactive terminal.\nRun: dj auth",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    if not sys.stdin.isatty():
        print(
            "dj auth requires an interactive terminal.\nRun: dj auth",
            file=sys.stderr,
        )
        raise SystemExit(2)


def resolve_client_id() -> str:
    existing = ""
    try:
        existing = config.resolve_spotify_client_id()
    except config.ConfigError:
        existing = str(config.load_app_config().get("spotify_client_id") or "").strip()

    if existing:
        short = f"{existing[:8]}…"
        if confirm_step(f"Use existing Spotify Client ID ({short})?", default_yes=True):
            return existing

    cid = prompt_step("Spotify Client ID", initial=existing)
    config.set_spotify_client_id(cid)
    return cid


def spotify_login() -> None:
    already = False
    try:
        already = spotify.session_is_valid()
    except Exception:
        already = False

    if already:
        if not confirm_step(
            "Spotify already logged in. Re-authenticate?",
            default_yes=False,
        ):
            ok("Already authenticated")
            return

    if not confirm_step(
        "Open browser to authorize Spotify?",
        default_yes=True,
    ):
        print("auth cancelled: Spotify login is required", file=sys.stderr)
        raise SystemExit(1)

    dim("Authorizing…")
    spotify.ensure_session()
    ok("Authenticated with Spotify")


def currently_enabled() -> list[AgentId]:
    enabled: list[AgentId] = []
    if claude_statusline.is_installed():
        enabled.append("claude")
    if opencode_statusline.is_installed():
        enabled.append("opencode")
    if pi_statusline.is_installed():
        enabled.append("pi")
    return enabled


def enable_agents(agents: list[AgentId]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    ok_all = True
    for agent in agents:
        try:
            if agent == "claude":
                out = claude_statusline.ensure_installed()
                if not isinstance(out, dict):
                    out = {"ok": True, "action": "installed"}
            elif agent == "opencode":
                opencode_statusline.ensure_installed()
                out = {"ok": True, "action": "installed"}
            else:
                pi_statusline.ensure_installed()
                out = {"ok": True, "action": "installed"}
        except Exception as exc:  # noqa: BLE001 — surface to wizard UI
            out = {"ok": False, "error": str(exc)}
        results[agent] = out
        if not out.get("ok"):
            ok_all = False
    return {"ok": ok_all, "agents": results}


def disable_agents(agents: list[AgentId]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    ok_all = True
    for agent in agents:
        try:
            if agent == "claude":
                out = claude_statusline.uninstall()
                if not isinstance(out, dict):
                    out = {"ok": True, "action": "disabled"}
            elif agent == "opencode":
                opencode_statusline.uninstall()
                out = {"ok": True, "action": "disabled"}
            else:
                pi_statusline.uninstall()
                out = {"ok": True, "action": "disabled"}
        except Exception as exc:  # noqa: BLE001 — surface to wizard UI
            out = {"ok": False, "error": str(exc)}
        results[agent] = out
        if not out.get("ok"):
            ok_all = False
    return {"ok": ok_all, "agents": results}


_LABELS = {"claude": "Claude Code", "opencode": "OpenCode", "pi": "Pi"}


def _report_enable(results: dict[str, Any]) -> None:
    for agent, out in results.get("agents", {}).items():
        name = _LABELS.get(agent, agent)
        if out.get("ok"):
            action = out.get("action") or "enabled"
            if action == "noop":
                action = "installed"
            ok(f"{name} · {action}")
        else:
            err = out.get("error") or "failed"
            fail(f"{name} · {err}")


def _report_disable(results: dict[str, Any]) -> None:
    for agent, out in results.get("agents", {}).items():
        name = _LABELS.get(agent, agent)
        if not out.get("ok"):
            fail(f"{name} · {out.get('error') or 'failed'}")
            continue
        action = out.get("action") or "disabled"
        if action == "noop":
            ok(f"{name} · already off")
        else:
            ok(f"{name} · off")


def run_on() -> dict[str, Any]:
    _bind_tty()
    header("dj on")
    chosen = prompt_agents(
        selected=currently_enabled(),
        question="Enable statusline for",
    )
    blank()
    results = enable_agents(chosen)
    _report_enable(results)
    blank()
    if not results.get("ok"):
        raise SystemExit(1)
    return results


def run_off() -> dict[str, Any]:
    _bind_tty()
    header("dj off")
    chosen = prompt_agents(
        selected=currently_enabled(),
        question="Disable statusline for",
    )
    blank()
    results = disable_agents(chosen)
    _report_disable(results)
    blank()
    if not results.get("ok"):
        raise SystemExit(1)
    return results


def run() -> dict[str, Any]:
    _bind_tty()
    header("dj auth")

    try:
        cid = resolve_client_id()
        spotify_login()
        blank()

        default = currently_enabled() or ["claude", "opencode"]
        chosen = prompt_agents(
            selected=default,
            question="Enable statusline for",
        )
        blank()
        results = enable_agents(chosen)
        _report_enable(results)
        if not results.get("ok"):
            raise SystemExit(1)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("auth cancelled") from None

    blank()
    ok("Done")
    dim("Toggle later with dj off / dj on")
    blank()
    return {
        "ok": True,
        "spotify_client_id": cid,
        "agents": chosen,
        "statusline": results,
    }
