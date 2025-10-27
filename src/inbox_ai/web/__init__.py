"""Web application entry point for Inbox AI."""

from .app import create_app

app = create_app()

__all__ = ["create_app", "app"]
