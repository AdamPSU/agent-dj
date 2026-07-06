"""Audio embedding generation for Claude DJ."""

from dataclasses import dataclass
import http.client
import math
from pathlib import Path
import sqlite3
import tempfile
import time
import urllib.request

import librosa
import numpy as np

from claude_dj.config import EmbeddingConfig, get_embedding_config
from claude_dj.storage.db import (
    CatalogStatus,
    TrackEmbeddingCandidate,
    fetch_tracks_needing_embeddings,
    get_catalog_status,
    initialize_schema,
    upsert_track_embedding,
)


MUQ_SAMPLE_RATE = 24_000
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 10
PREVIEW_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 Claude-DJ/0.1"}


class PreviewEmbeddingError(RuntimeError):
    """Expected per-preview failure while generating an audio embedding."""


@dataclass(frozen=True)
class EmbeddingGenerationSummary:
    """Summary of an audio embedding generation pass."""

    catalog_status: CatalogStatus
    model_name: str
    dimensions: int
    embedded_count: int = 0
    failed_count: int = 0
    timing: dict[str, float] | None = None

    def to_json(self) -> dict[str, int | bool | str | dict[str, float]]:
        """Serialize embedding-generation status for daemon responses."""
        payload: dict[str, int | bool | str | dict[str, float]] = {
            "ran": self.embedded_count > 0 or self.failed_count > 0,
            "model": self.model_name,
            "dimensions": self.dimensions,
            "embedded_count": self.embedded_count,
            "failed_count": self.failed_count,
        }
        if self.timing is not None:
            payload["timing"] = self.timing
        return payload


class PreviewEmbedder:
    """Interface implemented by embedding providers."""

    model_name: str
    model_version: str | None
    dimensions: int

    def embed(self, candidate: TrackEmbeddingCandidate) -> list[float]:
        raise NotImplementedError


def generate_audio_embeddings(
    db: sqlite3.Connection,
    *,
    embedder: PreviewEmbedder | None = None,
    limit: int | None = None,
) -> EmbeddingGenerationSummary:
    """Generate embeddings for matched Deezer preview URLs."""
    resolved_embedder = embedder or create_preview_embedder(get_embedding_config())
    candidates = fetch_tracks_needing_embeddings(db, limit=limit)
    if not candidates:
        return EmbeddingGenerationSummary(
            catalog_status=get_catalog_status(db),
            model_name=resolved_embedder.model_name,
            dimensions=resolved_embedder.dimensions,
        )

    embedded_count = 0
    failed_count = 0
    active_model: tuple[str, str | None, int] | None = None

    for candidate in candidates:
        try:
            embedding = resolved_embedder.embed(candidate)
        except PreviewEmbeddingError:
            failed_count += 1
            continue

        model_key = (
            resolved_embedder.model_name,
            resolved_embedder.model_version,
            resolved_embedder.dimensions,
        )
        if model_key != active_model:
            if active_model is not None:
                embedded_count = 0
            initialize_schema(
                db,
                dimensions=resolved_embedder.dimensions,
                model_name=resolved_embedder.model_name,
                model_version=resolved_embedder.model_version,
            )
            active_model = model_key

        if not _valid_embedding(embedding, resolved_embedder.dimensions):
            failed_count += 1
            continue
        upsert_track_embedding(
            db,
            track_id=candidate.track_id,
            embedding=embedding,
            model_name=resolved_embedder.model_name,
            model_version=resolved_embedder.model_version,
            dimensions=resolved_embedder.dimensions,
        )
        db.commit()
        embedded_count += 1

    return EmbeddingGenerationSummary(
        catalog_status=get_catalog_status(db),
        model_name=resolved_embedder.model_name,
        dimensions=resolved_embedder.dimensions,
        embedded_count=embedded_count,
        failed_count=failed_count,
        timing=_embedder_timing(resolved_embedder),
    )


def create_preview_embedder(config: EmbeddingConfig) -> PreviewEmbedder:
    """Create the configured embedding provider."""
    return LocalMuQEmbedder(
        model_name=config.model_name,
        model_version=config.model_version,
        dimensions=config.dimensions,
    )


