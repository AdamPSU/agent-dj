import os
import threading
import time

from fastapi import FastAPI
from uvicorn import Config, Server

from backend.config import HOST, PORT
from backend import sync as catalog_sync
from backend.orchestrator import Orchestrator
from backend.music.playback import FakePlayback, SpotifyPlayback
from backend.storage import db

app = FastAPI()
_server: Server | None = None


def _build_playback():
    """Use Spotify when tokens exist; FakePlayback otherwise (tests / offline)."""
    try:
        from backend.adapters.spotify import load_tokens

        if load_tokens() is not None:
            return SpotifyPlayback()
    except Exception:
        pass
    return FakePlayback()


_orchestrator = Orchestrator(playback=_build_playback())
_monitor_stop = threading.Event()
_monitor_thread: threading.Thread | None = None


def _monitor_loop() -> None:
    while not _monitor_stop.is_set():
        try:
            if _orchestrator.mode == "attached":
                conn = db.connect()
                try:
                    result = _orchestrator.tick(conn)
                    interval = 5.0
                    if result.get("event") == "ok":
                        # Near-end faster poll is handled inside tick via play-next;
                        # keep a slightly faster cadence while attached.
                        interval = 3.0
                finally:
                    conn.close()
            else:
                interval = 5.0
        except Exception:
            interval = 5.0
        _monitor_stop.wait(interval)


def _ensure_monitor() -> None:
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return
    _monitor_stop.clear()
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="dj-monitor")
    _monitor_thread.start()


def status_body() -> dict:
    """Build the debug status payload, including sync and play state."""
    body: dict = {
        "ok": True,
        "pid": os.getpid(),
        "syncing": catalog_sync.is_syncing(),
        "current": catalog_sync.current_track(),
        "tracks": {status: 0 for status in db.STATUSES},
        "playlists": 0,
        "playing": False,
        "mode": "idle",
        "current_block": None,
        "indexed": 0,
        "recommend_ready": False,
        "now_playing": None,
        "virtual_queue": [],
    }
    try:
        conn = db.connect()
        try:
            body["tracks"] = db.track_status_counts(conn)
            body["playlists"] = db.playlist_count(conn)
            body.update(_orchestrator.status_snapshot(conn))
        finally:
            conn.close()
    except Exception:
        pass
    return body


@app.get("/status")
def status() -> dict:
    return status_body()


@app.post("/sync")
def sync() -> dict:
    catalog_sync.kick()
    return {"ok": True, "syncing": catalog_sync.is_syncing()}


@app.post("/play")
def play() -> dict:
    """Kick catalog sync, start/resume DJ with virtual-queue playback."""
    catalog_sync.kick()
    _ensure_monitor()
    try:
        conn = db.connect()
        try:
            return _orchestrator.play(conn)
        finally:
            conn.close()
    except Exception as exc:
        return {"ok": False, "error": "play_failed", "detail": str(exc)}


@app.get("/devices")
def devices() -> dict:
    """List Spotify Connect devices and the saved preference."""
    from backend.adapters import spotify

    try:
        rows = spotify.list_devices()
        preferred = spotify.load_preferred_device_id()
        return {"ok": True, "devices": rows, "preferred_device_id": preferred}
    except Exception as exc:
        return {"ok": False, "error": "devices_failed", "detail": str(exc)}


@app.post("/devices/{device_id}")
def select_device(device_id: str) -> dict:
    """Persist preferred device and transfer Connect playback to it."""
    from backend.adapters import spotify

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
            # Preference saved even if transfer fails (device offline momentarily).
            pass
        return {
            "ok": True,
            "preferred_device_id": device_id,
            "device": match,
        }
    except Exception as exc:
        return {"ok": False, "error": "device_select_failed", "detail": str(exc)}


@app.post("/quit")
async def quit() -> dict:
    _monitor_stop.set()
    if _server is not None:
        _server.should_exit = True
    return {"ok": True}


def main() -> None:
    """Run the long-lived local server that the CLI talks to."""
    global _server
    _server = Server(Config(app, host=HOST, port=PORT, log_level="warning"))
    _server.run()
