"""Utilities for storing Markdown results."""

from __future__ import annotations

import re
from pathlib import Path

from .connectors.base import CloudDocument


class MarkdownOutputHandler:
    """Write Markdown documents to a target directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, document: CloudDocument, markdown: str) -> Path:
        safe_name = self._sanitize_name(document.name)
        target_path = self.directory / f"{safe_name}.md"
        target_path.write_text(markdown, encoding="utf-8")
        return target_path

    @staticmethod
    def _sanitize_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        return safe or "document"


__all__ = ["MarkdownOutputHandler"]
