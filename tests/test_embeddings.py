import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
import torch

from backend.audio import embeddings


def _sine_wav_bytes(seconds: float = 0.5, sr: int = 24_000) -> bytes:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


def test_pick_device_returns_known_value() -> None:
    assert embeddings.pick_device() in {"cuda", "mps", "cpu"}


def test_waveform_from_bytes_is_mono_24k() -> None:
    wav = embeddings._waveform_from_bytes(_sine_wav_bytes())
    assert wav.shape[0] == 1
    assert wav.dtype == torch.float32
    assert wav.numel() > 0


def test_embed_preview_with_mocked_model() -> None:
    fake = torch.randn(1, embeddings.EMBED_DIM)
    model = MagicMock()
    model.return_value = fake
    model.to.return_value = model
    model.eval.return_value = model

    with (
        patch.object(embeddings, "_load_model", return_value=(model, "cpu")),
        patch.object(embeddings, "fetch_preview_bytes", return_value=_sine_wav_bytes()),
    ):
        vector = embeddings.embed_preview("https://example.com/preview.mp3")

    assert len(vector) == embeddings.EMBED_DIM
    assert all(isinstance(x, float) for x in vector)
    model.assert_called_once()


def test_embed_preview_empty_bytes() -> None:
    with pytest.raises(embeddings.EmbedError, match="empty"):
        embeddings.embed_preview(b"")


def test_fetch_preview_bytes_network_error() -> None:
    with patch.object(
        embeddings.urllib.request,
        "urlopen",
        side_effect=embeddings.urllib.error.URLError("down"),
    ):
        with pytest.raises(embeddings.EmbedError, match="download"):
            embeddings.fetch_preview_bytes("https://example.com/x.mp3")
