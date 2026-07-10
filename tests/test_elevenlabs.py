"""ElevenLabs narration adapter tests."""

import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from claude_dj.adapters.elevenlabs import ElevenLabsError, synthesize_speech_to_file
from claude_dj.config import NarrationConfig


def test_synthesize_speech_to_file_streams_elevenlabs_audio(tmp_path) -> None:
    requests = []

    class FakeResponse:
        chunks = [b"audio-bytes", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            return self.chunks.pop(0)

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    output_file = tmp_path / "speech.mp3"
    result = synthesize_speech_to_file(
        "Claude DJ is live.",
        output_file,
        NarrationConfig(
            elevenlabs_api_key="secret-key",
            elevenlabs_voice_id="voice-id",
            elevenlabs_model_id="eleven_v3",
            elevenlabs_output_format="mp3_44100_128",
        ),
        urlopen=fake_urlopen,
    )

    request, timeout = requests[0]
    parsed = urlparse(request.full_url)
    query = parse_qs(parsed.query)
    body = json.loads(request.data.decode("utf-8"))
    assert result == output_file
    assert output_file.read_bytes() == b"audio-bytes"
    assert parsed.scheme == "https"
    assert parsed.netloc == "api.elevenlabs.io"
    assert parsed.path == "/v1/text-to-speech/voice-id/stream"
    assert query == {"output_format": ["mp3_44100_128"]}
    assert request.get_method() == "POST"
    assert request.headers["Xi-api-key"] == "secret-key"
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Accept"] == "audio/mpeg"
    assert body == {"text": "Claude DJ is live.", "model_id": "eleven_v3"}
    assert timeout == 30


def test_synthesize_speech_to_file_omits_latency_param_for_v3(tmp_path) -> None:
    class FakeResponse:
        chunks = [b"audio", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            return self.chunks.pop(0)

    request_urls = []

    def fake_urlopen(request, timeout):
        request_urls.append(request.full_url)
        return FakeResponse()

    synthesize_speech_to_file(
        "Claude DJ is live.",
        tmp_path / "speech.mp3",
        NarrationConfig(
            elevenlabs_api_key="secret-key",
            elevenlabs_voice_id="voice-id",
            elevenlabs_model_id="eleven_v3",
            elevenlabs_output_format="mp3_44100_128",
        ),
        urlopen=fake_urlopen,
    )

    assert "optimize_streaming_latency" not in request_urls[0]


def test_synthesize_speech_to_file_adds_latency_param_for_flash_2_5(tmp_path) -> None:
    class FakeResponse:
        chunks = [b"audio", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            return self.chunks.pop(0)

    request_urls = []

    def fake_urlopen(request, timeout):
        request_urls.append(request.full_url)
        return FakeResponse()

    synthesize_speech_to_file(
        "Claude DJ is live.",
        tmp_path / "speech.mp3",
        NarrationConfig(
            elevenlabs_api_key="secret-key",
            elevenlabs_voice_id="voice-id",
            elevenlabs_model_id="eleven_flash_v2_5",
            elevenlabs_output_format="mp3_44100_128",
            elevenlabs_optimize_streaming_latency=3,
        ),
        urlopen=fake_urlopen,
    )

    parsed = urlparse(request_urls[0])
    assert parse_qs(parsed.query)["optimize_streaming_latency"] == ["3"]


def test_synthesize_speech_to_file_rejects_empty_audio(tmp_path) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            return b""

    with pytest.raises(ElevenLabsError, match="empty audio"):
        synthesize_speech_to_file(
            "Claude DJ is live.",
            tmp_path / "speech.mp3",
            NarrationConfig(
                elevenlabs_api_key="secret-key",
                elevenlabs_voice_id="voice-id",
                elevenlabs_model_id="eleven_v3",
                elevenlabs_output_format="mp3_44100_128",
            ),
            urlopen=lambda request, timeout: FakeResponse(),
        )
    assert not (tmp_path / "speech.mp3").exists()


def test_synthesize_speech_to_file_removes_partial_audio_on_write_failure(tmp_path) -> None:
    class FakeResponse:
        chunks = [b"partial-audio"]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            if self.chunks:
                return self.chunks.pop(0)
            raise OSError("connection reset")

    output_file = tmp_path / "speech.mp3"
    with pytest.raises(ElevenLabsError):
        synthesize_speech_to_file(
            "Claude DJ is live.",
            output_file,
            NarrationConfig(
                elevenlabs_api_key="secret-key",
                elevenlabs_voice_id="voice-id",
                elevenlabs_model_id="eleven_v3",
                elevenlabs_output_format="mp3_44100_128",
            ),
            urlopen=lambda request, timeout: FakeResponse(),
        )

    assert not output_file.exists()


def test_synthesize_speech_to_file_maps_http_error_without_key(tmp_path) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"detail":"bad key"}'),
        )

    with pytest.raises(ElevenLabsError) as exc_info:
        synthesize_speech_to_file(
            "Claude DJ is live.",
            tmp_path / "speech.mp3",
            NarrationConfig(
                elevenlabs_api_key="secret-key",
                elevenlabs_voice_id="voice-id",
                elevenlabs_model_id="eleven_v3",
                elevenlabs_output_format="mp3_44100_128",
            ),
            urlopen=fake_urlopen,
        )

    assert "secret-key" not in str(exc_info.value)
