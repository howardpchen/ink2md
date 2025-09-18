"""Google Drive connector."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Iterable, List, Optional

from .base import CloudConnector, CloudDocument


class GoogleDriveConnector(CloudConnector):
    """Interact with Google Drive to retrieve PDFs from a specific folder."""

    def __init__(self, service: "Resource", folder_id: str, page_size: int = 100):
        self._service = service
        self._folder_id = folder_id
        self._page_size = page_size

    def list_pdfs(self) -> Iterable[CloudDocument]:
        query = (
            f"'{self._folder_id}' in parents and mimeType='application/pdf' "
            "and trashed = false"
        )
        fields = "nextPageToken, files(id, name, modifiedTime, webViewLink)"
        page_token: Optional[str] = None
        documents: List[CloudDocument] = []
        while True:
            response = (
                self._service.files()
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
        request = self._service.files().get_media(fileId=document.identifier)
        buffer = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore

        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buffer.getvalue()


__all__ = ["GoogleDriveConnector"]
