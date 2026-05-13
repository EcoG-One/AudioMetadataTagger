import json
import logging
from pathlib import Path
from requests_oauthlib import OAuth1Session
from config import DISCOGS_API_KEY, DISCOGS_API_SECRET

logger = logging.getLogger(__name__)

# Secure persistent storage path for the token
TOKEN_FILE = Path(__file__).resolve().parent.parent / "data" / "discogs_token.json"


class OAuthAuthenticator:
    def __init__(self):
        self.consumer_key = DISCOGS_API_KEY
        self.consumer_secret = DISCOGS_API_SECRET
        self.session = None
        self.request_token = None
        self.request_token_secret = None
        self._init_request_token()

    def _init_request_token(self):
        """Initialize a fresh request token for the auth flow."""
        self.oauth = OAuth1Session(
            self.consumer_key, client_secret=self.consumer_secret
        )
        try:
            resp = self.oauth.fetch_request_token(
                "https://api.discogs.com/oauth/request_token"
            )
            self.request_token = resp["oauth_token"]
            self.request_token_secret = resp["oauth_token_secret"]
        except Exception as e:
            logger.error(f"Failed to initialize request token: {e}")

    def get_authorization_url(self):
        """Returns the URL for the user to visit and authorize the app."""
        if not self.request_token:
            self._init_request_token()
        return self.oauth.authorization_url("https://api.discogs.com/oauth/authorize")

    def get_authenticated_session(self, verifier: str):
        """Exchanges the request token and verifier for an access token and returns the authenticated session."""
        if not self.request_token:
            raise Exception(
                "No request token available. Please re-initialize authentication."
            )

        try:
            # Step 1: Exchange request token + verifier for access token
            self.oauth = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.request_token,
                resource_owner_secret=self.request_token_secret,
                verifier=verifier,
            )
            resp = self.oauth.fetch_access_token(
                "https://api.discogs.com/oauth/access_token"
            )

            # Step 2: Create the persistent session
            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=resp["oauth_token"],
                resource_owner_secret=resp["oauth_token_secret"],
            )

            # Step 3: Save token persistently
            self.save_token(resp["oauth_token"], resp["oauth_token_secret"])
            logger.info("Discogs authentication successful. Token saved persistently.")
            return self.session

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise Exception(f"Failed to authenticate with Discogs: {e}")

    def save_token(self, token: str, secret: str):
        """Securely saves the access token and secret to a local JSON file."""
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"token": token, "secret": secret}
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f)
        logger.info("Token saved to %s", TOKEN_FILE)

    def load_token(self):
        """Loads the saved token from disk. Returns tuple (token, secret) or (None, None)."""
        if not TOKEN_FILE.exists():
            return None, None
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                return data.get("token"), data.get("secret")
        except Exception as e:
            logger.warning("Failed to load token: %s", e)
            return None, None

    def restore_session(self):
        """Attempts to restore a session from a saved token and validates it against Discogs API."""
        token, secret = self.load_token()
        if not token or not secret:
            return None

        # Construct session from disk credentials
        session = OAuth1Session(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=token,
            resource_owner_secret=secret,
        )

        # Validate token by requesting identity
        try:
            resp = session.get("https://api.discogs.com/oauth/identity")
            if resp.status_code == 200:
                logger.info("Discogs token validated successfully on startup.")
                self.session = session
                return self.session
            else:
                logger.warning(
                    "Discogs token invalid (status %d). Removing token.",
                    resp.status_code,
                )
                self.remove_token()
        except Exception as e:
            logger.warning("Discogs token invalid or network error: %s", e)
            self.remove_token()

        return None

    def remove_token(self):
        """Removes the stored token from disk to force re-authentication."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            logger.info("Token removed from disk.")
