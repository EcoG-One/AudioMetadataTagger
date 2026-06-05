"""MusicBrainz metadata lookup helpers.

This module provides a small production-oriented interface for resolving track
or album metadata from MusicBrainz using ``musicbrainzngs``.  The public entry
point is :func:`lookup_musicbrainz_metadata`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import re
import json
import time
import argparse
from typing import Any, Callable, Iterable, Literal, Optional, TypeVar
import musicbrainzngs


USER_AGENT = "FirstReleaseYearLookup/2.0 (contact: ecog@outlook.de)"
API_ROOT = "https://musicbrainz.org/ws/2/"

_REQUEST_DELAY = 1.2
_MAX_RETRIES = 3
RETRY_DELAY = 2.0
_RETRY_STATUS_CODES = {429, 502, 503, 504}
_DEFAULT_SEARCH_LIMIT = 15
_DATE_RECORDING_LIMIT = 8
_RELEASES_PER_RECORDING_LIMIT = 30

_EXCLUDED_SECONDARY_TYPES = {
    "compilation",
    "live",
    "remix",
    "dj-mix",
    "demo",
    "bootleg",
    "promotional",
    "promo",
    "interview",
    "audiobook",
    "audio drama",
    "spokenword",
    "field recording",
    "unofficial",
}

_NOISE_TOKENS = {
    "live",
    "acoustic",
    "demo",
    "remix",
    "radio edit",
    "extended mix",
    "instrumental",
    "karaoke",
    "remastered",
    "anniversary edition",
    "deluxe edition",
    "bonus track",
    "bonus",
    "edit",
    "single version",
    "album version",
    "mono",
    "stereo",
}

_TRACK_INCLUDES = ["releases", "artist-credits", "isrcs", "tags"]
_RELEASE_INCLUDES = ["recordings", "artist-credits", "release-groups", "media", "labels"]

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class MusicBrainzMatch:
    """A normalized MusicBrainz candidate with a quality score."""

    item: dict[str, Any]
    score: float


def configure_musicbrainz() -> None:
    """Configure the MusicBrainz client user agent and API host."""

    musicbrainzngs.set_useragent(
        "FirstReleaseYearLookup",
        "2.0",
        contact="ecog@outlook.de",
    )
    musicbrainzngs.set_hostname("musicbrainz.org", use_https=True)


def normalize_title(value: str) -> str:
    """Return a comparison-safe title string.

    The normalizer removes bracketed version suffixes, common non-original
    version markers, punctuation, repeated whitespace, and capitalization
    differences.  It is intentionally conservative: tokens are only removed
    when they appear as standalone phrases.
    """

    text = value.casefold()
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)
    text = re.sub(r"\s+-\s+.*$", " ", text)
    text = re.sub(r"[/:|]", " ", text)

    for token in sorted(_NOISE_TOKENS, key=len, reverse=True):
        pattern = rf"\b{re.escape(token)}\b"
        text = re.sub(pattern, " ", text)

    text = re.sub(r"['`´’]", "", text)
    text = re.sub(r"[^a-z0-9&]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_artist(value: str) -> str:
    """Normalize artist credits for robust equality checks."""

    text = value.casefold()
    text = re.sub(r"\b(the)\b", " ", text)
    text = re.sub(r"['`´’]", "", text)
    text = re.sub(r"[^a-z0-9&]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_match(expected: str, candidate: str) -> bool:
    """Return whether two titles match after cleanup."""

    left = normalize_title(expected)
    right = normalize_title(candidate)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def artist_credit_name(entity: dict[str, Any]) -> str:
    """Extract a display artist from a MusicBrainz entity."""

    credit = entity.get("artist-credit") or []
    parts: list[str] = []
    for item in credit:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            artist = item.get("artist") or {}
            parts.append(artist.get("name") or item.get("name") or "")
    return "".join(parts).strip()


def artists_match(expected: str, entity: dict[str, Any]) -> bool:
    """Return whether an entity's artist credit matches the requested artist."""

    candidate = artist_credit_name(entity)
    left = normalize_artist(expected)
    right = normalize_artist(candidate)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def valid_musicbrainz_date(value: Optional[str]) -> Optional[date]:
    """Parse a MusicBrainz partial date into a sortable ``date``.

    MusicBrainz may return ``YYYY``, ``YYYY-MM``, or ``YYYY-MM-DD``. Missing
    month or day parts are normalized to ``1`` so the value can be sorted while
    preserving the original string in returned metadata.
    """

    if not value:
        return None

    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        return date(year, month, day)
    except (TypeError, ValueError):
        logger.debug("Ignoring invalid MusicBrainz date: %s", value)
        return None


