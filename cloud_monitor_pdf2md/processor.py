"""Main orchestration logic for the pipeline."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from .config import AppConfig
from .connectors.base import CloudConnector
from .connectors.google_drive import GoogleDriveConnector
from .connectors.local import LocalFolderConnector
from .llm.base import LLMClient
from .llm.simple import SimpleLLMClient
from .output import MarkdownOutputHandler
from .state import ProcessingState

LOGGER = logging.getLogger("cloud_monitor_pdf2md")


@dataclass(slots=True)
class PDFProcessor:
    """Coordinate the flow between connectors, LLMs, and storage."""

    connector: CloudConnector
    state: ProcessingState
    llm_client: LLMClient
    output_handler: MarkdownOutputHandler
    prompt: Optional[str] = None

    def run_once(self) -> int:
        processed = 0
        for document in self.connector.list_pdfs():
            if self.state.has_processed(document.identifier):
                LOGGER.debug("Skipping %s; already processed", document.identifier)
                continue
            LOGGER.info("Processing %s", document.name)
            pdf_bytes = self.connector.download_pdf(document)
            markdown = self.llm_client.convert_pdf(document, pdf_bytes, prompt=self.prompt)
            output_path = self.output_handler.write(document, markdown)
            LOGGER.info("Wrote Markdown to %s", output_path)
            self.state.mark_processed(document.identifier, name=document.name)
            processed += 1
        return processed

    def run_forever(self, poll_interval: float) -> None:
        LOGGER.info("Starting continuous processing loop (interval=%s)", poll_interval)
        while True:
            processed = self.run_once()
            LOGGER.info("Iteration complete; processed %s new documents", processed)
            time.sleep(poll_interval)


def build_connector(config: AppConfig) -> CloudConnector:
    if config.provider == "google_drive":
        if not config.google_drive:
            raise ValueError("Google Drive configuration missing")
        if not config.google_drive.service_account_file:
            raise ValueError("A service_account_file is required for Google Drive usage")
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            str(config.google_drive.service_account_file)
        )
        if config.google_drive.delegated_user:
            credentials = credentials.with_subject(config.google_drive.delegated_user)
        service = build("drive", "v3", credentials=credentials)
        return GoogleDriveConnector(
            service=service,
            folder_id=config.google_drive.folder_id,
            page_size=config.google_drive.page_size,
        )
    if config.provider == "local":
        if not config.local:
            raise ValueError("Local folder configuration missing")
        return LocalFolderConnector(config.local.path)
    raise ValueError(f"Unsupported provider: {config.provider}")


def build_llm_client(config: AppConfig) -> LLMClient:
    if config.llm.provider == "simple":
        prompt_content = None
        if config.llm.prompt_path and config.llm.prompt_path.exists():
            prompt_content = config.llm.prompt_path.read_text(encoding="utf-8")
        return SimpleLLMClient(prompt=prompt_content)
    raise ValueError(f"Unsupported LLM provider: {config.llm.provider}")


def build_processor(config: AppConfig) -> PDFProcessor:
    connector = build_connector(config)
    llm_client = build_llm_client(config)
    state = ProcessingState(config.state.path)
    output_handler = MarkdownOutputHandler(config.output.directory)
    prompt_text = None
    if config.llm.prompt_path and config.llm.prompt_path.exists():
        prompt_text = config.llm.prompt_path.read_text(encoding="utf-8")
    return PDFProcessor(
        connector=connector,
        state=state,
        llm_client=llm_client,
        output_handler=output_handler,
        prompt=prompt_text,
    )


__all__ = [
    "PDFProcessor",
    "build_connector",
    "build_llm_client",
    "build_processor",
]
