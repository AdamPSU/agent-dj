"""Embedding similarity recommendation tests."""

import random

from claude_dj.recommendation.similarity import (
    DJTrack,
    SimilarTrack,
    find_similar_tracks,
    generate_next_dj_block,
)
from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    connect,
    initialize_schema,
    replace_source_tracks,
    upsert_source,
    upsert_track,
    upsert_track_embedding,
)


def test_find_similar_tracks_returns_nearest_neighbors(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        for track_id in (1, 2, 3):
            upsert_track(
                db,
                spotify_track_id=f"spotify-track-{track_id}",
                spotify_uri=f"spotify:track:{track_id}",
                isrc=f"US{track_id}",
                title=f"Track {track_id}",
                artist_name="Artist",
                album_name=None,
                duration_ms=None,
                explicit=False,
                popularity=None,
            )
        upsert_track_embedding(
            db,
            track_id=1,
            embedding=[0.0] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
        )
        upsert_track_embedding(
            db,
            track_id=2,
            embedding=[0.1] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
        )
        upsert_track_embedding(
            db,
            track_id=3,
            embedding=[1.0] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
        )
        db.commit()

        results = find_similar_tracks(db, seed_track_id=1, limit=2)

        assert [result.track_id for result in results] == [2, 3]
        assert all(isinstance(result, SimilarTrack) for result in results)
        assert results[0].distance < results[1].distance
    finally:
        db.close()


def test_find_similar_tracks_returns_empty_when_seed_has_no_embedding(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)

        assert find_similar_tracks(db, seed_track_id=99, limit=10) == []
    finally:
        db.close()


def test_generate_next_dj_block_includes_playlist_seed_and_similar_tracks(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Playlist 1",
            description=None,
        )
        track_ids = _insert_embedded_tracks(db, count=8)
        replace_source_tracks(
            db,
            source_id,
            [(track_id, position, None) for position, track_id in enumerate(track_ids)],
        )
        db.commit()

        block = generate_next_dj_block(db, rng=random.Random(1))

        assert block is not None
        assert block.source_id == source_id
        assert len(block.tracks) >= 3
        assert len(block.tracks) <= 8
        assert block.tracks[0] == DJTrack(track_id=block.seed_track_id, role="seed", distance=None)
        assert len({track.track_id for track in block.tracks}) == len(block.tracks)
        assert all(track.role == "similar" for track in block.tracks[1:])
    finally:
        db.close()


def test_generate_next_dj_block_keeps_similar_tracks_in_selected_playlist(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    class DeterministicChooser:
        def choice(self, values):
            return values[0]

        def randint(self, start, end):
            return 3

    try:
        initialize_schema(db)
        selected_source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Selected Playlist",
            description=None,
        )
        other_source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-2",
            name="Other Playlist",
            description=None,
        )
        seed_id = _insert_embedded_track(db, index=1, embedding_value=0.0)
        in_playlist_close_id = _insert_embedded_track(db, index=2, embedding_value=0.1)
        in_playlist_next_id = _insert_embedded_track(db, index=3, embedding_value=0.2)
        out_of_playlist_closest_id = _insert_embedded_track(db, index=4, embedding_value=0.01)
        replace_source_tracks(
            db,
            selected_source_id,
            [
                (seed_id, 0, None),
                (in_playlist_close_id, 1, None),
                (in_playlist_next_id, 2, None),
            ],
        )
        replace_source_tracks(db, other_source_id, [(out_of_playlist_closest_id, 0, None)])
        db.commit()

        block = generate_next_dj_block(
            db,
            rng=DeterministicChooser(),
            min_block_size=3,
            max_block_size=3,
        )

        assert block is not None
        assert block.source_id == selected_source_id
        assert [track.track_id for track in block.tracks] == [
            seed_id,
            in_playlist_close_id,
            in_playlist_next_id,
        ]
    finally:
        db.close()


def test_generate_next_dj_block_can_return_eight_tracks_by_default(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Playlist 1",
            description=None,
        )
        track_ids = _insert_embedded_tracks(db, count=8)
        replace_source_tracks(
            db,
            source_id,
            [(track_id, position, None) for position, track_id in enumerate(track_ids)],
        )
        db.commit()

        block = generate_next_dj_block(db, rng=random.Random(5))

        assert block is not None
        assert len(block.tracks) == 8
    finally:
        db.close()


def test_generate_next_dj_block_avoids_recently_played_tracks(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Playlist 1",
            description=None,
        )
        track_ids = _insert_embedded_tracks(db, count=8)
        replace_source_tracks(
            db,
            source_id,
            [(track_id, position, None) for position, track_id in enumerate(track_ids)],
        )
        db.commit()

        block = generate_next_dj_block(
            db,
            recently_played_track_ids=set(track_ids[:4]),
            rng=random.Random(1),
        )

        assert block is not None
        assert {track.track_id for track in block.tracks}.isdisjoint(track_ids[:4])
    finally:
        db.close()


def test_generate_next_dj_block_relaxes_cooldown_when_all_tracks_recently_played(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Playlist 1",
            description=None,
        )
        track_ids = _insert_embedded_tracks(db, count=4)
        replace_source_tracks(
            db,
            source_id,
            [(track_id, position, None) for position, track_id in enumerate(track_ids)],
        )
        db.commit()

        block = generate_next_dj_block(
            db,
            recently_played_track_ids=set(track_ids),
            rng=random.Random(1),
        )

        assert block is not None
        assert len(block.tracks) >= 3
        assert {track.track_id for track in block.tracks}.issubset(track_ids)
    finally:
        db.close()


def _insert_embedded_tracks(db, *, count: int) -> list[int]:
    track_ids = []
    for index in range(count):
        track_id = _insert_embedded_track(db, index=index, embedding_value=float(index) / 10.0)
        track_ids.append(track_id)
    return track_ids


def _insert_embedded_track(db, *, index: int, embedding_value: float) -> int:
    track_id = upsert_track(
        db,
        spotify_track_id=f"spotify-track-{index}",
        spotify_uri=f"spotify:track:{index}",
        isrc=f"US{index}",
        title=f"Track {index}",
        artist_name="Artist",
        album_name=None,
        duration_ms=None,
        explicit=False,
        popularity=None,
    )
    upsert_track_embedding(
        db,
        track_id=track_id,
        embedding=[embedding_value] * EMBEDDING_DIMENSIONS,
        model_name="OpenMuQ/MuQ-large-msd-iter",
        model_version=None,
    )
    return track_id
