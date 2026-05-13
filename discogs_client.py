"""Discogs API Client wrapper using requests."""

import requests
import time
import logging
from config import DISCOGS_USER_AGENT

logger = logging.getLogger(__name__)


class DiscogsClient:
    def __init__(self, oauth_session):
        """
        :param oauth_session: An authenticated OAuth1Session instance.
        """
        self.session = oauth_session
        self.session.headers["User-Agent"] = DISCOGS_USER_AGENT
        self.last_request_time = 0
        self.rate_limit_delay = 0.2  # seconds

    def _make_request(self, url, params=None):
        """Internal helper to handle rate limiting and headers."""
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)

        self.last_request_time = time.time()

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limit hit. Sleeping.")
                time.sleep(e.response.json().get("retry-after", 10))
                return self._make_request(url, params)  # Retry
            logger.error(f"API Error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Request Failed: {e}")
            return None

    def search_releases(
        self, artist: str, album: str, page: int = 1, per_page: int = 100
    ):
        """Search for releases using the Discogs API."""
        params = {
            "query": f"artist:{artist} album:{album}",
            "type": "release",
            "per_page": per_page,
            "page": page,
        }

        # Discogs search endpoint
        url = "https://api.discogs.com/database/search"
        data = self._make_request(url, params=params)

        if data:
            # Normalize response to match our expected dictionary format
            results = []
            for item in data.get("hits", []):
                results.append(
                    {
                        "id": item["id"],
                        "title": item.get("title", ""),
                        "artist": item.get("artist", ""),
                        "year": item.get("year", ""),
                        "image_url": item.get("cover_image", ""),
                    }
                )
            return results
        return []

    def get_release(self, release_id: int) -> dict:
        """Fetch detailed release info by ID."""
        url = f"https://api.discogs.com/releases/{release_id}"
        data = self._make_request(url)

        if not data:
            return {}

        # Fetch master release details for tracklist if available (often more complete)
        if data.get("master_url"):
            master_data = self._make_request(data.get("master_url"))
            if master_data:
                data.update(master_data)

        # Construct our dictionary structure
        tracks = []
        tracklist = data.get("tracklist", [])
        for track in tracklist:
            tracks.append(
                {"position": track.get("position", ""), "title": track.get("title", "")}
            )

        labels = []
        for l in data.get("labels", []):
            if l.get("name"):
                labels.append(l["name"])

        return {
            "id": data.get("id", release_id),
            "title": data.get("title", ""),
            "artist": data.get("artist", ""),
            "year": data.get("year", ""),
            "label": labels[0] if labels else "",
            "genre": data.get("genres", [None])[0] if data.get("genres") else "",
            "tracks": tracks,
            "image_url": data.get(
                "cover_image",
                (
                    data.get("images", [{}])[0].get("uri", "")
                    if data.get("images")
                    else ""
                ),
            ),
        }

    def get_artwork_url(self, release_data: dict) -> str:
        """Ensure the image URL is valid."""
        url = release_data.get("image_url", "")
        # Standardize image URL to Discogs CDN
        if url:
            return url.replace("https://discogs.com/", "https://i.discogs.com/")
        return ""