class LocalMuQEmbedder(PreviewEmbedder):
    """Local MuQ audio embedder."""

    def __init__(
        self,
        *,
        model_name: str,
        model_version: str | None,
        dimensions: int,
        urlopen=urllib.request.urlopen,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.dimensions = dimensions
        self.urlopen = urlopen
        self._model = None
        self._device: str | None = None
        self._model_load_seconds: float | None = None
        self.last_timing: dict[str, float] | None = None

    def embed(self, candidate: TrackEmbeddingCandidate) -> list[float]:
        waveform = _decode_preview_bytes(
            _download_preview_bytes(candidate.preview_url, urlopen=self.urlopen),
            sample_rate=MUQ_SAMPLE_RATE,
        )
        return self._embed_waveform(waveform)

    def _embed_waveform(self, waveform: np.ndarray) -> list[float]:
        import torch

        model, device = self._load_model()
        inference_started_at = time.perf_counter()
        try:
            wavs = torch.from_numpy(waveform).unsqueeze(0).to(device)
            with torch.no_grad():
                output = model(wavs, output_hidden_states=False)
                embedding_tensor = output.last_hidden_state.mean(dim=1).squeeze(0)
                embedding_tensor = torch.nn.functional.normalize(embedding_tensor, p=2.0, dim=0)
                embedding_tensor = embedding_tensor.detach().cpu().float()
        except (RuntimeError, ValueError) as exc:
            raise PreviewEmbeddingError("Could not generate MuQ embedding.") from exc
        inference_seconds = time.perf_counter() - inference_started_at
        self.last_timing = {"inference_seconds": inference_seconds}
        if self._model_load_seconds is not None:
            self.last_timing["model_load_seconds"] = self._model_load_seconds
        return embedding_tensor.tolist()

    def _load_model(self):
        if self._model is not None and self._device is not None:
            return self._model, self._device

        import torch

        started_at = time.perf_counter()
        try:
            _install_muq_audio_only_xclip_stub()
            from muq.muq import MuQ

            self._device = _select_torch_device(torch)
            self._model = MuQ.from_pretrained(self.model_name).to(self._device).float().eval()
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise PreviewEmbeddingError("Could not initialize MuQ embedding model.") from exc
        self._model_load_seconds = time.perf_counter() - started_at
        return self._model, self._device


def _select_torch_device(torch_module) -> str:
    if torch_module.cuda.is_available():
        return "cuda"
    mps_backend = getattr(torch_module.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps"
    return "cpu"


def _install_muq_audio_only_xclip_stub() -> None:
    import importlib.machinery
    import sys
    import types

    class _UnusedXClipTokenizer:
        vocab_size = 49_408

        def tokenize(self, _raw_texts):
            raise RuntimeError("Text tokenization is not available in the MuQ audio embedder.")

    x_clip = types.ModuleType("x_clip")
    x_clip_tokenizer = types.ModuleType("x_clip.tokenizer")
    x_clip.__spec__ = importlib.machinery.ModuleSpec("x_clip", loader=None, is_package=True)
    x_clip.__path__ = []
    x_clip_tokenizer.__spec__ = importlib.machinery.ModuleSpec("x_clip.tokenizer", loader=None)
    x_clip_tokenizer.tokenizer = _UnusedXClipTokenizer()
    sys.modules["x_clip"] = x_clip
    sys.modules["x_clip.tokenizer"] = x_clip_tokenizer


def _download_preview_bytes(preview_url: str, *, urlopen) -> bytes:
    request = urllib.request.Request(preview_url, headers=PREVIEW_REQUEST_HEADERS, method="GET")
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


def _decode_preview_bytes(preview_bytes: bytes, *, sample_rate: int) -> np.ndarray:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "preview.mp3"
        temp_path.write_bytes(preview_bytes)
        try:
            waveform, _sample_rate = librosa.load(temp_path, sr=sample_rate, mono=True)
        except Exception as exc:
            raise PreviewEmbeddingError("Could not decode preview audio.") from exc
    if waveform.size == 0:
        raise PreviewEmbeddingError("Preview audio decoded to an empty waveform.")
    return waveform.astype(np.float32, copy=False)


def _valid_embedding(embedding: list[float], dimensions: int) -> bool:
    return len(embedding) == dimensions and all(math.isfinite(value) for value in embedding)


def _embedder_timing(embedder: PreviewEmbedder) -> dict[str, float] | None:
    timing = getattr(embedder, "last_timing", None)
    return timing if isinstance(timing, dict) else None
