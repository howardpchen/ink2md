"""Gemini-powered Markdown converter."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from ..connectors.base import CloudDocument
from .base import LLMClient


_GENAI_SPEC = importlib.util.find_spec("google.generativeai")
if _GENAI_SPEC:  # pragma: no cover - imported dynamically in tests
    import google.generativeai as genai  # type: ignore
else:  # pragma: no cover - fallback executed when dependency missing
    genai = None  # type: ignore

DEFAULT_GEMINI_PROMPT = (
    "You are a senior technical writer who converts PDF documents into clean Markdown. "
    "Preserve structure, summarize key points, and produce a single consolidated output."
)


@dataclass(slots=True)
class GeminiLLMClient(LLMClient):
    """Convert PDFs to Markdown using the Gemini API."""

    api_key: str
    model: str
    prompt: Optional[str] = None
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if genai is None:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "GeminiLLMClient requires the 'google-generativeai' package."
            )
        if not self.api_key:
            raise ValueError("GeminiLLMClient requires a non-empty API key.")
        if not self.model:
            raise ValueError("GeminiLLMClient requires the name of a Gemini model.")

        genai.configure(api_key=self.api_key)
        generation_config = {
            "temperature": float(self.temperature),
        }
        self._model = genai.GenerativeModel(
            model_name=self.model,
            generation_config=generation_config,
        )

    def convert_pdf(
        self,
        document: CloudDocument,
        pdf_bytes: bytes,
        prompt: str | None = None,
    ) -> str:
        instructions = (prompt or self.prompt or DEFAULT_GEMINI_PROMPT).strip()
        uploaded_file = self._upload_pdf(document, pdf_bytes)
        try:
            payload = [{"text": instructions}, uploaded_file.as_part]
            response = self._model.generate_content(payload)
        except Exception as exc:  # pragma: no cover - dependent on external library
            raise RuntimeError("Gemini API request failed") from exc
        finally:
            uploaded_file.cleanup()
        
        feedback = getattr(response, "prompt_feedback", None)
        if feedback and getattr(feedback, "block_reason", None):
            reason = getattr(feedback, "block_reason", "unspecified")
            raise RuntimeError(f"Gemini blocked the request: {reason}")

        markdown = self._extract_response_text(response)
        if not markdown:
            raise RuntimeError("Gemini did not return any text content.")
        return markdown
        
    def _upload_pdf(self, document: CloudDocument, pdf_bytes: bytes):
        if genai is None:  # pragma: no cover - safety check
            raise RuntimeError("Gemini client is not configured.")

        display_name = (document.name or "document").strip() or "document"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            file = genai.upload_file(
                path=tmp_path,
                mime_type="application/pdf",
                display_name=display_name,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return _UploadedFileHandle(file)

    @staticmethod
    def _extract_response_text(response) -> str:
        text = getattr(response, "text", "") or ""
        if text:
            return text.strip()

        candidates = getattr(response, "candidates", None)
        parts: List[str] = []
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                for part in getattr(content, "parts", []):
                    value = getattr(part, "text", None)
                    if value:
                        parts.append(str(value))
        return "\n".join(parts).strip()

class _UploadedFileHandle:
    """Lightweight wrapper to ensure uploaded files are cleaned up."""

    def __init__(self, file_obj) -> None:
        self._file = file_obj

    @property
    def as_part(self) -> dict:
        return {
            "file_data": {
                "mime_type": getattr(self._file, "mime_type", "application/pdf"),
                "file_uri": getattr(self._file, "uri"),
            }
        }

    def cleanup(self) -> None:
        name = getattr(self._file, "name", None)
        if genai is None or not name:
            return
        try:
            genai.delete_file(name)
        except Exception:
            pass


__all__ = ["GeminiLLMClient"]
