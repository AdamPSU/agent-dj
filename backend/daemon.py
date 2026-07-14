import os

from fastapi import FastAPI
from uvicorn import Config, Server

from backend.config import HOST, PORT
from backend import sync as catalog_sync
from backend.storage import db

app = FastAPI()
_server: Server | None = None


def status_body() -> dict:
    """Build the debug status payload, including sync progress when available."""
    body: dict = {
        "ok": True,
        "pid": os.getpid(),
        "syncing": catalog_sync.is_syncing(),
        "current": catalog_sync.current_track(),
        "tracks": {status: 0 for status in db.STATUSES},
        "playlists": 0,
    }
    try:
        conn = db.connect()
        try:
            body["tracks"] = db.track_status_counts(conn)
            body["playlists"] = db.playlist_count(conn)
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
    """Ensure catalog sync is running; orchestrator (recommend/playback) later."""
    catalog_sync.kick()
    return {"ok": True, "play": "not_implemented"}


@app.post("/quit")
async def quit() -> dict:
    if _server is not None:
        _server.should_exit = True
    return {"ok": True}


def main() -> None:
    """Run the long-lived local server that the CLI talks to."""
    global _server
    _server = Server(Config(app, host=HOST, port=PORT, log_level="warning"))
    _server.run()
