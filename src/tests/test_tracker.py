import json
from pathlib import Path

from backend import tracker


def test_format_ms() -> None:
    assert tracker.format_ms(0) == "0:00"
    assert tracker.format_ms(102_000) == "1:42"
    assert tracker.format_ms(190_000) == "3:10"
    assert tracker.format_ms(3_661_000) == "1:01:01"
    assert tracker.format_ms(None) == "--:--"


def test_snapshot_payload() -> None:
    from backend import tracker

    snap = {
        "fetched_at": 1000.0,
        "spotify_id": "x",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 0,
        "duration_ms": 190_000,
        "is_playing": True,
    }
    out = tracker.snapshot_payload(snap, now=1000.0)
    assert out is not None
    assert out["title"] == "Four Tet — Baby"
    assert out["progress"] == "0:00"
    assert out["duration"] == "3:10"
    assert "♪" in out["line"] or "♫" in out["line"] or "♬" in out["line"] or "♩" in out["line"]


def test_format_playing_no_color() -> None:
    line = tracker.format_line(
        {
            "name": "Baby",
            "artists": "Four Tet",
            "progress_ms": 102_000,
            "duration_ms": 190_000,
        },
        color=False,
        now=0.0,
    )
    assert line == "♪\uFE0E Four Tet — Baby · 1:42/3:10"


def test_format_line_uses_palette() -> None:
    line = tracker.format_line(
        {
            "name": "Baby",
            "artists": "Four Tet",
            "progress_ms": 102_000,
            "duration_ms": 190_000,
        },
        color=True,
        now=0.0,
        palette=("#FF0000", "#00FF00", "#0000FF"),
    )
    assert "\033[38;2;255;0;0m" in line  # artist
    assert "\033[38;2;0;255;0m" in line  # song
    assert line.count("\033[38;2;0;0;255m") >= 2  # glyph + time


def test_format_empty_without_name() -> None:
    assert tracker.format_line({}, color=False) == ""


def test_music_glyph_cycles() -> None:
    assert tracker.music_glyph(now=0.0) == "♪\uFE0E"
    assert tracker.music_glyph(now=1.0) == "♫\uFE0E"
    assert tracker.music_glyph(now=4.0) == "♪\uFE0E"


def test_display_progress_interpolates_when_playing() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "progress_ms": 0,
        "duration_ms": 10_000,
    }
    assert tracker.display_progress(snap, now=1002.0) == 2000


def test_display_progress_frozen_when_paused() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": False,
        "progress_ms": 1500,
        "duration_ms": 10_000,
    }
    assert tracker.display_progress(snap, now=1005.0) == 1500


def test_display_progress_clamps_to_duration() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "progress_ms": 9000,
        "duration_ms": 10_000,
    }
    assert tracker.display_progress(snap, now=1005.0) == 10_000


def test_needs_poll_when_missing() -> None:
    assert tracker.needs_poll(None, now=1000.0) is True


def test_needs_poll_when_age_exceeds_poll_s() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "progress_ms": 0,
        "duration_ms": 60_000,
    }
    assert tracker.needs_poll(snap, now=1000.0 + tracker.POLL_S) is True


def test_needs_poll_false_within_window() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "progress_ms": 0,
        "duration_ms": 60_000,
    }
    assert tracker.needs_poll(snap, now=1004.0) is False


def test_needs_poll_when_would_pass_duration() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "progress_ms": 9000,
        "duration_ms": 10_000,
    }
    assert tracker.needs_poll(snap, now=1002.0) is True


def test_needs_poll_false_when_paused_even_if_near_end() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": False,
        "progress_ms": 9000,
        "duration_ms": 10_000,
    }
    assert tracker.needs_poll(snap, now=1004.0) is False


