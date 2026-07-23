"""Agent-agnostic now-playing formatting and poll/interpolate cache."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from backend.config import NOW_PLAYING_PATH

POLL_S = 5.0
STALE_S = 30.0

_MUSIC_GLYPHS = ("♪", "♫", "♬", "♩")

_NOTE_HEX = "#1DB954"
_DIM_HEX = "#6C7086"
_RESET = "\033[0m"


def music_glyph(*, now: float | None = None) -> str:
    t = time.time() if now is None else now
    return _MUSIC_GLYPHS[int(t) % len(_MUSIC_GLYPHS)]


def _use_color() -> bool:
    return not os.environ.get("NO_COLOR")


def _ansi_fg(hex_color: str) -> str:
    from backend.config import normalize_hex

    n = normalize_hex(hex_color) or "#FFFFFF"
    body = n[1:]
    r, g, b = int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


def _c(code: str, text: str, *, color: bool) -> str:
    if not color:
        return text
    return f"{code}{text}{_RESET}"


def format_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    total = max(0, int(ms) // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_line(
    snap: dict[str, Any],
    *,
    color: bool | None = None,
    now: float | None = None,
    palette: tuple[str, str, str] | None = None,
) -> str:
    if color is None:
        color = _use_color()
    if not (snap.get("spotify_id") or snap.get("name")):
        return ""
    if palette is None:
        from backend.config import load_palette

        palette = load_palette()
    artist_c, song_c, time_c = palette
    artists = str(snap.get("artists") or "").strip() or "unknown"
    name = str(snap.get("name") or "").strip() or "unknown"
    prog = format_ms(snap.get("progress_ms") if snap.get("progress_ms") is not None else None)
    dur = format_ms(snap.get("duration_ms") if snap.get("duration_ms") is not None else None)
    glyph = music_glyph(now=now)
    return (
        f"{_c(_ansi_fg(_NOTE_HEX), glyph, color=color)} "
        f"{_c(_ansi_fg(artist_c), artists, color=color)} "
        f"{_c(_ansi_fg(_DIM_HEX), '—', color=color)} "
        f"{_c(_ansi_fg(song_c), name, color=color)} "
        f"{_c(_ansi_fg(_DIM_HEX), '·', color=color)} "
        f"{_c(_ansi_fg(time_c), f'{prog}/{dur}', color=color)}"
    )


def load_cache(path: Path | None = None) -> dict[str, Any] | None:
    p = path or NOW_PLAYING_PATH
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_cache(snap: dict[str, Any], path: Path | None = None) -> None:
    p = path or NOW_PLAYING_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def clear_cache(path: Path | None = None) -> None:
    p = path or NOW_PLAYING_PATH
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def needs_poll(cache: dict[str, Any] | None, *, now: float) -> bool:
    if not cache or "fetched_at" not in cache:
        return True
    age = now - float(cache["fetched_at"])
    if age >= POLL_S:
        return True
    if not bool(cache.get("is_playing")):
        return False
    progress = int(cache.get("progress_ms") or 0)
    duration = int(cache.get("duration_ms") or 0)
    if duration <= 0:
        return False
    projected = progress + int(age * 1000)
    return projected >= duration


def display_progress(snap: dict[str, Any], *, now: float) -> int:
    progress = int(snap.get("progress_ms") or 0)
    duration = int(snap.get("duration_ms") or 0)
    if not bool(snap.get("is_playing")):
        return progress
    fetched_at = float(snap.get("fetched_at") or now)
    elapsed_ms = int((now - fetched_at) * 1000)
    projected = progress + max(0, elapsed_ms)
    if duration > 0:
        return min(duration, projected)
    return projected


def resolve_snapshot(
    *,
    now: float | None = None,
    fetch: Callable[[], dict[str, Any] | None] | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any] | None:
    t = time.time() if now is None else now
    cache = load_cache(cache_path)

    if not needs_poll(cache, now=t):
        return cache

    if fetch is None:
        from backend import spotify

        fetch = spotify.get_now_playing

    try:
        row = fetch()
    except Exception:
        if cache is not None:
            age = t - float(cache.get("fetched_at") or 0)
            if age < STALE_S:
                return cache
        return None

    if row is None:
        clear_cache(cache_path)
        return None

    snap = {
        "fetched_at": t,
        "spotify_id": row.get("spotify_id"),
        "name": row.get("name") or "",
        "artists": row.get("artists") or "",
        "progress_ms": int(row.get("progress_ms") or 0),
        "duration_ms": int(row.get("duration_ms") or 0),
        "is_playing": bool(row.get("is_playing")),
    }
    save_cache(snap, cache_path)
    return snap


def render_snapshot(
    snap: dict[str, Any] | None,
    *,
    color: bool | None = None,
    now: float | None = None,
) -> str:
    if not snap:
        return ""
    t = time.time() if now is None else now
    display = dict(snap)
    display["progress_ms"] = display_progress(snap, now=t)
    return format_line(display, color=color, now=t)


def snapshot_payload(
    snap: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Structured now-playing for TUI plugins (OpenCode cannot render ANSI)."""
    if not snap:
        return None
    if not (snap.get("spotify_id") or snap.get("name")):
        return None
    t = time.time() if now is None else now
    progress_ms = display_progress(snap, now=t)
    artists = str(snap.get("artists") or "").strip() or "unknown"
    name = str(snap.get("name") or "").strip() or "unknown"
    return {
        "glyph": music_glyph(now=t),
        "artists": artists,
        "name": name,
        "title": f"{artists} — {name}",
        "progress": format_ms(progress_ms),
        "duration": format_ms(
            snap.get("duration_ms") if snap.get("duration_ms") is not None else None
        ),
        "is_playing": bool(snap.get("is_playing")),
        "line": format_line(
            {**snap, "progress_ms": progress_ms},
            color=False,
            now=t,
        ),
    }
