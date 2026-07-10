"""ElevenLabs text-to-speech adapter for Claude DJ narration."""

from pathlib import Path
from urllib.parse import urlencode
import json
import urllib.error
import urllib.request

from claude_dj.config import NarrationConfig


API_BASE_URL = "https://api.elevenlabs.io/v1"
REQUEST_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 8192


class ElevenLabsError(RuntimeError):
    """Raised when ElevenLabs cannot synthesize narration audio."""


def synthesize_speech_to_file(
    text: str,
    output_file: Path,
    config: NarrationConfig,
    *,
    urlopen=urllib.request.urlopen,
) -> Path:
    """Stream ElevenLabs TTS audio to an MP3 file."""
    output_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    request = urllib.request.Request(
        _stream_url(config),
        data=json.dumps(
            {
                "text": text,
                "model_id": config.elevenlabs_model_id,
            }
        ).encode("utf-8"),
        headers={
            "xi-api-key": config.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    byte_count = 0
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            with output_file.open("wb") as audio:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    audio.write(chunk)
    except urllib.error.HTTPError as exc:
        raise ElevenLabsError(f"ElevenLabs TTS failed with HTTP {exc.code}.") from exc
    except OSError as exc:
        output_file.unlink(missing_ok=True)
        raise ElevenLabsError("ElevenLabs TTS failed.") from exc

    if byte_count == 0:
        output_file.unlink(missing_ok=True)
        raise ElevenLabsError("ElevenLabs returned empty audio.")
    return output_file


def _stream_url(config: NarrationConfig) -> str:
    query: dict[str, str] = {"output_format": config.elevenlabs_output_format}
    if config.elevenlabs_model_id != "eleven_v3" and config.elevenlabs_optimize_streaming_latency is not None:
        query["optimize_streaming_latency"] = str(config.elevenlabs_optimize_streaming_latency)
    return f"{API_BASE_URL}/text-to-speech/{config.elevenlabs_voice_id}/stream?{urlencode(query)}"
