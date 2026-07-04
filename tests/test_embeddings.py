from types import SimpleNamespace

import pytest
import torch

import claude_dj.audio.embeddings as embedding_module
from claude_dj.config import LOCAL_CLAP_MODEL_NAME, LOCAL_MUQ_MODEL_NAME
from claude_dj.audio.embeddings import (
    LocalClapEmbedder,
    PreviewEmbeddingError,
    generate_audio_embeddings,
)
from claude_dj.storage.db import TrackEmbeddingCandidate
from claude_dj.storage.db import (
    connect,
    initialize_schema,
    upsert_preview_match,
    upsert_track,
)


class FakeEmbedder:
    def __init__(self, *, model_name: str, dimensions: int, failures=None, timing=None) -> None:
        self.model_name = model_name
        self.model_version = None
        self.dimensions = dimensions
        self.failures = failures or []
        self.last_timing = timing
        self.calls = []

    def embed(self, candidate):
        self.calls.append(candidate.track_id)
        if candidate.track_id in self.failures:
            raise PreviewEmbeddingError("Could not embed preview.")
        return [1.0] + [0.0] * (self.dimensions - 1)


def add_matched_track(db, *, index: int = 1) -> int:
    track_id = upsert_track(
        db,
        spotify_track_id=f"spotify-track-{index}",
        spotify_uri=f"spotify:track:{index}",
        isrc=f"USUM7190076{index}",
        title=f"Track {index}",
        artist_name="Artist",
        album_name=None,
        duration_ms=None,
        explicit=False,
        popularity=None,
    )
    upsert_preview_match(
        db,
        track_id=track_id,
        provider="deezer",
        provider_track_id=f"deezer-{index}",
        preview_url=f"https://example.com/preview-{index}.mp3",
        match_method="isrc",
        status="matched",
        failure_reason=None,
    )
    return track_id


def test_local_clap_embedder_uses_pooler_output() -> None:
    class FakeProcessor:
        def __call__(self, *, audio, sampling_rate, return_tensors):
            assert sampling_rate == 48_000
            assert return_tensors == "pt"
            return {"input_features": torch.tensor([[1.0, 2.0]])}

    class FakeModel:
        def get_audio_features(self, **inputs):
            assert "input_features" in inputs
            return SimpleNamespace(pooler_output=torch.tensor([[3.0, 4.0] + [0.0] * 510]))

    embedder = LocalClapEmbedder(model_name=LOCAL_CLAP_MODEL_NAME, model_version=None, dimensions=512)
    embedder._processor = FakeProcessor()
    embedder._model = FakeModel()
    embedder._device = "cpu"

    embedding = embedder._embed_waveform(torch.tensor([0.1, 0.2]).numpy())

    assert len(embedding) == 512
    assert embedding[0] == pytest.approx(0.6)
    assert embedding[1] == pytest.approx(0.8)
    assert sum(value * value for value in embedding) == pytest.approx(1.0)


def test_local_muq_embedder_uses_last_hidden_state_mean() -> None:
    assert hasattr(embedding_module, "LocalMuQEmbedder")
    LocalMuQEmbedder = embedding_module.LocalMuQEmbedder

    class FakeModel:
        def __call__(self, wavs, *, output_hidden_states):
            assert wavs.shape == (1, 2)
            assert output_hidden_states is False
            return SimpleNamespace(last_hidden_state=torch.tensor([[[3.0, 4.0] + [0.0] * 1022]]))

    embedder = LocalMuQEmbedder(model_name=LOCAL_MUQ_MODEL_NAME, model_version=None, dimensions=1024)
    embedder._model = FakeModel()
    embedder._device = "cpu"

    embedding = embedder._embed_waveform(torch.tensor([0.1, 0.2]).numpy())

    assert len(embedding) == 1024
    assert embedding[0] == pytest.approx(0.6)
    assert embedding[1] == pytest.approx(0.8)
    assert sum(value * value for value in embedding) == pytest.approx(1.0)


