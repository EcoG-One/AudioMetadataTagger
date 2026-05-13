"""Discogs OAuth 1.0a Authentication Handler using requests-oauthlib."""

import sys
import webbrowser
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
)
from requests_oauthlib import OAuth1Session
from config import (
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_REQUEST_TOKEN_URL,
    DISCOGS_AUTHORIZE_URL,
    DISCOGS_ACCESS_TOKEN_URL,
    DISCOGS_USER_AGENT,
)


class OAuthAuthenticator:
    def __init__(self):
        self.consumer_key = DISCOGS_CONSUMER_KEY
        self.consumer_secret = DISCOGS_CONSUMER_SECRET
        self.session = None  # Holds the authenticated OAuth1Session
        self.user_session = None  # Holds the UserAgent string

    def get_oauth_session(self):
        """
        Initiates the OAuth 1.0a flow.
        1. Gets a request token.
        2. Opens browser for user authorization.
        3. Prompts user to paste the verifier code.
        4. Returns the authenticated session object.
        """
        try:
            # 1. Get Request Token
            client = OAuth1Session(
                self.consumer_key, client_secret=self.consumer_secret
            )
            fetch_response = client.fetch_request_token(DISCOGS_REQUEST_TOKEN_URL)

            # Save the tokens to be retrieved later
            self.request_token = fetch_response["oauth_token"]
            self.request_secret = fetch_response["oauth_token_secret"]

            # 2. Get Authorization URL
            authorization_url = client.authorize_url(url=DISCOGS_AUTHORIZE_URL)
            print(f"Please authorize: {authorization_url}")

            # Open browser automatically (optional, user can also type URL)
            webbrowser.open(authorization_url)

            # 3. User pastes the Verifier code (OAUTH_VERIFIER)
            verifier = self._get_verifier_from_user()

            if not verifier:
                return None

            # 4. Exchange Request Token for Access Token
            client = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.request_token,
                resource_owner_secret=self.request_secret,
                verifier=verifier,
            )
            resource_owner_details = client.fetch_access_token(DISCOGS_ACCESS_TOKEN_URL)

            # Create the final authenticated session
            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=resource_owner_details["oauth_token"],
                resource_owner_secret=resource_owner_details["oauth_token_secret"],
            )

            self.user_session = DISCOGS_USER_AGENT

            return self.session

        except Exception as e:
            print(f"Authentication Error: {e}")
            return None

    def _get_verifier_from_user(self):
        """Dialog to get the OAUTH_VERIFIER code from the user."""
        dlg = QDialog()
        dlg.setWindowTitle("Discogs Authentication")
        layout = QVBoxLayout(dlg)

        layout.addWidget(
            QLabel(
                "Please authorize the app in your browser, then paste the VERIFIER code below:"
            )
        )
        txt = QPlainTextEdit()
        txt.setPlaceholderText("Paste the 7-digit code here...")
        layout.addWidget(txt)

        btn_ok = QPushButton("Confirm")
        layout.addWidget(btn_ok)

        verifier_code = ""

        def accept():
            nonlocal verifier_code
            verifier_code = txt.toPlainText().strip()
            dlg.accept()

        btn_ok.clicked.connect(accept)
        dlg.exec()

        return verifier_code
