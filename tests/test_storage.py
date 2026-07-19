import math

from claude_dj.embeddings import EMBED_DIM
from claude_dj.catalog import db


def _vec(seed: float) -> list[float]:
    raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def test_playlist_track_membership_and_similarity(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")

    pl = db.upsert_playlist(
        conn,
        spotify_id="pl1",
        name="Gym",
        snapshot_id="snap-a",
        owner_spotify_id="user1",
        tracks_total=2,
    )
    a = db.upsert_track(
        conn,
        spotify_id="sp:a",
        name="Alpha",
        artists="Artist A",
        isrc="USAAA0000001",
        album_name="LP",
        duration_ms=200_000,
    )
    b = db.upsert_track(
        conn,
        spotify_id="sp:b",
        name="Beta",
        artists="Artist B",
    )
    c = db.upsert_track(
        conn,
        spotify_id="sp:c",
        name="Close",
        artists="Artist C",
    )

    db.set_playlist_tracks(
        conn,
        pl,
        [
            (a, 0, "2024-01-01T00:00:00Z"),
            (b, 1, "2024-01-02T00:00:00Z"),
        ],
    )
    members = conn.execute(
        "SELECT track_id, position FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
        (pl,),
    ).fetchall()
    assert [(m["track_id"], m["position"]) for m in members] == [(a, 0), (b, 1)]

    db.set_playlist_tracks(conn, pl, [(c, 0, None)])
    members = conn.execute(
        "SELECT track_id FROM playlist_tracks WHERE playlist_id = ?",
        (pl,),
    ).fetchall()
    assert [m["track_id"] for m in members] == [c]

    db.upsert_embedding(conn, a, _vec(0.1))
    db.upsert_embedding(conn, b, _vec(9.9))
    db.upsert_embedding(conn, c, _vec(0.11))

    assert db.get_track(conn, a)["status"] == "indexed"
    hits = db.similar_tracks(conn, _vec(0.1), limit=2, exclude_track_id=a)
    assert [h["spotify_id"] for h in hits] == ["sp:c", "sp:b"]
    assert hits[0]["distance"] <= hits[1]["distance"]


def test_status_and_list_filters(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")
    t = db.upsert_track(conn, spotify_id="sp:x", name="X", artists="Y")
    assert db.get_track(conn, t)["status"] == "pending"

    db.set_status(conn, t, "skipped")
    assert db.list_tracks(conn, status="skipped")[0]["spotify_id"] == "sp:x"
    assert db.list_tracks(conn, status="pending") == []

    same = db.upsert_track(
        conn,
        spotify_id="sp:x",
        name="X2",
        artists="Y",
        status="pending",
    )
    assert same == t
    # re-upsert does not clobber terminal indexed; skipped can move via set_status
    db.set_status(conn, t, "retry")
    assert db.get_track(conn, t)["status"] == "retry"


def test_upsert_embedding_sets_indexed(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")
    t = db.upsert_track(conn, spotify_id="sp:e", name="E", artists="F")
    db.set_status(conn, t, "retry")
    db.upsert_embedding(conn, t, _vec(1.0))
    assert db.get_track(conn, t)["status"] == "indexed"


def test_delete_orphan_tracks(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")
    pl = db.upsert_playlist(conn, spotify_id="pl", name="P")
    keep = db.upsert_track(conn, spotify_id="keep", name="K", artists="A")
    gone = db.upsert_track(conn, spotify_id="gone", name="G", artists="B")
    db.set_playlist_tracks(conn, pl, [(keep, 0, None)])
    db.upsert_embedding(conn, gone, _vec(2.0))
    assert db.delete_orphan_tracks(conn) == 1
    assert db.get_track(conn, keep) is not None
    assert db.get_track(conn, gone) is None


def test_get_embedding_roundtrip(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")
    t = db.upsert_track(conn, spotify_id="sp:emb", name="E", artists="A")
    vec = _vec(3.5)
    db.upsert_embedding(conn, t, vec)
    got = db.get_embedding(conn, t)
    assert got is not None
    assert len(got) == EMBED_DIM
    assert all(abs(a - b) < 1e-5 for a, b in zip(got, vec, strict=True))
    assert db.get_embedding(conn, 99999) is None


def test_list_indexed_track_ids_and_count(tmp_path) -> None:
    conn = db.connect(tmp_path / "catalog.db")
    a = db.upsert_track(conn, spotify_id="sp:a", name="A", artists="A")
    b = db.upsert_track(conn, spotify_id="sp:b", name="B", artists="B")
    c = db.upsert_track(conn, spotify_id="sp:c", name="C", artists="C")
    db.upsert_embedding(conn, a, _vec(0.1))
    db.upsert_embedding(conn, b, _vec(0.2))
    db.set_status(conn, c, "pending")
    assert db.count_indexed(conn) == 2
    assert sorted(db.list_indexed_track_ids(conn)) == sorted([a, b])
    assert db.count_embed_remaining(conn) == 1
    db.set_status(conn, c, "retry")
    assert db.count_embed_remaining(conn) == 1
    db.set_status(conn, c, "skipped")
    assert db.count_embed_remaining(conn) == 0
