import json
import urllib.error
import urllib.request

DEEZER_API_BASE = "https://api.deezer.com"


class DeezerError(Exception):
    """Raised when Deezer cannot be reached or returns an unusable response."""


def normalize_isrc(isrc: str) -> str:
    """Clean an ISRC for lookup: strip spaces and uppercase."""
    return isrc.strip().upper()


def lookup_by_isrc(isrc: str) -> dict | None:
    """Find a Deezer track by ISRC. Returns a small dict, or None if not found."""
    cleaned = normalize_isrc(isrc)
    if not cleaned:
        raise DeezerError("ISRC is empty")

    url = f"{DEEZER_API_BASE}/track/isrc:{cleaned}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        body = exc.read().decode(errors="replace")
        raise DeezerError(f"Deezer HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DeezerError(f"Deezer request failed: {exc}") from exc

    if not isinstance(payload, dict) or "id" not in payload:
        return None
    if payload.get("error"):
        return None

    artist = payload.get("artist") or {}
    return {
        "id": payload["id"],
        "title": payload.get("title") or "",
        "artist": artist.get("name") or "",
        "isrc": payload.get("isrc") or cleaned,
        "preview": payload.get("preview") or "",
        "readable": bool(payload.get("readable", False)),
        "duration": int(payload.get("duration") or 0),
    }
