"""Discogs OAuth 1.0a Authentication Handler."""

import sys
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)
import discogs_client


class OAuthAuthenticator:
    def __init__(self):
        self.session = discogs_client.Session(
            consumer_key=DISCOGS_CONSUMER_KEY,
            consumer_secret=DISCOGS_CONSUMER_SECRET,
            user_agent=DISCOGS_USER_AGENT,
        )
        self.request_token, self.request_secret = self.session.get_request_token(
            DISCOGS_REQUEST_TOKEN_URL
        )
        self.auth_url = f"{DISCOGS_AUTHORIZE_URL}?oauth_token={self.request_token}"
        self.access_token, self.access_secret = None, None

    def get_authorization_url(self) -> str:
        return self.auth_url

    def exchange_verifier_for_token(self, verifier: str):
        try:
            self.access_token, self.access_secret = self.session.get_access_token(
                self.request_token, self.request_secret, verifier=verifier
            )
            self.session.set_auth(
                self.request_token,
                self.request_secret,
                self.access_token,
                self.access_secret,
            )
            return True
        except Exception as e:
            QMessageBox.critical(None, "Auth Error", f"Failed to authenticate: {e}")
            return False

    def get_authenticated_session(self):
        return discogs_client.Session(
            consumer_key=DISCOGS_CONSUMER_KEY,
            consumer_secret=DISCOGS_CONSUMER_SECRET,
            access_token=self.access_token,
            token_secret=self.access_secret,
            user_agent=DISCOGS_USER_AGENT,
        )


# Fallback to module-level constants if not imported from config
try:
    from config import (
        DISCOGS_CONSUMER_KEY,
        DISCOGS_CONSUMER_SECRET,
        DISCOGS_USER_AGENT,
        DISCOGS_REQUEST_TOKEN_URL,
        DISCOGS_AUTHORIZE_URL,
    )
except ImportError:
    pass
