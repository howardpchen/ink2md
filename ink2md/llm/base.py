"""LLM client abstractions."""

from __future__ import annotations

from typing import Protocol

from ..connectors.base import CloudDocument
from ..mindmap import Mindmap


class LLMClient(Protocol):
    """Minimal interface that Markdown conversion backends must implement."""

    def convert_pdf(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        """Convert the provided PDF bytes to Markdown."""

    def extract_mindmap(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> Mindmap:
        """Convert the provided PDF bytes to a structured mindmap."""

    def classify_document(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        """Return the target pipeline for this document, e.g., 'markdown' or 'mindmap'."""


__all__ = ["LLMClient"]
