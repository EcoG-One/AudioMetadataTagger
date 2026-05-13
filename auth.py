import sys
import discogs_client
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)
from config import (
    DISCOGS_USER_AGENT,
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_REQUEST_TOKEN_URL,
)

# CRITICAL: discogs-client v3 requires UserAgent to be set on the module level
# BEFORE creating a Client instance.
discogs_client.UserAgent = DISCOGS_USER_AGENT


class OAuthAuthenticator:
    def __init__(self):
        # Initialize the Client with consumer key and secret
        self.client = discogs_client.Client(
            key=DISCOGS_CONSUMER_KEY, secret=DISCOGS_CONSUMER_SECRET
        )
        self.authenticated = False

    def get_authorization_url(self) -> str:
        """
        Starts the OAuth flow. In v3, you typically just call login()
        which handles the URL generation and server callback automatically.
        """
        return None  # login() handles the UI flow

    def authenticate(self, parent=None) -> bool:
        """
        Initiates the authentication flow. Opens a browser for the user
        to authorize the application.
        """
        try:
            # This method blocks, opens the browser, and waits for the callback token
            # It automatically saves the token to self.client
            self.client.login()
            self.authenticated = True
            return True
        except Exception as e:
            error_msg = f"Authentication failed. Please check your internet connection."
            if parent:
                QMessageBox.critical(parent, "Auth Error", error_msg)
            return False

    def get_authenticated_client(self):
        """Returns the authenticated client instance to be used by the app."""
        if not self.authenticated:
            raise Exception(
                "User has not authenticated yet. Call authenticate() first."
            )
        return self.client