def release_secondary_types(release: dict[str, Any]) -> set[str]:
    """Return normalized secondary release types from a release entity."""

    release_group = release.get("release-group") or {}
    raw_types = (
        release.get("secondary-type-list")
        or release.get("secondary-types")
        or release_group.get("secondary-type-list")
        or release_group.get("secondary-types")
        or []
    )
    return {str(item).casefold() for item in raw_types}


def is_canonical_release(release: dict[str, Any]) -> bool:
    """Return whether a release is suitable for original-date resolution."""

    secondary_types = release_secondary_types(release)
    if secondary_types & _EXCLUDED_SECONDARY_TYPES:
        return False

    status = str(release.get("status", "")).casefold()
    if status and status not in {"official"}:
        return False

    title = normalize_title(str(release.get("title", "")))
    return not any(token in title.split() for token in {"live", "demo", "remix"})


def canonical_release_score(release: dict[str, Any]) -> int:
    """Score how strongly a release resembles an original studio release."""

    release_group = release.get("release-group") or {}
    primary_type = str(
        release.get("primary-type") or release_group.get("primary-type") or ""
    ).casefold()
    status = str(release.get("status", "")).casefold()
    score = 0
    if status == "official":
        score += 4
    if primary_type == "album":
        score += 3
    elif primary_type in {"single", "ep"}:
        score += 2
    if not release_secondary_types(release):
        score += 1
    return score


