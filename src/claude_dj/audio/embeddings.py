"""Audio embedding generation for Claude DJ.

This module will own MuQ-MuLan loading and preview-audio-to-vector generation.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import http.client
import math
from pathlib import Path
import sqlite3
import tempfile
import urllib.request

import librosa
import numpy as np
import torch
from muq import MuQMuLan

from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    CatalogStatus,
    TrackEmbeddingCandidate,
    fetch_tracks_needing_embeddings,
    get_catalog_status,
    upsert_track_embedding,
)


MUQ_MULAN_MODEL_NAME = "OpenMuQ/MuQ-MuLan-large"
MUQ_MULAN_MODEL_VERSION = None
MUQ_MULAN_SAMPLE_RATE = 24_000
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
PREVIEW_DOWNLOAD_WORKERS = 4
REQUEST_TIMEOUT_SECONDS = 10


class PreviewEmbeddingError(RuntimeError):
    """Expected per-preview failure while generating an audio embedding."""


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
    preview_download_workers: int = PREVIEW_DOWNLOAD_WORKERS,
    urlopen=urllib.request.urlopen,
) -> EmbeddingGenerationSummary:
    """Generate MuQ-MuLan embeddings for matched Deezer preview URLs."""
    candidates = fetch_tracks_needing_embeddings(db, limit=max_tracks)
    if not candidates:
        return EmbeddingGenerationSummary(catalog_status=get_catalog_status(db))

    model = _load_model()
    embedded_count = 0
    failed_count = 0
    workers = max(preview_download_workers, 1)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for batch in _batches(candidates, workers):
            decoded_previews = list(
                executor.map(
                    lambda candidate: _decode_candidate_preview(candidate, urlopen=urlopen),
                    batch,
                )
            )
            for decoded_preview in decoded_previews:
                if decoded_preview.error is not None:
                    failed_count += 1
                    continue

                try:
                    embedding = _embed_waveform(model, decoded_preview.waveform)
                except PreviewEmbeddingError:
                    failed_count += 1
                    continue

                upsert_track_embedding(
                    db,
                    track_id=decoded_preview.track_id,
                    embedding=embedding,
                    model_name=MUQ_MULAN_MODEL_NAME,
                    model_version=MUQ_MULAN_MODEL_VERSION,
                    dimensions=EMBEDDING_DIMENSIONS,
                )
                embedded_count += 1

    db.commit()
    return EmbeddingGenerationSummary(
        catalog_status=get_catalog_status(db),
        embedded_count=embedded_count,
        failed_count=failed_count,
    )


@dataclass(frozen=True)
class DecodedPreview:
    """Decoded preview audio ready for single-worker model inference."""

    track_id: int
    waveform: np.ndarray
    error: PreviewEmbeddingError | None = None


def _decode_candidate_preview(
    candidate: TrackEmbeddingCandidate,
    *,
    urlopen,
) -> DecodedPreview:
    try:
        preview_bytes = _download_preview_bytes(candidate.preview_url, urlopen=urlopen)
        waveform = _decode_preview_bytes(preview_bytes)
    except PreviewEmbeddingError as exc:
        return DecodedPreview(track_id=candidate.track_id, waveform=np.array([], dtype=np.float32), error=exc)
    return DecodedPreview(track_id=candidate.track_id, waveform=waveform)


def _batches(candidates: list[TrackEmbeddingCandidate], size: int):
    for index in range(0, len(candidates), size):
        yield candidates[index : index + size]


def _load_model() -> MuQMuLan:
    device = _select_device()
    model = MuQMuLan.from_pretrained(MUQ_MULAN_MODEL_NAME)
    return model.to(device).float().eval()


def _select_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps"
    return "cpu"


def _download_preview_bytes(preview_url: str, *, urlopen) -> bytes:
    request = urllib.request.Request(preview_url, method="GET")
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            preview_bytes = response.read(MAX_PREVIEW_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise PreviewEmbeddingError("Could not download preview audio.") from exc
    if len(preview_bytes) > MAX_PREVIEW_BYTES:
        raise PreviewEmbeddingError("Preview audio exceeded maximum download size.")
    if not preview_bytes:
        raise PreviewEmbeddingError("Preview audio response was empty.")
    return preview_bytes


def _decode_preview_bytes(preview_bytes: bytes) -> np.ndarray:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "preview.mp3"
        temp_path.write_bytes(preview_bytes)
        try:
            waveform, _sample_rate = librosa.load(
                temp_path,
                sr=MUQ_MULAN_SAMPLE_RATE,
                mono=True,
            )
        except Exception as exc:
            # librosa delegates to multiple audio backends with inconsistent error types.
            raise PreviewEmbeddingError("Could not decode preview audio.") from exc
    if waveform.size == 0:
        raise PreviewEmbeddingError("Preview audio decoded to an empty waveform.")
    return waveform.astype(np.float32, copy=False)


def _embed_waveform(model: MuQMuLan, waveform: np.ndarray) -> list[float]:
    device = next(model.parameters()).device
    wavs = torch.from_numpy(waveform).unsqueeze(0).to(device)
    try:
        with torch.no_grad():
            embedding_tensor = model(wavs=wavs).squeeze(0).detach().cpu().float()
    except RuntimeError as exc:
        raise PreviewEmbeddingError("Could not generate MuQ-MuLan embedding.") from exc
    embedding = embedding_tensor.tolist()
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise PreviewEmbeddingError(
            f"MuQ-MuLan returned {len(embedding)} dimensions, expected {EMBEDDING_DIMENSIONS}."
        )
    if not all(math.isfinite(value) for value in embedding):
        raise PreviewEmbeddingError("MuQ-MuLan returned a non-finite embedding.")
    return embedding
