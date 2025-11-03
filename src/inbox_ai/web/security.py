"""Lightweight CSRF protection helpers for the dashboard."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from starlette.responses import Response

CSRF_COOKIE_NAME = "inbox_ai_csrf"
CSRF_FIELD_NAME = "csrf_token"


@dataclass(slots=True)
class CsrfProtector:
    """Generate and validate CSRF tokens using the double-submit cookie pattern."""

    cookie_name: str = CSRF_COOKIE_NAME
    field_name: str = CSRF_FIELD_NAME
    max_age: int = 60 * 60  # 1 hour

    def generate_token(self) -> str:
        """Return a new cryptographically random token."""

        return secrets.token_urlsafe(32)

    def set_cookie(self, response: Response, token: str, *, secure: bool) -> None:
        """Persist the token in a SameSite cookie for subsequent validation."""

        response.set_cookie(
            key=self.cookie_name,
            value=token,
            max_age=self.max_age,
            httponly=True,
            samesite="lax",
            secure=secure,
        )

    def validate(self, request: Request, token: str | None) -> None:
        """Ensure the submitted token matches the version stored in the cookie."""

        cookie_token = request.cookies.get(self.cookie_name)
        if not cookie_token or not token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing CSRF token.",
            )
        if not secrets.compare_digest(cookie_token, token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token.",
            )


__all__ = ["CSRF_COOKIE_NAME", "CSRF_FIELD_NAME", "CsrfProtector"]
