"""Discogs API Client wrapper using requests."""

import requests
import time
import logging
from config import DISCOGS_USER_AGENT

logger = logging.getLogger(__name__)


class DiscogsClient:
    def __init__(self, oauth_session):
        """
        :param oauth_session: An authenticated OAuth1Session instance from auth.py
        """
        self.session = oauth_session
        # Discogs requires a User-Agent header for all requests
        self.session.headers["User-Agent"] = DISCOGS_USER_AGENT
        self.last_request_time = 0
        self.rate_limit_delay = 0.2

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
            error_text = "Unknown Error"
            try:
                error_text = e.response.text
            except:
                pass

            status_code = e.response.status_code

            if status_code == 401:
                logger.error(
                    f"Discogs Error 401: Unauthorized. Check your API keys/tokens. Details: {error_text}"
                )
            elif status_code == 403:
                logger.error(
                    f"Discogs Error 403: Forbidden/Rate Limited. Details: {error_text}"
                )
                time.sleep(60)  # Sleep to avoid hammering the rate limit
                return self._make_request(url, params)  # Retry
            elif status_code == 400:
                logger.error(f"Discogs Error 400: Bad Request. Details: {error_text}")
            else:
                logger.error(f"Discogs Error {status_code}: {error_text}")

            return None
        except Exception as e:
            logger.error(f"Network/General Error: {e}")
            return None

    def search_releases(
        self, artist: str, album: str, page: int = 1, per_page: int = 50
    ):
        """
        Search for releases using the Discogs API.
        IMPORTANT: Parameter must be 'q', not 'query'.
        """
        # Discogs API v1 Search Endpoint
        # Docs: https://www.discogs.com/developers/#page:database,header:database-search
        query_string = f"{artist} {album}"

        params = {
            "q": query_string,  # Fixed: Discogs expects 'q', not 'query'
            "type": "release",
            "per_page": min(per_page, 50),  # Discogs API max is 50
            "page": page,
        }

        url = "https://api.discogs.com/database/search"

        logger.info(f"Searching Discogs: {query_string}")
        data = self._make_request(url, params=params)

        if not data:
            return []

        # Parse response
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

    def get_release(self, release_id: int) -> dict:
        """Fetch detailed release info by ID."""
        url = f"https://api.discogs.com/releases/{release_id}"
        data = self._make_request(url)

        if not data:
            return {}

        # Fetch Master Release details if available
        if data.get("master_url"):
            master_data = self._make_request(data.get("master_url"))
            if master_data:
                # Use master data to fill in missing details
                data.update(master_data)

        # Process Tracks
        tracks = []
        for track in data.get("tracklist", []):
            tracks.append(
                {"position": track.get("position", ""), "title": track.get("title", "")}
            )

        # Process Labels
        labels = [l["name"] for l in data.get("labels", []) if l.get("name")]

        # Process Images
        img = data.get("cover_image", "")
        if not img and data.get("images"):
            img = data["images"][0].get("uri", "")

        return {
            "id": data.get("id", release_id),
            "title": data.get("title", ""),
            "artist": data.get("artist", ""),
            "year": data.get("year", ""),
            "label": labels[0] if labels else "",
            "genre": data.get("genres", [None])[0] if data.get("genres") else "",
            "tracks": tracks,
            "image_url": img,
        }
