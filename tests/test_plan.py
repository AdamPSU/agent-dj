from claude_dj.playback import PlayerState
from claude_dj.session import Plan


def _track(i: int) -> dict:
    return {"spotify_id": f"sp:{i}", "track_id": i, "name": f"T{i}"}


def test_plan_replace_and_remaining() -> None:
    plan = Plan()
    plan.replace([_track(0), _track(1), _track(2)])
    assert plan.expected_id == "sp:0"
    assert plan.index == 0
    assert [t["spotify_id"] for t in plan.remaining()] == ["sp:0", "sp:1", "sp:2"]


def test_plan_observe_same() -> None:
    plan = Plan()
    plan.replace([_track(0), _track(1)])
    state = PlayerState(
        is_playing=True,
        progress_ms=10_000,
        duration_ms=180_000,
        track_id="sp:0",
    )
    assert plan.observe(state).kind == "same"


def test_plan_observe_same_on_last_track() -> None:
    """Last track is still `same` — refill is Session's job, not observe."""
    plan = Plan()
    plan.replace([_track(0), _track(1)])
    plan.move_to("sp:1")
    last = PlayerState(
        is_playing=True,
        progress_ms=176_000,
        duration_ms=180_000,
        track_id="sp:1",
    )
    assert plan.observe(last).kind == "same"


def test_plan_observe_pause_never_mints() -> None:
    plan = Plan()
    plan.replace([_track(0), _track(1)])
    plan.move_to("sp:1")
    stopped = PlayerState(
        is_playing=False,
        progress_ms=30_000,
        duration_ms=180_000,
        track_id="sp:1",
    )
    assert plan.observe(stopped).kind == "paused"

    plan.replace([_track(0)])
    empty = PlayerState(
        is_playing=False,
        progress_ms=0,
        duration_ms=None,
        track_id=None,
    )
    assert plan.observe(empty).kind == "paused"
    assert plan.observe(None).kind == "device_gone"


def test_plan_observe_advanced_and_foreign() -> None:
    plan = Plan()
    plan.replace([_track(0), _track(1), _track(2)])
    adv = plan.observe(
        PlayerState(is_playing=True, progress_ms=0, duration_ms=1000, track_id="sp:2")
    )
    assert adv.kind == "advanced"
    assert adv.track_id == "sp:2"

    foreign = plan.observe(
        PlayerState(is_playing=True, progress_ms=0, duration_ms=1000, track_id="other")
    )
    assert foreign.kind == "foreign"


def test_plan_append_keeps_cursor() -> None:
    plan = Plan()
    plan.replace([_track(0), _track(1)])
    plan.move_to("sp:1")
    plan.append([_track(2), _track(3)])
    assert plan.expected_id == "sp:1"
    assert plan.index == 1
    assert [t["spotify_id"] for t in plan.remaining()] == ["sp:1", "sp:2", "sp:3"]
