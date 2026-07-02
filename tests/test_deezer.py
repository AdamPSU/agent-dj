"""Deezer preview resolver tests."""

import json
import urllib.error

from claude_dj.adapters.deezer import resolve_isrc_preview


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_resolve_isrc_preview_fetches_deezer_track_by_isrc() -> None:
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "id": 123,
                "isrc": "US123",
                "preview": "https://cdnt-preview.dzcdn.net/preview.mp3",
            }
        )

    result = resolve_isrc_preview("US123", urlopen=fake_urlopen)

    request, timeout = requests[0]
    assert request.full_url == "https://api.deezer.com/track/isrc:US123"
    assert request.get_method() == "GET"
    assert timeout == 10
    assert result.status == "matched"
    assert result.provider_track_id == "123"
    assert result.preview_url == "https://cdnt-preview.dzcdn.net/preview.mp3"
    assert result.failure_reason is None


def test_resolve_isrc_preview_reports_no_preview() -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse({"id": 123, "isrc": "US123", "preview": ""})

    result = resolve_isrc_preview("US123", urlopen=fake_urlopen)

    assert result.status == "no_preview"
    assert result.provider_track_id == "123"
    assert result.preview_url is None
    assert result.failure_reason == "missing_preview_url"


def test_resolve_isrc_preview_reports_not_found_for_deezer_no_data_error() -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse({"error": {"type": "DataException", "message": "no data", "code": 800}})

    result = resolve_isrc_preview("US123", urlopen=fake_urlopen)

    assert result.status == "not_found"
    assert result.failure_reason == "deezer_no_data"


def test_resolve_isrc_preview_retries_deezer_quota_error() -> None:
    sleeps = []
    payloads = [
        {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}},
        {
            "id": 123,
            "isrc": "US123",
            "preview": "https://cdnt-preview.dzcdn.net/preview.mp3",
        },
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(payloads.pop(0))

    result = resolve_isrc_preview(
        "US123",
        urlopen=fake_urlopen,
        sleep=sleeps.append,
        rate_limit_backoff_seconds=(5.0, 10.0),
    )

    assert sleeps == [5.0]
    assert result.status == "matched"
    assert result.provider_track_id == "123"
    assert result.preview_url == "https://cdnt-preview.dzcdn.net/preview.mp3"


def test_resolve_isrc_preview_retries_http_429() -> None:
    sleeps = []
    responses = ["rate_limited", "matched"]

    def fake_urlopen(request, timeout):
        next_response = responses.pop(0)
        if next_response == "rate_limited":
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
        return FakeResponse(
            {
                "id": 123,
                "isrc": "US123",
                "preview": "https://cdnt-preview.dzcdn.net/preview.mp3",
            }
        )

    result = resolve_isrc_preview(
        "US123",
        urlopen=fake_urlopen,
        sleep=sleeps.append,
        rate_limit_backoff_seconds=(5.0, 10.0),
    )

    assert sleeps == [5.0]
    assert result.status == "matched"


def test_resolve_isrc_preview_reports_rate_limit_after_retry_budget_is_exhausted() -> None:
    sleeps = []

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    result = resolve_isrc_preview(
        "US123",
        urlopen=fake_urlopen,
        sleep=sleeps.append,
        rate_limit_backoff_seconds=(5.0, 10.0),
    )

    assert sleeps == [5.0, 10.0]
    assert result.status == "rate_limited"
    assert result.failure_reason == "http_429"
