import os

from fastapi import FastAPI
from uvicorn import Config, Server

from backend.config import HOST, PORT

app = FastAPI()
started = False
_server: Server | None = None


def status_body() -> dict:
    return {"ok": True, "started": started, "pid": os.getpid()}


@app.get("/status")
def status() -> dict:
    return status_body()


@app.post("/start")
def start() -> dict:
    global started
    started = True
    return status_body()


@app.post("/sync")
def sync() -> dict:
    return {"ok": True, "stub": True}


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
