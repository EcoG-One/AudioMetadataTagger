"""Discogs API Client wrapper with rate limiting & pagination."""

import time
import discogs_client
import requests
import logging
from config import (
    DISCOGS_USER_AGENT,
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_REQUEST_TOKEN_URL,
    API_RATE_LIMIT_DELAY,
)

logger = logging.getLogger(__name__)


class DiscogsClient:
    def __init__(self, session: discogs_client.Session):
        self.session = session
        self.session.fetcher.timeout = 10
        self.last_request_time = 0

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < API_RATE_LIMIT_DELAY:
            time.sleep(API_RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()

    def search_releases(
        self, artist: str, album: str, page: int = 1, per_page: int = 50
    ):
        """Search Discogs for releases. Returns list of release dicts."""
        self._rate_limit()
        try:
            results = self.session.search(
                artist=artist,
                release=album,
                type="release",
                page=page,
                per_page=per_page,
            )
            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "artist": r.artist,
                    "year": r.year,
                    "image_url": r.image_url,
                }
                for r in results.data
            ]
        except discogs_client.HTTPError as e:
            logger.warning(f"Discogs search error (page {page}): {e}")
            return []
        except Exception as e:
            logger.error(f"Discogs search unexpected error: {e}")
            return []

    def get_release(self, release_id: int) -> dict:
        """Fetch full release details including tracks."""
        self._rate_limit()
        try:
            release = self.session.release.get(release_id)
            tracks = [
                {"position": t.position, "title": t.title} for t in release.tracklist
            ]
            return {
                "id": release.id,
                "title": release.title,
                "artist": release.artist,
                "year": release.year,
                "label": release.labels[0].name if release.labels else "",
                "genre": release.genres[0] if release.genres else "",
                "tracks": tracks,
                "image_url": release.image_url,
            }
        except Exception as e:
            logger.error(f"Failed to fetch release {release_id}: {e}")
            return {}

    def get_artwork_url(self, release_data: dict) -> str:
        """Get highest quality image URL."""
        img = release_data.get("image_url") or release_data.get("cover_image_url")
        if not img:
            # Fallback to master release if needed
            return ""
        return img.replace("https://discogs.com/", "https://i.discogs.com/")
