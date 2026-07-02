"""Audio embedding generation for Claude DJ.

This module will own MuQ-MuLan loading and preview-audio-to-vector generation.
"""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import urllib.request

import librosa
import torch
from muq import MuQMuLan

from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    CatalogStatus,
    fetch_tracks_needing_embeddings,
    get_catalog_status,
    upsert_track_embedding,
)


MUQ_MULAN_MODEL_NAME = "OpenMuQ/MuQ-MuLan-large"
MUQ_MULAN_MODEL_VERSION = None
MUQ_MULAN_SAMPLE_RATE = 24_000
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class EmbeddingGenerationSummary:
    """Summary of a local audio embedding generation pass."""

    catalog_status: CatalogStatus
    embedded_count: int = 0
    failed_count: int = 0

    def to_json(self) -> dict[str, int | bool | str]:
        """Serialize embedding-generation status for daemon responses."""
        return {
            "ran": self.embedded_count > 0 or self.failed_count > 0,
            "model": MUQ_MULAN_MODEL_NAME,
            "dimensions": EMBEDDING_DIMENSIONS,
            "embedded_count": self.embedded_count,
            "failed_count": self.failed_count,
        }


def generate_audio_embeddings(
    db: sqlite3.Connection,
    *,
    max_tracks: int | None = None,
    urlopen=urllib.request.urlopen,
) -> EmbeddingGenerationSummary:
    """Generate MuQ-MuLan embeddings for matched Deezer preview URLs."""
    candidates = fetch_tracks_needing_embeddings(db, limit=max_tracks)
    if not candidates:
        return EmbeddingGenerationSummary(catalog_status=get_catalog_status(db))

    model = _load_model()
    embedded_count = 0
    failed_count = 0

    for candidate in candidates:
        try:
            preview_audio = _download_preview_audio(candidate.preview_url, urlopen=urlopen)
            waveform = _decode_preview_audio(preview_audio)
            embedding = _embed_waveform(model, waveform)
            upsert_track_embedding(
                db,
                track_id=candidate.track_id,
                embedding=embedding,
                model_name=MUQ_MULAN_MODEL_NAME,
                model_version=MUQ_MULAN_MODEL_VERSION,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        except Exception:
            failed_count += 1
        else:
            embedded_count += 1

    db.commit()
    return EmbeddingGenerationSummary(
        catalog_status=get_catalog_status(db),
        embedded_count=embedded_count,
        failed_count=failed_count,
    )


def _load_model() -> MuQMuLan:
    device = _select_device()
    model = MuQMuLan.from_pretrained(MUQ_MULAN_MODEL_NAME)
    return model.to(device).float().eval()


def _select_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _download_preview_audio(preview_url: str, *, urlopen) -> bytes:
    request = urllib.request.Request(preview_url, method="GET")
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        audio = response.read(MAX_PREVIEW_BYTES + 1)
    if len(audio) > MAX_PREVIEW_BYTES:
        raise ValueError("Preview audio exceeded maximum download size.")
    if not audio:
        raise ValueError("Preview audio response was empty.")
    return audio


def _decode_preview_audio(preview_audio: bytes) -> list[float]:
    temp_path = _write_temp_preview_file(preview_audio)
    try:
        waveform, _sample_rate = librosa.load(temp_path, sr=MUQ_MULAN_SAMPLE_RATE, mono=True)
    finally:
        _remove_temp_file(temp_path)
    if waveform.size == 0:
        raise ValueError("Preview audio decoded to an empty waveform.")
    return waveform.astype("float32").tolist()


def _write_temp_preview_file(preview_audio: bytes) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
        temp_file.write(preview_audio)
        return Path(temp_file.name)


def _remove_temp_file(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _embed_waveform(model: MuQMuLan, waveform: list[float]) -> list[float]:
    device = next(model.parameters()).device
    wavs = torch.tensor(waveform, dtype=torch.float32).unsqueeze(0).to(device)
    with torch.no_grad():
        embedding_tensor = model(wavs=wavs).squeeze(0).detach().cpu().float()
    embedding = embedding_tensor.tolist()
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"MuQ-MuLan returned {len(embedding)} dimensions, expected {EMBEDDING_DIMENSIONS}."
        )
    if not all(math.isfinite(value) for value in embedding):
        raise ValueError("MuQ-MuLan returned a non-finite embedding.")
    return embedding
