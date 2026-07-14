import io
import urllib.error
import urllib.request
from functools import lru_cache

import librosa
import numpy as np
import soundfile as sf
import torch

SAMPLE_RATE = 24_000
EMBED_DIM = 512


class EmbedError(Exception):
    """Raised when audio cannot be loaded or embedded."""


def pick_device() -> str:
    """Choose the fastest available compute device for the model."""
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def _load_model():
    """Load MuQ-MuLan once and keep it in memory for later embeds."""
    from muq import MuQMuLan

    device = pick_device()
    model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large")
    model = model.to(device).eval()
    return model, device


def _waveform_from_bytes(data: bytes) -> torch.Tensor:
    """Decode audio bytes to a mono 24 kHz waveform tensor."""
    try:
        audio, sr = sf.read(io.BytesIO(data), always_2d=False)
    except Exception:
        try:
            audio, sr = librosa.load(io.BytesIO(data), sr=SAMPLE_RATE, mono=True)
            return torch.tensor(audio, dtype=torch.float32).unsqueeze(0)
        except Exception as exc:
            raise EmbedError(f"could not decode audio: {exc}") from exc

    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    if sr != SAMPLE_RATE:
        audio = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=sr, target_sr=SAMPLE_RATE)
    else:
        audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        raise EmbedError("audio is empty")
    return torch.tensor(audio, dtype=torch.float32).unsqueeze(0)


def fetch_preview_bytes(url: str) -> bytes:
    """Download a short preview clip into memory (not saved to disk)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmbedError(f"could not download preview: {exc}") from exc


def embed_preview(source: str | bytes) -> list[float]:
    """
    Turn a Deezer preview URL (or raw audio bytes) into a 512-number music fingerprint.
    The model loads on first use and stays warm in this process.
    """
    if isinstance(source, str):
        data = fetch_preview_bytes(source)
    else:
        data = source
    if not data:
        raise EmbedError("audio is empty")

    wavs = _waveform_from_bytes(data)
    model, device = _load_model()
    wavs = wavs.to(device)

    try:
        with torch.no_grad():
            embeds = model(wavs=wavs)
    except Exception as exc:
        raise EmbedError(f"embedding failed: {exc}") from exc

    vector = embeds.detach().float().cpu().numpy().reshape(-1)
    if vector.shape[0] != EMBED_DIM:
        raise EmbedError(f"expected {EMBED_DIM}-d embedding, got {vector.shape[0]}")
    return vector.tolist()
