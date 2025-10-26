"""Ingestion pipeline components."""

from .fetcher import EmailParserProtocol, MailFetcher, MailFetcherResult
from .parser import EmailParser

__all__ = ["EmailParser", "MailFetcher", "MailFetcherResult", "EmailParserProtocol"]
