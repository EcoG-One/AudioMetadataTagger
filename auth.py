"""Discogs OAuth 1.0a Authentication Logic."""

from requests_oauthlib import OAuth1Session
from config import (
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_REQUEST_TOKEN_URL,
    DISCOGS_ACCESS_TOKEN_URL,
)


class OAuthAuthenticator:
    def __init__(self):
        self.consumer_key = DISCOGS_CONSUMER_KEY
        self.consumer_secret = DISCOGS_CONSUMER_SECRET
        self.request_token = None
        self.request_secret = None

    def get_authorization_url(self):
        """
        Initiates the OAuth flow. Returns the URL to open in the browser.
        """
        # Create a temporary client just for the request token phase
        client = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret)

        try:
            # 1. Get Request Token
            resp = client.fetch_request_token(DISCOGS_REQUEST_TOKEN_URL)
            self.request_token = resp["oauth_token"]
            self.request_secret = resp["oauth_token_secret"]

            # 2. Get Authorize URL
            return client.authorize_url(url=DISCOGS_AUTHORIZE_URL)

        except Exception as e:
            raise Exception(f"Failed to initiate OAuth request token: {e}")

    def get_authenticated_session(self, verifier: str):
        """
        Exchanges the verifier code for an Access Token Session.
        """
        if not self.request_token:
            raise Exception(
                "No request token found. Please call get_authorization_url() first."
            )

        # Create a session to perform the token exchange using the verifier
        client = OAuth1Session(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.request_token,
            resource_owner_secret=self.request_secret,
            verifier=verifier,
        )

        try:
            # Exchange for Access Token
            token_resp = client.fetch_access_token(DISCOGS_ACCESS_TOKEN_URL)

            # Create the final authenticated session for API calls
            auth_session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=token_resp["oauth_token"],
                resource_owner_secret=token_resp["oauth_token_secret"],
            )
            return auth_session

        except Exception as e:
            raise Exception(f"Failed to exchange code for token: {e}")
