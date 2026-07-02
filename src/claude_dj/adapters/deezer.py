"""Deezer adapter for ISRC-based preview resolution."""

from collections.abc import Callable
from dataclasses import dataclass
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote


API_BASE_URL = "https://api.deezer.com"
RATE_LIMIT_BACKOFF_SECONDS = (5.0, 10.0, 20.0)


@dataclass(frozen=True)
class DeezerPreviewResult:
    """Normalized Deezer preview lookup result."""

    status: str
    provider_track_id: str | None
    preview_url: str | None
    failure_reason: str | None


def resolve_isrc_preview(
    isrc: str,
    *,
    urlopen=urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    rate_limit_backoff_seconds: tuple[float, ...] = RATE_LIMIT_BACKOFF_SECONDS,
) -> DeezerPreviewResult:
    """Resolve one ISRC to a Deezer 30-second preview URL."""
    request = urllib.request.Request(
        f"{API_BASE_URL}/track/isrc:{quote(isrc, safe='')}",
        method="GET",
    )
    retryable_rate_limit: DeezerPreviewResult | None = None

    for attempt in range(len(rate_limit_backoff_seconds) + 1):
        result = _resolve_request(request, urlopen=urlopen)
        if result.status != "rate_limited":
            return result
        retryable_rate_limit = result
        if attempt < len(rate_limit_backoff_seconds):
            sleep(rate_limit_backoff_seconds[attempt])

    return retryable_rate_limit or _result("rate_limited", failure_reason="rate_limited")


def _resolve_request(request: urllib.request.Request, *, urlopen) -> DeezerPreviewResult:
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return _result("rate_limited", failure_reason="http_429")
        return _result("failed", failure_reason=f"http_{exc.code}")
    except urllib.error.URLError as exc:
        return _result("failed", failure_reason=f"url_error:{exc.reason}")
    except json.JSONDecodeError:
        return _result("failed", failure_reason="invalid_json")

    if not isinstance(payload, dict):
        return _result("failed", failure_reason="invalid_response")

    error = payload.get("error")
    if isinstance(error, dict):
        return _error_result(error)

    provider_track_id = _provider_track_id(payload)
    if provider_track_id is None:
        return _result("not_found", failure_reason="missing_deezer_track_id")

    preview_url = payload.get("preview")
    if not isinstance(preview_url, str) or not preview_url:
        return _result(
            "no_preview",
            provider_track_id=provider_track_id,
            failure_reason="missing_preview_url",
        )

    return _result(
        "matched",
        provider_track_id=provider_track_id,
        preview_url=preview_url,
    )


def _error_result(error: dict[object, object]) -> DeezerPreviewResult:
    code = error.get("code")
    message = error.get("message")
    if code == 4:
        return _result("rate_limited", failure_reason="deezer_quota_limit")
    if code == 800 or message == "no data":
        return _result("not_found", failure_reason="deezer_no_data")
    return _result("failed", failure_reason=f"deezer_error:{code}")


def _provider_track_id(payload: dict[str, object]) -> str | None:
    value = payload.get("id")
    if isinstance(value, (int, str)):
        return str(value)
    return None


def _result(
    status: str,
    *,
    provider_track_id: str | None = None,
    preview_url: str | None = None,
    failure_reason: str | None = None,
) -> DeezerPreviewResult:
    return DeezerPreviewResult(
        status=status,
        provider_track_id=provider_track_id,
        preview_url=preview_url,
        failure_reason=failure_reason,
    )
