import json
from unittest.mock import MagicMock, patch

import pytest

from backend.adapters import deezer


def test_normalize_isrc() -> None:
    assert deezer.normalize_isrc("  usrc17607839  ") == "USRC17607839"


def test_lookup_by_isrc_empty_raises() -> None:
    with pytest.raises(deezer.DeezerError, match="empty"):
        deezer.lookup_by_isrc("   ")


def test_lookup_by_isrc_hit() -> None:
    payload = {
        "id": 42,
        "title": "One More Time",
        "artist": {"name": "Daft Punk"},
        "isrc": "GBDUW0000059",
        "preview": "https://example.com/preview.mp3",
        "readable": True,
        "duration": 320,
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch.object(deezer.urllib.request, "urlopen", return_value=mock_resp) as urlopen:
        result = deezer.lookup_by_isrc("gbduw0000059")

    assert result == {
        "id": 42,
        "title": "One More Time",
        "artist": "Daft Punk",
        "isrc": "GBDUW0000059",
        "preview": "https://example.com/preview.mp3",
        "readable": True,
        "duration": 320,
    }
    assert "isrc:GBDUW0000059" in urlopen.call_args.args[0]


def test_lookup_by_isrc_miss_error_payload() -> None:
    payload = {"error": {"type": "DataException", "message": "no data", "code": 800}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch.object(deezer.urllib.request, "urlopen", return_value=mock_resp):
        assert deezer.lookup_by_isrc("USRC17607839") is None


def test_lookup_by_isrc_network_error() -> None:
    with patch.object(
        deezer.urllib.request,
        "urlopen",
        side_effect=deezer.urllib.error.URLError("down"),
    ):
        with pytest.raises(deezer.DeezerError, match="failed"):
            deezer.lookup_by_isrc("USRC17607839")
