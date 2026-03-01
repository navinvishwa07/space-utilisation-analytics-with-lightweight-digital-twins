"""Simple admin token authentication service."""

from __future__ import annotations

import secrets
from typing import Optional

from backend.utils.config import Settings, get_settings


class AuthenticationError(Exception):
    """Base authentication failure."""


class AdminTokenNotConfiguredError(AuthenticationError):
    """Raised when ADMIN_TOKEN is missing."""


class InvalidAdminTokenError(AuthenticationError):
    """Raised when provided token is invalid."""


class AuthService:
    """Validates login credentials and bearer tokens."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._session_token: str | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self._settings.admin_token)

    def _expected_token(self) -> str:
        if not self._settings.admin_token:
            raise AdminTokenNotConfiguredError(
                "ADMIN_TOKEN is not configured. Set ADMIN_TOKEN in environment variables."
            )
        return self._settings.admin_token

    def login(self, provided_admin_token: str) -> str:
        expected = self._expected_token()
        if not secrets.compare_digest(provided_admin_token, expected):
            raise InvalidAdminTokenError("Invalid admin token")
        self._session_token = secrets.token_urlsafe(32)
        return self._session_token

    def validate_bearer_token(self, bearer_token: str) -> None:
        if not self.auth_enabled:
            return
        if self._session_token is None:
            raise InvalidAdminTokenError("No active session. Login first.")
        if not secrets.compare_digest(bearer_token, self._session_token):
            raise InvalidAdminTokenError("Invalid bearer token")
