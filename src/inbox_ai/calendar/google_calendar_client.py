"""Google Calendar client for OAuth 2.0 and event management."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from inbox_ai.core.config import CalendarSettings

logger = logging.getLogger(__name__)


class GoogleCalendarClient:
    """Client for interacting with Google Calendar API using OAuth 2.0."""

    OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, settings: CalendarSettings):
        """Initialize the calendar client with settings."""
        self._settings = settings
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def get_authorization_url(self, state: str) -> str:
        """Generate OAuth 2.0 authorization URL for user consent."""
        params = {
            "client_id": self._settings.client_id,
            "redirect_uri": self._settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent to get refresh token
            "state": state,
        }
        return f"{self.OAUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._settings.client_id,
                    "client_secret": self._settings.client_secret,
                    "redirect_uri": self._settings.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            tokens = response.json()
            self._access_token = tokens.get("access_token")
            self._refresh_token = tokens.get("refresh_token")
            logger.info("Successfully exchanged authorization code for tokens")
            return tokens

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using the refresh token."""
        logger.info("Attempting to refresh access token...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._settings.client_id,
                    "client_secret": self._settings.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )

            # Debug logging for token refresh
            if response.status_code != 200:
                logger.error("Token refresh failed: %s", response.status_code)
                logger.error("Response: %s", response.text)

            response.raise_for_status()
            tokens = response.json()
            self._access_token = tokens.get("access_token")
            logger.info(
                "Successfully refreshed access token (starts with: %s...)",
                self._access_token[:10] if self._access_token else "None",
            )
            return tokens

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token, refreshing if necessary."""
        if not self._access_token:
            raise ValueError("No access token available")

        # Check if token is valid by making a simple API call
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.CALENDAR_API_BASE}/users/me/calendarList",
                headers={"Authorization": f"Bearer {self._access_token}"},
                params={"maxResults": 1},
            )

            if response.status_code in (401, 403):
                logger.warning(
                    "Token appears invalid (status %s), attempting refresh...",
                    response.status_code,
                )
                logger.debug("Error response: %s", response.text)

                if self._refresh_token:
                    await self.refresh_access_token(self._refresh_token)
                else:
                    raise ValueError("Token is invalid and no refresh token available")

    def set_tokens(self, access_token: str, refresh_token: str | None = None) -> None:
        """Set access and refresh tokens for authenticated requests."""
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token

    async def list_calendars(self) -> list[dict[str, Any]]:
        """List all calendars available to the user."""
        if not self._access_token:
            raise ValueError("No access token available. Please authenticate first.")

        # Ensure token is valid before making request
        await self._ensure_valid_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.CALENDAR_API_BASE}/users/me/calendarList",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )

            # Debug logging
            if response.status_code != 200:
                logger.error("Failed to list calendars: %s", response.status_code)
                logger.error("Response: %s", response.text)

            response.raise_for_status()
            data = response.json()
            calendars = data.get("items", [])
            logger.info("Retrieved %d calendars", len(calendars))
            return calendars

    async def create_event(
        self,
        action: str,
        due_at: datetime,
        email_subject: str | None,
        email_sender: str | None,
        calendar_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event for a follow-up task."""
        if not self._access_token:
            raise ValueError("No access token available. Please authenticate first.")

        # Ensure token is valid before making request
        await self._ensure_valid_token()

        target_calendar = calendar_id or self._settings.selected_calendar
        logger.info("Creating event in calendar: %s", target_calendar)

        # Build event description with context
        description_parts = [f"Action: {action}"]
        if email_subject:
            description_parts.append(f"Email Subject: {email_subject}")
        if email_sender:
            description_parts.append(f"From: {email_sender}")
        description = "\n".join(description_parts)

        # Calculate end time (due_at + duration)
        end_time = due_at + timedelta(minutes=self._settings.event_duration_minutes)

        event_body = {
            "summary": action,
            "description": description,
            "start": {
                "dateTime": due_at.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
            "reminders": {
                "useDefault": True,
            },
        }

        logger.debug("Event body: %s", event_body)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.CALENDAR_API_BASE}/calendars/{target_calendar}/events",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(event_body),
            )

            # Enhanced debugging for 403 errors
            if response.status_code == 403:
                logger.error("403 Forbidden Error Details:")
                logger.error("Calendar ID: %s", target_calendar)
                logger.error("Response: %s", response.text)
                logger.error(
                    "Access token (first 10 chars): %s...",
                    self._access_token[:10] if self._access_token else "None",
                )
                logger.error("Refresh token available: %s", bool(self._refresh_token))

            response.raise_for_status()
            event = response.json()
            logger.info(
                "Created calendar event: %s (ID: %s)",
                event.get("summary"),
                event.get("id"),
            )
            return event

    async def get_event(
        self, event_id: str, calendar_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve a calendar event by ID."""
        await self._ensure_valid_token()

        target_calendar = calendar_id or self._settings.selected_calendar
        logger.debug(
            "Fetching calendar event %s from calendar %s", event_id, target_calendar
        )

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.CALENDAR_API_BASE}/calendars/{target_calendar}/events/{event_id}",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )

            if response.status_code == 404:
                logger.info("Calendar event %s returned 404", event_id)
                raise Exception("404: Event not found")

            if response.status_code != 200:
                logger.error(
                    "Failed to fetch calendar event %s: %s - %s",
                    event_id,
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()

            return response.json()

    async def update_event(
        self,
        event_id: str,
        action: str,
        due_at: datetime,
        email_subject: str | None,
        email_sender: str | None,
        calendar_id: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing calendar event."""
        if not self._access_token:
            raise ValueError("No access token available. Please authenticate first.")

        target_calendar = calendar_id or self._settings.selected_calendar

        # Build event description with context
        description_parts = [f"Action: {action}"]
        if email_subject:
            description_parts.append(f"Email Subject: {email_subject}")
        if email_sender:
            description_parts.append(f"From: {email_sender}")
        description = "\n".join(description_parts)

        # Calculate end time
        end_time = due_at + timedelta(minutes=self._settings.event_duration_minutes)

        event_body = {
            "summary": action,
            "description": description,
            "start": {
                "dateTime": due_at.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.CALENDAR_API_BASE}/calendars/{target_calendar}/events/{event_id}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(event_body),
            )
            response.raise_for_status()
            event = response.json()
            logger.info(
                "Updated calendar event: %s (ID: %s)",
                event.get("summary"),
                event.get("id"),
            )
            return event

    def get_event_url(self, event_id: str, calendar_id: str | None = None) -> str:
        """Generate a URL to view the event in Google Calendar.

        The URL opens the event in the Google Calendar web interface for viewing.
        """
        _ = calendar_id  # Reserved for future use
        # Standard format for viewing events in Google Calendar
        return f"https://calendar.google.com/calendar/r/events/{event_id}"


__all__ = ["GoogleCalendarClient"]
