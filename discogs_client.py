import discogs_client
import time
import logging
from config import API_RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)


class DiscogsClient:
    def __init__(self, library_client: discogs_client.Client):
        """
        Wrapper for the discogs_client library instance.
        """
        self.client = library_client
        self.last_request_time = 0

    def _rate_limit(self):
        """Simple rate limiting for the Discogs API."""
        elapsed = time.time() - self.last_request_time
        if elapsed < API_RATE_LIMIT_DELAY:
            time.sleep(API_RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()

    def search_releases(
        self, artist: str, album: str, page: int = 1, per_page: int = 100
    ):
        """
        Search for releases.
        Note: discogs-client v3 search() does not support page/per_page directly
        in the standard call like the old API did, but returns the first page of results.
        """
        self._rate_limit()
        try:
            # Returns a list of discogs_client.model.Release objects
            results = self.client.search(artist=artist, release=album, type="release")

            # Convert to dictionary for UI compatibility
            search_results = []
            for r in results:
                search_results.append(
                    {
                        "id": r.id,
                        "title": r.title,
                        "artist": r.artist,
                        "year": r.year if hasattr(r, "year") else None,
                        "image_url": r.image_url if hasattr(r, "image_url") else "",
                    }
                )
            return search_results

        except discogs_client.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                logger.error("Rate limit exceeded or forbidden.")
            else:
                logger.warning(f"Discogs search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Discogs search unexpected error: {e}")
            return []

    def get_release(self, release_id: int) -> dict:
        """Fetch detailed release information by ID."""
        self._rate_limit()
        try:
            release = self.client.release.get(release_id)

            tracks = []
            if hasattr(release, "tracklist"):
                for t in release.tracklist:
                    tracks.append(
                        {
                            "position": t.position if hasattr(t, "position") else "",
                            "title": t.title,
                        }
                    )

            labels = []
            if hasattr(release, "labels"):
                for l in release.labels:
                    if hasattr(l, "name"):
                        labels.append(l.name)

            return {
                "id": release.id,
                "title": release.title,
                "artist": release.artist,
                "year": release.year if hasattr(release, "year") else "",
                "label": labels[0] if labels else "",
                "genre": (
                    release.genres[0]
                    if hasattr(release, "genres") and release.genres
                    else ""
                ),
                "tracks": tracks,
                "image_url": release.image_url if hasattr(release, "image_url") else "",
            }
        except Exception as e:
            logger.error(f"Failed to fetch release {release_id}: {e}")
            return {}

    def get_artwork_url(self, release_data: dict) -> str:
        """Get highest quality image URL."""
        img = release_data.get("image_url", "")
        if not img:
            return ""
        # Discogs API image URLs often need to be converted to the image hosting format
        return img.replace("https://discogs.com/", "https://i.discogs.com/")
