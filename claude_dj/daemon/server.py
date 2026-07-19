import logging
import os
import threading

from fastapi import FastAPI
from uvicorn import Config, Server

from claude_dj.config import HOST, PORT
from claude_dj.catalog import sync as catalog_sync
from claude_dj.session import Session
from claude_dj.playback import SpotifyPlayback
from claude_dj.catalog import db

log = logging.getLogger("claude-dj.daemon")

app = FastAPI()
_server: Server | None = None

_session = Session(playback=SpotifyPlayback())
_monitor_stop = threading.Event()
_monitor_thread: threading.Thread | None = None


def _shutdown() -> None:
    """Stop monitor loop and uvicorn (same path as /kill)."""
    _monitor_stop.set()
    if _server is not None:
        _server.should_exit = True


def _monitor_loop() -> None:
    while not _monitor_stop.is_set():
        try:
            if _session.mode == "attached":
                conn = db.connect()
                try:
                    result = _session.tick(conn)
                finally:
                    conn.close()
                if result.get("quit"):
                    log.info("foreign track — shutting down")
                    _shutdown()
                    return
        except Exception:
            log.exception("monitor tick failed")
        _monitor_stop.wait(1.0)


def _ensure_monitor() -> None:
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return
    _monitor_stop.clear()
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="dj-monitor")
    _monitor_thread.start()


def status_body() -> dict:
    """Health + playback/sync snapshot for CLI and statusline."""
    body: dict = {
        "ok": True,
        "syncing": catalog_sync.is_syncing(),
        "mode": "idle",
        "indexed": 0,
        "catalog_total": 0,
        "now_playing": None,
    }
    try:
        conn = db.connect()
        try:
            body.update(_session.status(conn))
        finally:
            conn.close()
    except Exception:
        log.exception("status snapshot failed")
    return body


@app.get("/status")
def status() -> dict:
    return status_body()


@app.post("/sync")
def sync() -> dict:
    catalog_sync.kick()
    return {"ok": True, "syncing": catalog_sync.is_syncing()}


@app.post("/jam")
def jam() -> dict:
    """Kick catalog sync, start/resume DJ with virtual-queue playback."""
    catalog_sync.kick()
    _ensure_monitor()
    try:
        conn = db.connect()
        try:
            return _session.play(conn)
        finally:
            conn.close()
    except Exception as exc:
        log.exception("jam failed")
        return {"ok": False, "error": "play_failed", "detail": str(exc)}


@app.get("/devices")
def devices() -> dict:
    """List Spotify Connect devices and the saved preference."""
    from claude_dj.adapters import spotify

    try:
        rows = spotify.list_devices()
        preferred = spotify.load_preferred_device_id()
        return {"ok": True, "devices": rows, "preferred_device_id": preferred}
    except Exception as exc:
        log.exception("devices list failed")
        return {"ok": False, "error": "devices_failed", "detail": str(exc)}


@app.post("/devices/{device_id}")
def select_device(device_id: str) -> dict:
    """Persist preferred device and transfer Connect playback to it."""
    from claude_dj.adapters import spotify

    try:
        rows = spotify.list_devices()
        match = next((d for d in rows if d.get("id") == device_id), None)
        if match is None:
            return {
                "ok": False,
                "error": "unknown_device",
                "detail": f"device not in available list: {device_id}",
                "devices": rows,
            }
        spotify.save_preferred_device_id(device_id)
        try:
            spotify.transfer_playback(device_id, play=False)
        except Exception:
            log.exception("transfer playback failed (preference still saved)")
        return {
            "ok": True,
            "preferred_device_id": device_id,
            "device": match,
        }
    except Exception as exc:
        log.exception("device select failed")
        return {"ok": False, "error": "device_select_failed", "detail": str(exc)}


@app.post("/kill")
async def kill() -> dict:
    """Stop daemon entirely (jam + statusline process). Spotify keeps playing."""
    _session.quit_jam()
    _shutdown()
    return {"ok": True}


def main() -> None:
    """Run the long-lived local server that the CLI talks to."""
    global _server
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    _server = Server(Config(app, host=HOST, port=PORT, log_level="warning"))
    _server.run()
