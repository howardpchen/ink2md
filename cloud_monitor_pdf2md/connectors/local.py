"""Local filesystem connector useful for development and testing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from .base import CloudConnector, CloudDocument


class LocalFolderConnector(CloudConnector):
    """Treat a folder on the local filesystem as the monitored source."""

    def __init__(self, folder: str | Path):
        self._folder = Path(folder).expanduser().resolve()
        if not self._folder.exists():
            raise FileNotFoundError(f"Local folder does not exist: {self._folder}")

    def list_pdfs(self) -> Iterable[CloudDocument]:  # pragma: no cover - simple wrapper
        documents: List[CloudDocument] = []
        for path in sorted(self._folder.glob("*.pdf")):
            stat = path.stat()
            documents.append(
                CloudDocument(
                    identifier=str(path),
                    name=path.stem,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    download_url=str(path),
                )
            )
        return documents

    def download_pdf(self, document: CloudDocument) -> bytes:
        pdf_path = Path(document.identifier)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        with pdf_path.open("rb") as handle:
            return handle.read()


__all__ = ["LocalFolderConnector"]
