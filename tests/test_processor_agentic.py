"""Agentic processor tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from ink2md.connectors.base import CloudConnector, CloudDocument
from ink2md.mindmap import Mindmap, MindmapNode
from ink2md.output import MarkdownOutputHandler
from ink2md.output_mindmap import GoogleDriveMindmapOutputHandler
from ink2md.processor import AgenticProcessor
from ink2md.state import ProcessingState


class FakeConnector:
    def __init__(self, documents: List[CloudDocument]) -> None:
        self._documents = documents
        self.downloaded: List[str] = []

    def list_pdfs(self) -> Iterable[CloudDocument]:
        return list(self._documents)

    def download_pdf(self, document: CloudDocument) -> bytes:
        self.downloaded.append(document.identifier)
        return b"%PDF-fake"


class FakeLLM:
    def __init__(self) -> None:
        self.classify_calls: list[str] = []
        self.convert_calls: list[str] = []
        self.mindmap_calls: list[str] = []

    def classify_document(
        self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None
    ) -> str:
        self.classify_calls.append(document.identifier)
        return "mindmap" if "map" in (document.name or "").lower() else "markdown"

    def convert_pdf(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        self.convert_calls.append(document.identifier)
        return f"markdown:{document.name}"

    def extract_mindmap(
        self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None
    ) -> Mindmap:
        self.mindmap_calls.append(document.identifier)
        return Mindmap(root=MindmapNode(text=document.name or "root"))


class RecordingMarkdownOutput(MarkdownOutputHandler):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.writes: list[str] = []

    def write(self, document: CloudDocument, markdown: str, *, pdf_bytes: bytes | None = None, basename=None):
        self.writes.append(f"{document.identifier}:{markdown}")
        return super().write(document, markdown, pdf_bytes=pdf_bytes, basename=basename)


class RecordingMindmapOutput(GoogleDriveMindmapOutputHandler):
    def __init__(self, directory: Path):
        self.writes: list[str] = []
        super().__init__(service=_DummyService(), folder_id="folder", keep_local_copy=True, local_directory=directory)

    def write(self, document: CloudDocument, mindmap: Mindmap):
        self.writes.append(f"{document.identifier}:{mindmap.root.text}")
        return super().write(document, mindmap)


class _DummyService:
    def files(self):
        return self

    def create(self, body=None, media_body=None, supportsAllDrives=None):
        return self

    def execute(self):
        return {}


def test_agentic_processor_routes_documents(tmp_path: Path) -> None:
    docs = [
        CloudDocument(identifier="d1", name="general notes"),
        CloudDocument(identifier="d2", name="Project MindMap"),  # triggers mindmap via classifier
        CloudDocument(identifier="d3", name="sketch #mm"),  # hashtag forces mindmap
    ]
    connector = FakeConnector(docs)
    llm = FakeLLM()
    markdown_output = RecordingMarkdownOutput(tmp_path / "md")
    mindmap_output = RecordingMindmapOutput(tmp_path / "mm")
    state = ProcessingState(tmp_path / "state.json")

    processor = AgenticProcessor(
        connector=connector,
        state=state,
        llm_client=llm,
        markdown_output_handler=markdown_output,
        mindmap_output_handler=mindmap_output,
        hashtags=("mm", "mindmap"),
        orchestration_prompt="route",
    )

    processed = processor.run_once()

    assert processed == 3
    assert llm.classify_calls == ["d1"]
    assert llm.convert_calls == ["d1"]
    assert llm.mindmap_calls == ["d2", "d3"]
    assert any("d1:" in entry for entry in markdown_output.writes)
    assert any("d2:" in entry for entry in mindmap_output.writes)
    assert any("d3:" in entry for entry in mindmap_output.writes)
    assert state.has_processed("d1") and state.has_processed("d2") and state.has_processed("d3")


def test_agentic_processor_with_sample_pdfs(tmp_path: Path) -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    markdown_pdf = data_dir / "Test markdown.pdf"
    mindmap_pdf = data_dir / "Test mindmap.pdf"

    docs = [
        CloudDocument(identifier=str(markdown_pdf), name=markdown_pdf.stem),
        CloudDocument(identifier=str(mindmap_pdf), name=mindmap_pdf.stem),
    ]

    class FileConnector:
        def list_pdfs(self) -> Iterable[CloudDocument]:
            return docs

        def download_pdf(self, document: CloudDocument) -> bytes:
            return Path(document.identifier).read_bytes()

    connector = FileConnector()
    llm = FakeLLM()
    markdown_output = RecordingMarkdownOutput(tmp_path / "md")
    mindmap_output = RecordingMindmapOutput(tmp_path / "mm")
    state = ProcessingState(tmp_path / "state.json")

    processor = AgenticProcessor(
        connector=connector,  # type: ignore[arg-type]
        state=state,
        llm_client=llm,
        markdown_output_handler=markdown_output,
        mindmap_output_handler=mindmap_output,
        hashtags=("mm", "mindmap"),
    )

    processed = processor.run_once()

    assert processed == 2
    # Hashtag/keyword short-circuit routes the mindmap file without classification.
    assert set(llm.classify_calls) == {str(markdown_pdf)}
    assert state.has_processed(str(markdown_pdf))
    assert state.has_processed(str(mindmap_pdf))