def _extract_http_status(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from musicbrainzngs errors."""

    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value

    cause = getattr(exc, "cause", None) or getattr(exc, "__cause__", None)
    for attr in ("status_code", "code"):
        value = getattr(cause, attr, None)
        if isinstance(value, int):
            return value

    match = re.search(r"\b(429|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def _date_string_from_release(release: dict[str, Any]) -> Optional[str]:
    return release.get("date") or release.get("first-release-date")


class MusicBrainzClient:
    """Thin, rate-limited, retrying client around ``musicbrainzngs``."""

    def __init__(
        self,
        request_delay: float = _REQUEST_DELAY,
        max_retries: int = _MAX_RETRIES,
        retry_delay: float = RETRY_DELAY,
    ) -> None:
        configure_musicbrainz()
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run one MusicBrainz request with delay and retry handling."""

        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            time.sleep(self.request_delay)
            try:
                return fn(*args, **kwargs)
            except musicbrainzngs.WebServiceError as exc:
                last_error = exc
                status = _extract_http_status(exc)
                should_retry = status in _RETRY_STATUS_CODES and attempt < self.max_retries
                if should_retry:
                    logger.warning(
                        "MusicBrainz request failed with HTTP %s; retrying %s/%s in %.1fs",
                        status,
                        attempt,
                        self.max_retries,
                        self.retry_delay,
                    )
                    time.sleep(self.retry_delay)
                    continue
                logger.exception("MusicBrainz request failed permanently: %s", exc)
                raise

        if last_error:
            raise last_error
        raise RuntimeError("MusicBrainz request failed without an exception")

    def search_recordings(
        self,
        artist: str,
        title: str,
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """Search recordings for an artist/title pair."""

        query = f'artist:"{artist}" AND recording:"{title}"'
        response = self._call(
            musicbrainzngs.search_recordings,
            query=query,
            limit=limit,
        )
        return response.get("recording-list", [])

    def browse_recording_releases(
        self,
        recording_id: str,
        limit: int = _RELEASES_PER_RECORDING_LIMIT,
    ) -> list[dict[str, Any]]:
        """Fetch releases that include a recording."""

        response = self._call(
            musicbrainzngs.browse_releases,
            recording=recording_id,
            includes=["release-groups", "media", "artist-credits"],
            limit=limit,
        )
        return response.get("release-list", [])

    def search_releases(
        self,
        artist: str,
        title: str,
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """Search releases for an artist/title pair."""

        query = f'artist:"{artist}" AND release:"{title}"'
        response = self._call(
            musicbrainzngs.search_releases,
            query=query,
            limit=limit,
        )
        return response.get("release-list", [])

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        """Fetch a recording with useful metadata includes."""

        response = self._call(
            musicbrainzngs.get_recording_by_id,
            recording_id,
            includes=_TRACK_INCLUDES,
        )
        return response.get("recording", {})

    def get_release(self, release_id: str) -> dict[str, Any]:
        """Fetch a release with track, artist, release-group, and label metadata."""

        response = self._call(
            musicbrainzngs.get_release_by_id,
            release_id,
            includes=_RELEASE_INCLUDES,
        )
        return response.get("release", {})


def _recording_match_score(artist: str, title: str, recording: dict[str, Any]) -> float:
    score = 0.0
    if titles_match(title, str(recording.get("title", ""))):
        score += 70
    if artists_match(artist, recording):
        score += 25
    score += min(float(recording.get("ext:score", 0) or 0), 100.0) / 20
    return score


def _release_match_score(artist: str, title: str, release: dict[str, Any]) -> float:
    score = 0.0
    if titles_match(title, str(release.get("title", ""))):
        score += 70
    if artists_match(artist, release):
        score += 20
    score += canonical_release_score(release) * 2
    score += min(float(release.get("ext:score", 0) or 0), 100.0) / 20
    return score


def _best_match(
    candidates: Iterable[dict[str, Any]],
    scorer: Callable[[dict[str, Any]], float],
    minimum_score: float,
) -> Optional[dict[str, Any]]:
    matches = [MusicBrainzMatch(item=item, score=scorer(item)) for item in candidates]
    matches.sort(key=lambda match: match.score, reverse=True)
    if not matches or matches[0].score < minimum_score:
        return None
    return matches[0].item


def determine_earliest_valid_release_date(
    artist: str,
    title: str,
    client: Optional[MusicBrainzClient] = None,
) -> Optional[str]:
    """Resolve the earliest valid original release date for a song.

    The function searches all relevant MusicBrainz recordings for the requested
    artist and title, gathers ``first-release-date`` values from matched
    recordings, browses each recording's releases, filters out non-canonical
    secondary types, and returns the earliest date found.  When multiple
    releases share dates, canonical studio releases are preferred by status and
    primary type scoring.
    """

    mb_client = client or MusicBrainzClient()
    recordings = mb_client.search_recordings(artist, title, limit=_DEFAULT_SEARCH_LIMIT)
    matched = [
        recording
        for recording in sorted(
            recordings,
            key=lambda item: _recording_match_score(artist, title, item),
            reverse=True,
        )
        if titles_match(title, str(recording.get("title", ""))) and artists_match(artist, recording)
    ][:_DATE_RECORDING_LIMIT]

    canonical_dated_candidates: list[tuple[date, int, str]] = []
    recording_dated_candidates: list[tuple[date, int, str]] = []
    for recording in matched:
        first_release_date = recording.get("first-release-date")
        parsed = valid_musicbrainz_date(first_release_date)
        if parsed:
            recording_dated_candidates.append((parsed, 0, first_release_date))

        recording_id = recording.get("id")
        if not recording_id:
            continue

        try:
            releases = mb_client.browse_recording_releases(
                recording_id,
                limit=_RELEASES_PER_RECORDING_LIMIT,
            )
        except musicbrainzngs.WebServiceError:
            continue

        for release in releases:
            if not is_canonical_release(release):
                continue

            release_date = _date_string_from_release(release)
            parsed_release_date = valid_musicbrainz_date(release_date)
            if parsed_release_date:
                canonical_dated_candidates.append(
                    (
                        parsed_release_date,
                        -canonical_release_score(release),
                        release_date,
                    )
                )

    dated_candidates = canonical_dated_candidates or recording_dated_candidates
    if not dated_candidates:
        return None

    dated_candidates.sort(key=lambda item: (item[0], item[1]))
    return dated_candidates[0][2]


def extract_track_metadata(
    recording: dict[str, Any],
    artist: str,
    title: str,
    first_release_date: Optional[str],
) -> dict[str, Any]:
    """Convert a MusicBrainz recording into a JSON-safe metadata dictionary."""

    releases = recording.get("release-list") or []
    canonical_releases = [release for release in releases if is_canonical_release(release)]
    release_dates = sorted(
        {
            release_date
            for release in canonical_releases
            if (release_date := _date_string_from_release(release))
        }
    )
    isrcs = recording.get("isrc-list") or []

    return {
        "type": "track",
        "id": recording.get("id"),
        "title": recording.get("title") or title,
        "artist": artist_credit_name(recording) or artist,
        "length_ms": recording.get("length"),
        "first_release_date": first_release_date,
        "release_dates": release_dates,
        "isrcs": isrcs,
        "musicbrainz_url": f"https://musicbrainz.org/recording/{recording.get('id')}"
        if recording.get("id")
        else None,
    }


def lookup_track_metadata(
    artist: str,
    title: str,
    client: Optional[MusicBrainzClient] = None,
) -> dict[str, Any]:
    """Look up one track and return structured recording metadata."""

    mb_client = client or MusicBrainzClient()
    recordings = mb_client.search_recordings(artist, title)
    best = _best_match(
        recordings,
        lambda recording: _recording_match_score(artist, title, recording),
        minimum_score=80,
    )
    if not best:
        return {
            "type": "track",
            "artist": artist,
            "title": title,
            "found": False,
            "error": "No matching MusicBrainz recording found.",
        }

    recording_id = best.get("id")
    full_recording = mb_client.get_recording(recording_id) if recording_id else best
    first_release_date = determine_earliest_valid_release_date(artist, title, mb_client)
    metadata = extract_track_metadata(full_recording or best, artist, title, first_release_date)
    metadata["found"] = True
    return metadata


def extract_album_tracks(release: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all tracks from a MusicBrainz release."""

    tracks: list[dict[str, Any]] = []
    for medium in release.get("medium-list") or []:
        medium_position = medium.get("position")
        medium_format = medium.get("format")
        for track in medium.get("track-list") or []:
            recording = track.get("recording") or {}
            tracks.append(
                {
                    "position": track.get("position"),
                    "number": track.get("number"),
                    "medium_position": medium_position,
                    "medium_format": medium_format,
                    "id": recording.get("id"),
                    "title": recording.get("title") or track.get("title"),
                    "artist": artist_credit_name(recording) or artist_credit_name(track),
                    "length_ms": recording.get("length") or track.get("length"),
                    "first_release_date": recording.get("first-release-date"),
                    "musicbrainz_url": (
                        f"https://musicbrainz.org/recording/{recording.get('id')}"
                        if recording.get("id")
                        else None
                    ),
                }
            )
    return tracks


def extract_album_metadata(release: dict[str, Any], artist: str, title: str) -> dict[str, Any]:
    """Convert a MusicBrainz release into a JSON-safe album metadata dictionary."""

    release_group = release.get("release-group") or {}
    labels = [
        label_info.get("label", {}).get("name")
        for label_info in release.get("label-info-list") or []
        if label_info.get("label", {}).get("name")
    ]
    return {
        "type": "album",
        "found": True,
        "album": {
            "id": release.get("id"),
            "title": release.get("title") or title,
            "artist": artist_credit_name(release) or artist,
            "date": release.get("date"),
            "country": release.get("country"),
            "status": release.get("status"),
            "barcode": release.get("barcode"),
            "asin": release.get("asin"),
            "primary_type": release_group.get("primary-type"),
            "secondary_types": sorted(release_secondary_types(release)),
            "labels": labels,
            "musicbrainz_url": f"https://musicbrainz.org/release/{release.get('id')}"
            if release.get("id")
            else None,
        },
        "tracks": extract_album_tracks(release),
    }


def lookup_album_metadata(
    artist: str,
    title: str,
    client: Optional[MusicBrainzClient] = None,
) -> dict[str, Any]:
    """Look up one album and return release metadata plus every track."""

    mb_client = client or MusicBrainzClient()
    releases = mb_client.search_releases(artist, title)
    canonical = [release for release in releases if is_canonical_release(release)]
    best = _best_match(
        canonical or releases,
        lambda release: _release_match_score(artist, title, release),
        minimum_score=78,
    )
    if not best:
        return {
            "type": "album",
            "artist": artist,
            "title": title,
            "found": False,
            "error": "No matching MusicBrainz release found.",
        }

    release_id = best.get("id")
    full_release = mb_client.get_release(release_id) if release_id else best
    return extract_album_metadata(full_release or best, artist, title)


def lookup_musicbrainz_metadata(
    artist: str,
    title: str,
    type: Literal["track", "album"],
) -> dict[str, Any]:
    """Look up track or album metadata from MusicBrainz.

    Args:
        artist: Artist name to search for.
        title: Track or album title to search for.
        type: Either ``"track"`` or ``"album"``.

    Returns:
        A JSON-serializable dictionary. Track lookups return recording metadata;
        album lookups return album metadata and a ``tracks`` list.

    Raises:
        ValueError: If ``type`` is not ``"track"`` or ``"album"``.
        musicbrainzngs.WebServiceError: If the API fails after retries.
    """

    if not artist.strip():
        raise ValueError("artist must not be empty")
    if not title.strip():
        raise ValueError("title must not be empty")

    mb_client = MusicBrainzClient()
    if type == "track":
        return lookup_track_metadata(artist.strip(), title.strip(), mb_client)
    if type == "album":
        return lookup_album_metadata(artist.strip(), title.strip(), mb_client)
    raise ValueError('type must be either "track" or "album"')


def example_usage() -> None:
    """Demonstrate track and album lookups without running automatically."""

    track = lookup_musicbrainz_metadata(
        artist="Kate Bush",
        title="Running Up That Hill",
        type="track",
    )
    print(json.dumps(track, indent=2))

    album = lookup_musicbrainz_metadata(
        artist="Radiohead",
        title="OK Computer",
        type="album",
    )
    print(json.dumps(album, indent=2))


def _main() -> None:
    """Run a single explicit lookup from the command line."""

    parser = argparse.ArgumentParser(description="Look up MusicBrainz metadata.")
    parser.add_argument("--artist", required=True, help="Artist name to search for.")
    parser.add_argument("--title", required=True, help="Track or album title to search for.")
    parser.add_argument(
        "--type",
        required=True,
        choices=("track", "album"),
        help="Lookup type.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)

    metadata = lookup_musicbrainz_metadata(
        artist=args.artist,
        title=args.title,
        type=args.type,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    _main()
