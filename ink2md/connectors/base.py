"""Connector interfaces for discovering and retrieving PDF files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol


@dataclass(frozen=True, slots=True)
class CloudDocument:
    """Metadata describing a PDF stored in a remote system."""

    identifier: str
    name: str
    modified_at: datetime | None = None
    download_url: str | None = None


class CloudConnector(Protocol):
    """Abstract representation of a cloud storage provider."""

    def list_pdfs(self) -> Iterable[CloudDocument]:
        """Return an iterable of PDFs that exist within the monitored folder."""

    def download_pdf(self, document: CloudDocument) -> bytes:
        """Retrieve the raw bytes for the provided document."""


__all__ = ["CloudDocument", "CloudConnector"]
