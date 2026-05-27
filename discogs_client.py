"""Discogs API Client wrapper using requests."""

import requests
import time
import logging
from config import DISCOGS_USER_AGENT
import settings

logger = logging.getLogger(__name__)


class DiscogsClient:
    def __init__(self, oauth_session):
        self.session = oauth_session
        self.session.headers["User-Agent"] = DISCOGS_USER_AGENT
        self.last_request_time = 0
        self.rate_limit_delay = settings.SETTINGS.get('api_rate_limit_delay', 0.2)

    def _make_request(self, url, params=None):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            if url.endswith(".jpeg") or url.endswith(".jpg") or url.endswith(".png"):
                image = response.text
                with open(image, "wb") as fh:
                    fh.write(response.content)
            else:
                return response.json()
        except requests.exceptions.HTTPError as e:
            # Return None instead of crashing if 404 or other errors
            return None
        except Exception as e:
            logger.error(f"Request Failed: {e}")
            return None

    def search_releases(
        self, artist: str, album: str, page: int = 1, per_page: int = 50
    ):
        query_string = f"{artist} {album}"
        params = {
            "q": query_string,
            "type": "release",
            "per_page": min(settings.SETTINGS.get('default_page_size', 50), 50),
            "page": page,
        }
        url = "https://api.discogs.com/database/search"
        data = self._make_request(url, params=params)

        if not data:
            return []

        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "id": item["id"],
                    "album": item.get("title", ""),
                    "album_artist": item.get("artist", ""),
                    "year": item.get("year", ""),
                    "image_url": item.get("cover_image", ""),
                    "master_id": item.get(
                        "master_id"
                    ),  # Added: Store Master ID if available
                    "resource_url": item.get("resource_url"),
                }
            )
        return results

    def get_release(self, release_id: int) -> dict:
        """Fetch specific Release info."""
        url = f"https://api.discogs.com/releases/{release_id}"
        data = self._make_request(url)
        return self._format_release_data(data)

    def get_album_artwork(self, url: str) -> bytes:
        """Fetch album artwork for a specific release."""
        response = self.session.get(url)
        response.raise_for_status()
        return response.content

    def get_master(self, master_id: int) -> dict:
        """Fetch Master Release info (Fallback for 404 releases)."""
        url = f"https://api.discogs.com/masters/{master_id}"
        data = self._make_request(url)
        if not data:
            return {}

        # Construct a dictionary similar to get_release for UI consistency
        tracks = []
        for t in data.get("tracks", []):
            tracks.append({"position": t.get("position"), "title": t.get("title")})

        return {
            "id": data.get("id"),
            "album": data.get("title"),
            "album_artist": data.get("artist"),
            "year": data.get("master_year"),
            "tracks": tracks,
            "image_url": data.get("cover_image")
            or (data.get("images", [{}])[0].get("uri") if data.get("images") else ""),
        }

    def _format_release_data(self, data):
        """Helper to convert API data to internal dict format."""
        if not data:
            return {}

        tracks = []
        for t in data.get("tracklist", []):
            tracks.append({"position": t.get("position"), "artists": [a["name"] for a in t.get("artists", [])], "title": t.get("title"), "duration": t.get("duration")})

        labels = [l["name"] for l in data.get("labels", []) if l.get("name")]
        img = data.get("cover_image", "")
        if not img and data.get("images"):
            img = data["images"][0].get("uri", "")

        return {
            "id": data.get("id"),
            "album": data.get("title"),
            "album_artist": data["artists"][0]["name"] or data.get("artist"),
            "year": data.get("year"),
            "format": data.get("formats", [{}])[0].get("name", ""),
            "label": labels[0] if labels else "",
            "country": data.get("country", ""),
            "genre": data.get("genres", [None])[0] if data.get("genres") else "",
            "tracks": tracks,
            "comment": data.get("notes", ""),
            "image_url": img,
        }
