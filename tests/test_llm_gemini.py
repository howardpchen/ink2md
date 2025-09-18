"""Tests for the Gemini LLM client."""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types

import pytest

from cloud_monitor_pdf2md.connectors.base import CloudDocument


def _install_genai_stub(monkeypatch: pytest.MonkeyPatch):
    google_pkg = types.ModuleType("google")
    google_pkg.__path__ = []  # mark as package
    google_pkg.__spec__ = importlib.machinery.ModuleSpec(
        "google", loader=None, is_package=True
    )
    google_pkg.__spec__.submodule_search_locations = []  # type: ignore[attr-defined]

    stub = types.ModuleType("google.generativeai")
    stub.__spec__ = importlib.machinery.ModuleSpec(
        "google.generativeai", loader=None, is_package=False
    )

    uploads: list[dict] = []
    deleted: list[str] = []

    class UploadedFile:
        def __init__(
            self, *, index: int, path: str, mime_type: str, display_name: str
        ) -> None:
            self.path = path
            self.mime_type = mime_type
            self.display_name = display_name
            self.uri = f"uploaded://{index}"
            self.name = f"files/{index}"

    class DummyModel:
        def __init__(self, model_name: str, generation_config: dict | None = None) -> None:
            self.model_name = model_name
            self.generation_config = generation_config or {}
            self.calls: list[list[dict]] = []

        def generate_content(self, payload):  # pragma: no cover - exercised in tests
            self.calls.append(payload)
            return types.SimpleNamespace(text="# Markdown", prompt_feedback=None)

    config_args: dict[str, str] = {}

    def configure(**kwargs):  # pragma: no cover - exercised in tests
        config_args.update(kwargs)

    def upload_file(**kwargs):  # pragma: no cover - exercised in tests
        index = len(uploads)
        uploads.append(kwargs)
        return UploadedFile(index=index, **kwargs)

    def delete_file(name: str):  # pragma: no cover - exercised in tests
        deleted.append(name)

    stub.GenerativeModel = DummyModel
    stub.configure = configure
    stub.upload_file = upload_file
    stub.delete_file = delete_file

    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name, package=None):  # pragma: no cover - passthrough helper
        if name == "google.generativeai":
            return stub.__spec__
        return original_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    setattr(google_pkg, "generativeai", stub)
    monkeypatch.setitem(sys.modules, "google.generativeai", stub)

    return stub, config_args, uploads, deleted


def _reload_gemini_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("cloud_monitor_pdf2md.llm.gemini", None)
    module = importlib.import_module("cloud_monitor_pdf2md.llm.gemini")
    return module


def test_gemini_client_generates_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    stub, config_args, uploads, deleted = _install_genai_stub(monkeypatch)
    module = _reload_gemini_module(monkeypatch)

    client = module.GeminiLLMClient(
        api_key="test-key",
        model="models/gemini-2.5-flash",
        prompt="Use markdown.",
        temperature=0.25,
    )

    document = CloudDocument(identifier="doc-1", name="Doc One")
    markdown = client.convert_pdf(document, pdf_bytes=b"fake-bytes")

    assert markdown == "# Markdown"
    assert config_args["api_key"] == "test-key"
    assert uploads and uploads[0]["display_name"] == "Doc One"
    assert "path" in uploads[0] and uploads[0]["path"].endswith(".pdf")
    assert deleted == ["files/0"]
    assert client._model.calls, "Model should receive at least one generate_content call"
    first_call = client._model.calls[0]
    assert first_call[0]["text"] == "Use markdown."
    file_part = first_call[1]["file_data"]
    assert file_part["mime_type"] == "application/pdf"
    assert file_part["file_uri"].startswith("uploaded://")


def test_gemini_client_reports_blocked_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    stub, _config_args, uploads, deleted = _install_genai_stub(monkeypatch)

    class BlockingModel(stub.GenerativeModel):  # type: ignore[attr-defined]
        def generate_content(self, payload: str):  # pragma: no cover - exercised in test
            feedback = types.SimpleNamespace(block_reason="SAFETY")
            return types.SimpleNamespace(text="", prompt_feedback=feedback, candidates=None)

    stub.GenerativeModel = BlockingModel  # type: ignore[attr-defined]
    module = _reload_gemini_module(monkeypatch)

    client = module.GeminiLLMClient(
        api_key="key",
        model="models/gemini-2.5-flash",
    )

    document = CloudDocument(identifier="doc-2", name="Doc Two")
    with pytest.raises(RuntimeError, match="Gemini blocked the request"):
        client.convert_pdf(document, pdf_bytes=b"fake")
    assert uploads, "Upload should have been attempted"
    assert "path" in uploads[0] and uploads[0]["path"].endswith(".pdf")
    assert deleted == ["files/0"]


def test_gemini_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_genai_stub(monkeypatch)
    module = _reload_gemini_module(monkeypatch)

    with pytest.raises(ValueError):
        module.GeminiLLMClient(api_key="", model="models/gemini-2.5-flash")
