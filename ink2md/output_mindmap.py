"""Output handler for uploading FreeMind mindmaps to Google Drive."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime as dt_module, timezone
from pathlib import Path
from typing import Optional

from .connectors.base import CloudDocument
from .mindmap import Mindmap, serialize_to_freemind


class GoogleDriveMindmapOutputHandler:
    """Upload FreeMind mindmaps to a Google Drive folder."""

    def __init__(
        self,
        service: "Resource",
        folder_id: str,
        *,
        keep_local_copy: bool = False,
        local_directory: str | Path | None = None,
    ) -> None:
        if not folder_id:
            raise ValueError("A target folder_id is required for mindmap uploads")
        self._service = service
        self._folder_id = folder_id
        self._keep_local_copy = bool(keep_local_copy)
        self._local_directory = (
            Path(local_directory).expanduser().resolve() if local_directory else None
        )
        if self._keep_local_copy and self._local_directory:
            self._local_directory.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        document: CloudDocument,
        mindmap: Mindmap,
    ) -> Path | None:
        xml_content = serialize_to_freemind(mindmap)
        basename = self._build_basename(document)
        filename = f"{basename}.mm"

        tmp_path: Optional[Path] = None
        local_path: Optional[Path] = None
        try:
            tmp_path = self._write_temp_file(xml_content)
            self._upload_to_drive(filename, tmp_path)
        finally:
            if self._keep_local_copy and self._local_directory:
                local_path = self._local_directory / filename
                local_path.write_text(xml_content, encoding="utf-8")
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return local_path

    def _upload_to_drive(self, filename: str, tmp_path: Path) -> None:
        from googleapiclient.http import MediaFileUpload  # type: ignore

        media = MediaFileUpload(
            str(tmp_path), mimetype="application/x-freemind", resumable=False
        )
        metadata = {
            "name": filename,
            "parents": [self._folder_id],
            "mimeType": "application/x-freemind",
        }
        (
            self._service.files()
            .create(
                body=metadata,
                media_body=media,
                supportsAllDrives=True,
            )
            .execute()
        )

    @staticmethod
    def _write_temp_file(contents: str) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".mm", delete=False) as handle:
            handle.write(contents.encode("utf-8"))
            return Path(handle.name)

    @staticmethod
    def _sanitize_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        return safe or "mindmap"

    def _build_basename(self, document: CloudDocument) -> str:
        suffix = self._determine_timestamp_suffix(document)
        safe_name = self._sanitize_name(document.name)
        return f"{safe_name}-{suffix}"

    @staticmethod
    def _determine_timestamp_suffix(document: CloudDocument) -> str:
        if document.modified_at is not None:
            timestamp = document.modified_at.astimezone(timezone.utc)
        else:
            timestamp = dt_module.now(timezone.utc)
        return timestamp.strftime("%Y%m%d%H%M%S")


__all__ = ["GoogleDriveMindmapOutputHandler"]
