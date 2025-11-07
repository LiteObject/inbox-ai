"""Ingestion pipeline components."""

from .fetcher import EmailParserProtocol, MailFetcher, MailFetcherResult
from .optimized_fetcher import OptimizedMailFetcher
from .parser import EmailParser

__all__ = [
    "EmailParser",
    "MailFetcher",
    "MailFetcherResult",
    "EmailParserProtocol",
    "OptimizedMailFetcher",
]
