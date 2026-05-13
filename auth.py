"""Discogs OAuth 1.0a Authentication Logic."""

import webbrowser
from requests_oauthlib import OAuth1Session
from config import (
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_REQUEST_TOKEN_URL,
    DISCOGS_AUTHORIZE_URL,
    DISCOGS_ACCESS_TOKEN_URL,
)


class OAuthAuthenticator:
    def __init__(self):
        self.consumer_key = DISCOGS_CONSUMER_KEY
        self.consumer_secret = DISCOGS_CONSUMER_SECRET
        self.request_token = None
        self.request_secret = None

    def get_authorization_url(self) -> str:
        """
        Step 1: Get Request Token.
        Returns the URL to open in the browser.
        """
        client = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret)
        try:
            resp = client.fetch_request_token(DISCOGS_REQUEST_TOKEN_URL)
            self.request_token = resp["oauth_token"]
            self.request_secret = resp["oauth_token_secret"]
            return client.authorize_url(url=DISCOGS_AUTHORIZE_URL)
        except Exception as e:
            raise Exception(f"Failed to initiate OAuth: {e}")

    def get_authenticated_session(self, verifier: str):
        """
        Step 2: Exchange Verifier for Access Token.
        Called after the user provides the code from the browser.
        Returns an authenticated requests_oauthlib.OAuth1Session object.
        """
        if not self.request_token:
            raise Exception("No request token found. Please start auth flow first.")

        client = OAuth1Session(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.request_token,
            resource_owner_secret=self.request_secret,
            verifier=verifier,
        )

        try:
            token_resp = client.fetch_access_token(DISCOGS_ACCESS_TOKEN_URL)

            # Create the final session for API requests
            auth_session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=token_resp["oauth_token"],
                resource_owner_secret=token_resp["oauth_token_secret"],
            )
            return auth_session
        except Exception as e:
            raise Exception(f"Failed to authenticate: {e}")
