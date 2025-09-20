"""LLM client abstractions."""

from __future__ import annotations

from typing import Protocol

from ..connectors.base import CloudDocument


class LLMClient(Protocol):
    """Minimal interface that Markdown conversion backends must implement."""

    def convert_pdf(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        """Convert the provided PDF bytes to Markdown."""


__all__ = ["LLMClient"]
