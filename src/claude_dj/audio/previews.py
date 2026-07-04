"""Preview URL resolution for Claude DJ."""

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3
import time

from claude_dj.adapters.deezer import DeezerPreviewResult, resolve_isrc_preview
from claude_dj.storage.db import (
    CatalogStatus,
    fetch_tracks_needing_preview_resolution,
    get_catalog_status,
    upsert_preview_match,
)


# Community-observed Deezer API limit: 50 requests per 5 seconds per IP.
DEEZER_RATE_LIMIT_REQUESTS = 50
DEEZER_RATE_LIMIT_WINDOW_SECONDS = 5
DEEZER_REQUESTS_PER_SECOND = DEEZER_RATE_LIMIT_REQUESTS // DEEZER_RATE_LIMIT_WINDOW_SECONDS
PreviewStatusCounts = dict[str, int]


@dataclass(frozen=True)
class PreviewResolutionSummary:
    """Summary of a Deezer preview-resolution pass."""

    catalog_status: CatalogStatus
    matched_count: int = 0
    no_preview_count: int = 0
    not_found_count: int = 0
    no_isrc_count: int = 0
    rate_limited_count: int = 0
    failed_count: int = 0

    @property
    def resolved_count(self) -> int:
        """Return preview rows written during this pass."""
        return (
            self.matched_count
            + self.no_preview_count
            + self.not_found_count
            + self.no_isrc_count
        )

    def to_json(self) -> dict[str, int | bool | str]:
        """Serialize the resolution summary for daemon responses."""
        payload: dict[str, int | bool | str] = {
            "ran": self.resolved_count > 0 or self.rate_limited_count > 0,
            "provider": "deezer",
            "resolved_count": self.resolved_count,
            "matched_count": self.matched_count,
            "no_preview_count": self.no_preview_count,
            "not_found_count": self.not_found_count,
            "no_isrc_count": self.no_isrc_count,
            "rate_limited_count": self.rate_limited_count,
            "failed_count": self.failed_count,
        }
        if self.rate_limited_count:
            payload["error_code"] = "deezer_rate_limited"
        return payload


def resolve_deezer_previews(
    db: sqlite3.Connection,
    *,
    resolver: Callable[[str], DeezerPreviewResult] = resolve_isrc_preview,
    sleep: Callable[[float], None] = time.sleep,
    requests_per_second: int = DEEZER_REQUESTS_PER_SECOND,
) -> PreviewResolutionSummary:
    """Resolve missing track previews through Deezer using ISRCs only."""
    counts: PreviewStatusCounts = {
        "matched": 0,
        "no_preview": 0,
        "not_found": 0,
        "no_isrc": 0,
        "rate_limited": 0,
        "failed": 0,
    }

    delay = 1 / requests_per_second if requests_per_second > 0 else 0
    candidates = fetch_tracks_needing_preview_resolution(db)
    for candidate in candidates:
        if candidate.isrc is None:
            _store_and_count_result(
                db,
                track_id=candidate.track_id,
                result=_missing_isrc_result(),
                counts=counts,
            )
            continue

        result = resolver(candidate.isrc)
        if result.status == "rate_limited":
            counts["rate_limited"] += 1
            break

        _store_and_count_result(db, track_id=candidate.track_id, result=result, counts=counts)

        if delay:
            sleep(delay)

    db.commit()
    return _summary_from_counts(catalog_status=get_catalog_status(db), counts=counts)


def _missing_isrc_result() -> DeezerPreviewResult:
    return DeezerPreviewResult(
        status="no_isrc",
        provider_track_id=None,
        preview_url=None,
        failure_reason="missing_isrc",
    )


def _store_and_count_result(
    db: sqlite3.Connection,
    *,
    track_id: int,
    result: DeezerPreviewResult,
    counts: PreviewStatusCounts,
) -> None:
    _increment_count(counts, result.status)
    if result.status != "failed":
        _store_result(db, track_id=track_id, result=result)


def _increment_count(counts: PreviewStatusCounts, status: str) -> None:
    if status in counts:
        counts[status] += 1
    else:
        counts["failed"] += 1


def _summary_from_counts(
    *,
    catalog_status: CatalogStatus,
    counts: PreviewStatusCounts,
) -> PreviewResolutionSummary:
    return PreviewResolutionSummary(
        catalog_status=catalog_status,
        matched_count=counts["matched"],
        no_preview_count=counts["no_preview"],
        not_found_count=counts["not_found"],
        no_isrc_count=counts["no_isrc"],
        rate_limited_count=counts["rate_limited"],
        failed_count=counts["failed"],
    )


def _store_result(
    db: sqlite3.Connection,
    *,
    track_id: int,
    result: DeezerPreviewResult,
) -> None:
    upsert_preview_match(
        db,
        track_id=track_id,
        provider="deezer",
        provider_track_id=result.provider_track_id,
        preview_url=result.preview_url,
        match_method="isrc",
        status=result.status,
        failure_reason=result.failure_reason,
    )