def test_fallback_embedder_switches_to_clap_when_muq_fails() -> None:
    assert hasattr(embedding_module, "EmbeddingModelError")
    assert hasattr(embedding_module, "FallbackPreviewEmbedder")
    EmbeddingModelError = embedding_module.EmbeddingModelError
    FallbackPreviewEmbedder = embedding_module.FallbackPreviewEmbedder

    class FailingMuQEmbedder:
        model_name = LOCAL_MUQ_MODEL_NAME
        model_version = None
        dimensions = 1024

        def __init__(self) -> None:
            self.calls = []

        def embed(self, candidate):
            self.calls.append(candidate.track_id)
            raise EmbeddingModelError("MuQ unavailable")

    class RecordingClapEmbedder:
        model_name = LOCAL_CLAP_MODEL_NAME
        model_version = None
        dimensions = 512

        def __init__(self) -> None:
            self.calls = []

        def embed(self, candidate):
            self.calls.append(candidate.track_id)
            return [1.0] + [0.0] * 511

    primary = FailingMuQEmbedder()
    fallback = RecordingClapEmbedder()
    embedder = FallbackPreviewEmbedder(primary=primary, fallback=fallback)

    first_embedding = embedder.embed(TrackEmbeddingCandidate(track_id=1, preview_url="https://example.com/one.mp3"))
    second_embedding = embedder.embed(TrackEmbeddingCandidate(track_id=2, preview_url="https://example.com/two.mp3"))

    assert first_embedding == [1.0] + [0.0] * 511
    assert second_embedding == [1.0] + [0.0] * 511
    assert primary.calls == [1]
    assert fallback.calls == [1, 2]
    assert embedder.model_name == LOCAL_CLAP_MODEL_NAME
    assert embedder.dimensions == 512


def test_fallback_embedder_keeps_primary_metadata_when_fallback_fails() -> None:
    assert hasattr(embedding_module, "EmbeddingModelError")
    assert hasattr(embedding_module, "FallbackPreviewEmbedder")
    EmbeddingModelError = embedding_module.EmbeddingModelError
    FallbackPreviewEmbedder = embedding_module.FallbackPreviewEmbedder

    class FailingMuQEmbedder:
        model_name = LOCAL_MUQ_MODEL_NAME
        model_version = None
        dimensions = 1024

        def embed(self, candidate):
            raise EmbeddingModelError("MuQ unavailable")

    class FailingClapEmbedder:
        model_name = LOCAL_CLAP_MODEL_NAME
        model_version = None
        dimensions = 512

        def embed(self, candidate):
            raise EmbeddingModelError("CLAP unavailable")

    embedder = FallbackPreviewEmbedder(primary=FailingMuQEmbedder(), fallback=FailingClapEmbedder())

    with pytest.raises(EmbeddingModelError):
        embedder.embed(TrackEmbeddingCandidate(track_id=1, preview_url="https://example.com/one.mp3"))

    assert embedder.model_name == LOCAL_MUQ_MODEL_NAME
    assert embedder.dimensions == 1024


def test_generate_audio_embeddings_stores_local_muq_vectors(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=1024)
        track_id = add_matched_track(db)
        db.commit()
        embedder = FakeEmbedder(
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=1024,
            timing={"inference_seconds": 0.4, "total_seconds": 1.2},
        )

        summary = generate_audio_embeddings(db, embedder=embedder)

        metadata = db.execute(
            "SELECT * FROM embedding_metadata WHERE track_id = ?",
            (track_id,),
        ).fetchone()
        embedding_row = db.execute(
            "SELECT track_id FROM track_embeddings WHERE track_id = ?",
            (track_id,),
        ).fetchone()

        assert summary.embedded_count == 1
        assert summary.failed_count == 0
        assert summary.catalog_status.embedding_count == 1
        assert summary.to_json()["timing"] == {"inference_seconds": 0.4, "total_seconds": 1.2}
        assert metadata["model_name"] == LOCAL_MUQ_MODEL_NAME
        assert metadata["dimensions"] == 1024
        assert embedding_row["track_id"] == track_id
    finally:
        db.close()


def test_generate_audio_embeddings_embeds_tracks_one_at_a_time(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=512)
        first_track_id = add_matched_track(db, index=1)
        second_track_id = add_matched_track(db, index=2)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_CLAP_MODEL_NAME, dimensions=512)

        summary = generate_audio_embeddings(db, embedder=embedder)

        assert embedder.calls == [first_track_id, second_track_id]
        assert summary.embedded_count == 2
        assert summary.failed_count == 0
    finally:
        db.close()


def test_generate_audio_embeddings_uses_local_clap_dimensions(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=512)
        track_id = add_matched_track(db)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_CLAP_MODEL_NAME, dimensions=512)

        summary = generate_audio_embeddings(db, embedder=embedder)

        metadata = db.execute(
            "SELECT * FROM embedding_metadata WHERE track_id = ?",
            (track_id,),
        ).fetchone()

        assert summary.embedded_count == 1
        assert summary.failed_count == 0
        assert metadata["model_name"] == LOCAL_CLAP_MODEL_NAME
        assert metadata["dimensions"] == 512
    finally:
        db.close()


def test_generate_audio_embeddings_counts_embedder_failures(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=512)
        track_id = add_matched_track(db)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_CLAP_MODEL_NAME, dimensions=512, failures=[track_id])

        summary = generate_audio_embeddings(db, embedder=embedder)

        assert summary.embedded_count == 0
        assert summary.failed_count == 1
        assert summary.catalog_status.embedding_count == 0
    finally:
        db.close()
