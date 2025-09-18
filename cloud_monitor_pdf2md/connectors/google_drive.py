"""Google Drive connector."""

from __future__ import annotations

import io
import time
from datetime import datetime
from typing import Callable, Iterable, List, Optional, TypeVar

from .base import CloudConnector, CloudDocument


T = TypeVar("T")


class GoogleDriveConnector(CloudConnector):
    """Interact with Google Drive to retrieve PDFs from a specific folder."""

    def __init__(
        self,
        service: "Resource",
        folder_id: str,
        page_size: int = 100,
        *,
        max_retries: int = 3,
        retry_initial_backoff: float = 1.0,
    ):
        self._service = service
        self._folder_id = folder_id
        self._page_size = page_size
        self._max_retries = max(1, int(max_retries))
        self._retry_initial_backoff = max(0.1, float(retry_initial_backoff))

    def list_pdfs(self) -> Iterable[CloudDocument]:
        query = (
            f"'{self._folder_id}' in parents and mimeType='application/pdf' "
            "and trashed = false"
        )
        fields = "nextPageToken, files(id, name, modifiedTime, webViewLink)"
        page_token: Optional[str] = None
        documents: List[CloudDocument] = []
        while True:
            response = self._with_retry(
                lambda page_token=page_token: self._service.files()
                .list(
                    q=query,
                    fields=fields,
                    pageToken=page_token,
                    pageSize=self._page_size,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for item in response.get("files", []):
                modified_at = None
                if "modifiedTime" in item:
                    modified_at = datetime.fromisoformat(
                        item["modifiedTime"].replace("Z", "+00:00")
                    )
                documents.append(
                    CloudDocument(
                        identifier=item["id"],
                        name=item.get("name", item["id"]),
                        modified_at=modified_at,
                        download_url=item.get("webViewLink"),
                    )
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return documents

    def download_pdf(self, document: CloudDocument) -> bytes:
        def _download() -> bytes:
            request = self._service.files().get_media(fileId=document.identifier)
            buffer = io.BytesIO()
            from googleapiclient.http import MediaIoBaseDownload  # type: ignore

            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
            return buffer.getvalue()

        return self._with_retry(_download)

    def _with_retry(self, operation: Callable[[], T]) -> T:
        delay = self._retry_initial_backoff
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                return operation()
            except Exception as exc:  # pragma: no cover - fallback for retry logic
                if not self._is_retryable_error(exc) or attempt == self._max_retries - 1:
                    raise
                last_error = exc
                self._sleep(delay)
                delay = min(delay * 2, 30.0)
        if last_error is not None:  # pragma: no cover - defensive
            raise last_error
        raise RuntimeError("Retry logic reached an unexpected state")  # pragma: no cover

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        resp = getattr(error, "resp", None)
        status = getattr(resp, "status", None)
        if status is None:
            return False
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            return False
        return 500 <= status_code < 600

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)


__all__ = ["GoogleDriveConnector"]
