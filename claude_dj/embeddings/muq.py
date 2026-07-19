import contextlib
import io
import os
import tempfile
import urllib.error
import urllib.request
import warnings
from functools import lru_cache

# Keep librosa/joblib single-process so abrupt stops don't leave loky semaphore warnings.
os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import librosa
import numpy as np
import soundfile as sf
import torch

SAMPLE_RATE = 24_000
EMBED_DIM = 512


class EmbedError(Exception):
    """Raised when audio cannot be loaded or embedded."""


@contextlib.contextmanager
def _quiet_c_stderr():
    """Hide noisy C-library messages (e.g. mpg123 ID3 warnings) during decode."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)
        os.close(devnull_fd)


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
    # MuQ loads a text tower from a base checkpoint; extra LM-head weights are unused noise.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large")
    model = model.to(device).eval()
    return model, device


def ensure_model_loaded() -> str:
    """Download (if needed) and load MuQ into memory. Returns device name."""
    _, device = _load_model()
    return device


def _waveform_from_bytes(data: bytes) -> torch.Tensor:
    """Decode audio bytes to a mono 24 kHz waveform tensor."""
    # In-memory decode works for WAV; Deezer previews are MP3 and need a real path.
    try:
        with _quiet_c_stderr():
            audio, sr = sf.read(io.BytesIO(data), always_2d=False)
        if getattr(audio, "ndim", 1) > 1:
            audio = np.mean(audio, axis=1)
        if sr != SAMPLE_RATE:
            audio = librosa.resample(
                np.asarray(audio, dtype=np.float32),
                orig_sr=sr,
                target_sr=SAMPLE_RATE,
            )
        else:
            audio = np.asarray(audio, dtype=np.float32)
    except Exception:
        suffix = ".mp3" if data[:3] == b"ID3" or data[:2] == b"\xff\xfb" else ".bin"
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            with _quiet_c_stderr():
                audio, _sr = librosa.load(path, sr=SAMPLE_RATE, mono=True)
            audio = np.asarray(audio, dtype=np.float32)
        except Exception as exc:
            raise EmbedError(f"could not decode audio: {exc}") from exc
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

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
