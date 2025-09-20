"""Tests for the Google Drive connector implementation."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import pytest

from ink2md.connectors.base import CloudDocument
from ink2md.connectors.google_drive import GoogleDriveConnector


class _FakeRequest:
    def __init__(self, response: dict):
        self._response = response

    def execute(self) -> dict:
        return self._response


class _FakeFilesResource:
    def __init__(self, list_responses: list[dict], media_payloads: dict[str, bytes]):
        self._list_responses = list_responses
        self._media_payloads = media_payloads
        self.list_calls: list[dict] = []
        self._list_index = 0
        self.get_media_calls: list[str] = []

    def list(self, **kwargs):  # pragma: no cover - thin wrapper
        response = self._list_responses[self._list_index]
        self._list_index += 1
        self.list_calls.append(kwargs)
        return _FakeRequest(response)

    def get_media(self, fileId: str):  # noqa: N803 - API parity
        self.get_media_calls.append(fileId)
        return types.SimpleNamespace(content=self._media_payloads[fileId])


class _FakeDriveService:
    def __init__(self, files_resource: _FakeFilesResource):
        self._files_resource = files_resource

    def files(self):  # pragma: no cover - API adapter
        return self._files_resource


@pytest.fixture()
def fake_drive_service() -> tuple[GoogleDriveConnector, _FakeFilesResource]:
    list_responses = [
        {
            "files": [
                {
                    "id": "doc-1",
                    "name": "Quarterly Report",
                    "modifiedTime": "2024-01-15T12:34:56Z",
                    "webViewLink": "https://drive.example/doc-1",
                }
            ],
            "nextPageToken": "token-1",
        },
        {
            "files": [
                {
                    "id": "doc-2",
                    "name": "Roadmap",
                    "modifiedTime": "2024-02-01T08:00:00Z",
                    "webViewLink": "https://drive.example/doc-2",
                }
            ],
        },
    ]
    media_payloads = {
        "doc-1": b"PDF data 1",
        "doc-2": b"PDF data 2",
    }
    files_resource = _FakeFilesResource(list_responses, media_payloads)
    connector = GoogleDriveConnector(
        service=_FakeDriveService(files_resource),
        folder_id="folder-123",
        page_size=10,
    )
    return connector, files_resource


def test_list_pdfs_collects_paginated_results(fake_drive_service: tuple[GoogleDriveConnector, _FakeFilesResource]):
    connector, files_resource = fake_drive_service
    documents = list(connector.list_pdfs())

    assert [doc.identifier for doc in documents] == ["doc-1", "doc-2"]
    assert documents[0].name == "Quarterly Report"
    assert documents[0].modified_at == datetime(2024, 1, 15, 12, 34, 56, tzinfo=timezone.utc)

    assert len(files_resource.list_calls) == 2
    first_call = files_resource.list_calls[0]
    assert first_call["q"].startswith("'folder-123' in parents")
    assert first_call["pageSize"] == 10


def test_download_pdf_streams_content(monkeypatch: pytest.MonkeyPatch, fake_drive_service: tuple[GoogleDriveConnector, _FakeFilesResource]):
    connector, files_resource = fake_drive_service

    class _FakeDownloader:
        def __init__(self, buffer, request):
            self._buffer = buffer
            self._request = request
            self._finished = False

        def next_chunk(self):
            if self._finished:
                return None, True
            self._buffer.write(self._request.content)
            self._finished = True
            return None, True

    google_module = types.ModuleType("googleapiclient")
    http_module = types.ModuleType("googleapiclient.http")
    http_module.MediaIoBaseDownload = _FakeDownloader
    monkeypatch.setitem(sys.modules, "googleapiclient", google_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http_module)

    document = CloudDocument(identifier="doc-2", name="Roadmap")
    payload = connector.download_pdf(document)

    assert payload == b"PDF data 2"
    assert files_resource.get_media_calls == ["doc-2"]
class _TransientHttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.resp = types.SimpleNamespace(status=status)


def test_list_pdfs_retries_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    list_responses = [
        {
            "files": [
                {
                    "id": "doc-1",
                    "name": "Quarterly Report",
                    "modifiedTime": "2024-01-15T12:34:56Z",
                }
            ]
        }
    ]
    media_payloads: dict[str, bytes] = {}

    class _FlakyFilesResource(_FakeFilesResource):
        def __init__(self) -> None:
            super().__init__(list_responses, media_payloads)
            self.attempts = 0

        def list(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise _TransientHttpError(502)
            return super().list(**kwargs)

    resource = _FlakyFilesResource()
    connector = GoogleDriveConnector(
        service=_FakeDriveService(resource),
        folder_id="folder-123",
        page_size=10,
    )
    monkeypatch.setattr(connector, "_sleep", lambda _delay: None)

    docs = list(connector.list_pdfs())

    assert len(docs) == 1
    assert docs[0].identifier == "doc-1"
    assert resource.list_calls[0]["pageToken"] is None
    assert len(resource.list_calls) == 1  # only the successful call is recorded
    assert resource.attempts == 2


def test_download_pdf_retries_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    list_responses = [
        {
            "files": [
                {
                    "id": "doc-1",
                    "name": "Quarterly Report",
                    "modifiedTime": "2024-01-15T12:34:56Z",
                }
            ]
        }
    ]
    media_payloads = {"doc-1": b"PDF data"}
    files_resource = _FakeFilesResource(list_responses, media_payloads)

    connector = GoogleDriveConnector(
        service=_FakeDriveService(files_resource),
        folder_id="folder-123",
        page_size=10,
    )

    class _FlakyDownloader:
        failures_remaining = 1

        def __init__(self, buffer, request):
            self._buffer = buffer
            self._request = request

        def next_chunk(self):
            if type(self).failures_remaining > 0:
                type(self).failures_remaining -= 1
                raise _TransientHttpError(502)
            self._buffer.write(self._request.content)
            return None, True

    google_module = types.ModuleType("googleapiclient")
    http_module = types.ModuleType("googleapiclient.http")
    http_module.MediaIoBaseDownload = _FlakyDownloader
    monkeypatch.setitem(sys.modules, "googleapiclient", google_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http_module)
    monkeypatch.setattr(connector, "_sleep", lambda _delay: None)

    document = CloudDocument(identifier="doc-1", name="Quarterly Report")
    payload = connector.download_pdf(document)

    assert payload == b"PDF data"
