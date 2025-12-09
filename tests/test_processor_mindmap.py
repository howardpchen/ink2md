"""Mindmap processor tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from ink2md.connectors.base import CloudConnector, CloudDocument
from ink2md.mindmap import Mindmap, MindmapNode
from ink2md.processor import MindmapProcessor
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
        self.prompts: list[str | None] = []
        self.calls: list[str] = []

    def convert_pdf(self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None) -> str:
        raise NotImplementedError

    def extract_mindmap(
        self, document: CloudDocument, pdf_bytes: bytes, prompt: str | None = None
    ) -> Mindmap:
        self.prompts.append(prompt)
        self.calls.append(document.identifier)
        root = MindmapNode(
            text=document.name,
            children=[MindmapNode(text="Child")],
        )
        return Mindmap(root=root)


class RecordingOutput:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, document: CloudDocument, mindmap: Mindmap):
        self.writes.append(f"{document.identifier}:{mindmap.root.text}")
        return None


def test_mindmap_processor_runs_once(tmp_path: Path) -> None:
    document = CloudDocument(identifier="doc-1", name="Sketch One")
    connector = FakeConnector([document])
    llm = FakeLLM()
    output = RecordingOutput()
    state = ProcessingState(tmp_path / "state.json")

    processor = MindmapProcessor(
        connector=connector,
        state=state,
        llm_client=llm,
        output_handler=output,  # type: ignore[arg-type]
        prompt="Use mindmap prompt",
    )

    processed = processor.run_once()

    assert processed == 1
    assert connector.downloaded == ["doc-1"]
    assert llm.calls == ["doc-1"]
    assert llm.prompts == ["Use mindmap prompt"]
    assert output.writes == ["doc-1:Sketch One"]
    assert state.has_processed("doc-1")
