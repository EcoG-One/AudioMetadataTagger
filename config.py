"""Configuration constants for MetadataTagger."""
import os

# Discogs API credentials
DISCOGS_CONSUMER_KEY = os.environ.get("Consumer_Key")
DISCOGS_CONSUMER_SECRET = os.environ.get("Consumer_Secret")
DISCOGS_USER_AGENT = os.environ.get("User-Agent")
DISCOGS_API_BASE = "https://api.discogs.com"

# API Endpoints
DISCOGS_REQUEST_TOKEN_URL = "https://api.discogs.com/oauth/request_token"
DISCOGS_AUTHORIZE_URL = "https://www.discogs.com/oauth/authorize"
DISCOGS_ACCESS_TOKEN_URL = "https://api.discogs.com/oauth/access_token"

# Audio Formats & Extensions
SUPPORTED_FORMATS = {"MP3", "FLAC", "M4A", "WAV", "OGG", "MP4", "WAVPACK"}
SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".mp4", ".wv"}

# Search & Matching Settings
FUZZY_THRESHOLD = 75
DEFAULT_PAGE_SIZE = 50
MAX_SEARCH_RETRIES = 3
API_RATE_LIMIT_DELAY = 0.2  # seconds between requests

# UI Defaults
DEFAULT_ARTWORK_EMBED = True
DEFAULT_VALIDATE_TAGS = True
