from types import SimpleNamespace

import pytest
import torch

import claude_dj.audio.embeddings as embedding_module
from claude_dj.config import LOCAL_MUQ_MODEL_NAME
from claude_dj.audio.embeddings import (
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


def test_create_preview_embedder_returns_local_muq_embedder() -> None:
    assert hasattr(embedding_module, "LocalMuQEmbedder")

    embedder = embedding_module.create_preview_embedder(embedding_module.get_embedding_config())

    assert isinstance(embedder, embedding_module.LocalMuQEmbedder)
    assert embedder.model_name == LOCAL_MUQ_MODEL_NAME


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
        initialize_schema(db, dimensions=1024)
        first_track_id = add_matched_track(db, index=1)
        second_track_id = add_matched_track(db, index=2)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_MUQ_MODEL_NAME, dimensions=1024)

        summary = generate_audio_embeddings(db, embedder=embedder)

        assert embedder.calls == [first_track_id, second_track_id]
        assert summary.embedded_count == 2
        assert summary.failed_count == 0
    finally:
        db.close()


def test_generate_audio_embeddings_counts_embedder_failures(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=1024)
        track_id = add_matched_track(db)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_MUQ_MODEL_NAME, dimensions=1024, failures=[track_id])

        summary = generate_audio_embeddings(db, embedder=embedder)

        assert summary.embedded_count == 0
        assert summary.failed_count == 1
        assert summary.catalog_status.embedding_count == 0
    finally:
        db.close()


def test_generate_audio_embeddings_limits_one_chunk(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db, dimensions=1024)
        for index in range(1, 12):
            add_matched_track(db, index=index)
        db.commit()
        embedder = FakeEmbedder(model_name=LOCAL_MUQ_MODEL_NAME, dimensions=1024)

        summary = generate_audio_embeddings(db, embedder=embedder, limit=10)

        assert len(embedder.calls) == 10
        assert summary.embedded_count == 10
        assert summary.catalog_status.embedding_count == 10
        assert summary.catalog_status.embedding_pending_count == 1
    finally:
        db.close()


def test_generate_audio_embeddings_commits_each_successful_embedding(tmp_path) -> None:
    database_file = tmp_path / "claude-dj.sqlite3"
    db = connect(database_file)

    class ObservingEmbedder(FakeEmbedder):
        def embed(self, candidate: TrackEmbeddingCandidate):
            embedding = super().embed(candidate)
            observer = connect(database_file)
            try:
                self.observations.append(
                    observer.execute("SELECT COUNT(*) AS count FROM track_embeddings").fetchone()["count"]
                )
            finally:
                observer.close()
            return embedding

    try:
        initialize_schema(db, dimensions=1024)
        add_matched_track(db, index=1)
        add_matched_track(db, index=2)
        db.commit()
        embedder = ObservingEmbedder(model_name=LOCAL_MUQ_MODEL_NAME, dimensions=1024)
        embedder.observations = []

        generate_audio_embeddings(db, embedder=embedder, limit=2)

        assert embedder.observations == [0, 1]
    finally:
        db.close()