def test_resolve_uses_cache_without_fetch(tmp_path: Path) -> None:
    path = tmp_path / "np.json"
    cache = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "spotify_id": "x",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 0,
        "duration_ms": 60_000,
    }
    path.write_text(json.dumps(cache))
    calls: list[int] = []

    def fetch():
        calls.append(1)
        raise AssertionError("should not fetch")

    out = tracker.resolve_snapshot(now=1003.0, fetch=fetch, cache_path=path)
    assert out is not None
    assert out["name"] == "Baby"
    assert calls == []


def test_resolve_fetches_and_saves(tmp_path: Path) -> None:
    path = tmp_path / "np.json"

    def fetch():
        return {
            "spotify_id": "id1",
            "name": "T",
            "artists": "A",
            "progress_ms": 100,
            "duration_ms": 1000,
            "is_playing": True,
        }

    out = tracker.resolve_snapshot(now=50.0, fetch=fetch, cache_path=path)
    assert out is not None
    assert out["fetched_at"] == 50.0
    assert out["name"] == "T"
    saved = json.loads(path.read_text())
    assert saved["spotify_id"] == "id1"


def test_resolve_idle_writes_negative_cache(tmp_path: Path) -> None:
    path = tmp_path / "np.json"
    path.write_text(json.dumps({"fetched_at": 0, "name": "old", "spotify_id": "x"}))
    calls: list[int] = []

    def fetch():
        calls.append(1)
        return None

    out = tracker.resolve_snapshot(now=100.0, fetch=fetch, cache_path=path)
    assert out is None
    assert calls == [1]
    saved = json.loads(path.read_text())
    assert saved["fetched_at"] == 100.0
    assert "spotify_id" not in saved

    # Within POLL_S, idle must not hit Spotify again.
    out2 = tracker.resolve_snapshot(now=104.0, fetch=fetch, cache_path=path)
    assert out2 is None
    assert calls == [1]


def test_resolve_idle_repolls_after_poll_s(tmp_path: Path) -> None:
    path = tmp_path / "np.json"
    path.write_text(json.dumps({"fetched_at": 1000.0}))
    calls: list[int] = []

    def fetch():
        calls.append(1)
        return None

    out = tracker.resolve_snapshot(
        now=1000.0 + tracker.POLL_S,
        fetch=fetch,
        cache_path=path,
    )
    assert out is None
    assert calls == [1]


def test_resolve_fetch_error_propagates(tmp_path: Path) -> None:
    path = tmp_path / "np.json"
    path.write_text(
        json.dumps(
            {
                "fetched_at": 1000.0,
                "is_playing": True,
                "spotify_id": "x",
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 0,
                "duration_ms": 60_000,
            }
        )
    )

    def fetch():
        raise RuntimeError("api down")

    try:
        tracker.resolve_snapshot(
            now=1000.0 + tracker.POLL_S + 1,
            fetch=fetch,
            cache_path=path,
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "api down" in str(exc)


def test_render_snapshot_paused_message() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": False,
        "spotify_id": "x",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 17482,
        "duration_ms": 237_117,
    }
    assert tracker.render_snapshot(snap, color=False, now=1004.0) == (
        "⏸\uFE0E spotify paused"
    )
    assert tracker.render_snapshot(None, color=False) == "⏸\uFE0E spotify paused"


def test_snapshot_payload_paused_message() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": False,
        "spotify_id": "x",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 17482,
        "duration_ms": 237_117,
    }
    out = tracker.snapshot_payload(snap, now=1004.0)
    assert out is not None
    assert out["is_playing"] is False
    assert out["line"] == "⏸\uFE0E spotify paused"
    assert out["name"] == "spotify paused"


def test_render_snapshot_interpolates() -> None:
    snap = {
        "fetched_at": 1000.0,
        "is_playing": True,
        "spotify_id": "x",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 0,
        "duration_ms": 60_000,
    }
    # now=1004 → +4s progress; int(1004)%4==0 → ♪
    line = tracker.render_snapshot(snap, color=False, now=1004.0)
    assert line == "♪\uFE0E Four Tet — Baby · 0:04/1:00"
