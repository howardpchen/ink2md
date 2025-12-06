"""A basic Markdown converter that extracts text locally."""

from __future__ import annotations

import importlib.util
import io
from dataclasses import dataclass
from typing import Optional

from ..connectors.base import CloudDocument
from ..mindmap import Mindmap, MindmapNode
from .base import LLMClient


_PYPDF_AVAILABLE = importlib.util.find_spec("pypdf") is not None
if _PYPDF_AVAILABLE:  # pragma: no cover - depends on optional dependency
    from pypdf import PdfReader  # type: ignore
else:  # pragma: no cover - fallback path executed when dependency missing
    PdfReader = None  # type: ignore


DEFAULT_PROMPT = """You are a helpful assistant that converts PDF content to Markdown."""


@dataclass(slots=True)
class SimpleLLMClient(LLMClient):
    """Convert PDFs to Markdown using local text extraction heuristics."""

    prompt: Optional[str] = None

    def convert_pdf(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        effective_prompt = prompt or self.prompt or DEFAULT_PROMPT
        text = self._extract_text(pdf_bytes)
        markdown_lines = [f"# {document.name}", "", f"> {effective_prompt}", ""]
        for paragraph in self._segment_paragraphs(text):
            markdown_lines.append(paragraph)
            markdown_lines.append("")
        return "\n".join(markdown_lines).strip()

    def _extract_text(self, pdf_bytes: bytes) -> str:
        if PdfReader is None:
            return "(Install 'pypdf' to enable local PDF text extraction.)"
        reader = PdfReader(io.BytesIO(pdf_bytes))
        contents = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            contents.append(page_text.strip())
        return "\n".join(contents)

    @staticmethod
    def _segment_paragraphs(text: str) -> list[str]:
        raw_lines = [line.strip() for line in text.splitlines()]
        paragraphs: list[str] = []
        buffer: list[str] = []
        for line in raw_lines:
            if not line:
                if buffer:
                    paragraphs.append(" ".join(buffer))
                    buffer.clear()
                continue
            buffer.append(line)
        if buffer:
            paragraphs.append(" ".join(buffer))
        return paragraphs or ["(The source PDF did not contain extractable text.)"]

    def extract_mindmap(
        self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None
    ) -> Mindmap:
        """Produce a simple mindmap tree derived from extracted text."""

        del prompt  # Simple client ignores prompt but keeps signature parity.
        text = self._extract_text(pdf_bytes)
        branches = [p for p in self._segment_paragraphs(text) if p]
        if not branches:
            branches = ["No extractable content found."]

        children = [MindmapNode(text=branch) for branch in branches]
        root = MindmapNode(text=document.name or "Mindmap", children=children)
        return Mindmap(root=root)

    def classify_document(
        self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None
    ) -> str:
        """Heuristically route documents; simple client defaults to markdown."""

        name = (document.name or "").lower()
        if any(tag in name for tag in ("#mm", "#mindmap", " mindmap", " mind map")):
            return "mindmap"
        text = self._extract_text(pdf_bytes).lower()
        if "#mm" in text or "#mindmap" in text:
            return "mindmap"
        return "markdown"


__all__ = ["SimpleLLMClient"]
