"""Main orchestration logic for the pipeline."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .config import AppConfig
from .connectors.base import CloudConnector
from .connectors.google_drive import GoogleDriveConnector
from .connectors.local import LocalFolderConnector
from .llm.base import LLMClient
from .llm.simple import SimpleLLMClient
from .output import (
    GitMarkdownOutputHandler,
    MarkdownOutputHandler,
    ObsidianVaultOutputHandler,
    GoogleDriveMarkdownOutputHandler,
)
from .output_mindmap import GoogleDriveMindmapOutputHandler
from .state import ProcessingState
from .mindmap import Mindmap

LOGGER = logging.getLogger("ink2md")


def _extract_code_from_user_input(raw_value: str) -> str:
    """Return the OAuth authorization code from direct input or a pasted URL."""

    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Missing authorization input")

    if value.lower().startswith(("http://", "https://")):
        parsed = urlparse(value)
        query_params = parse_qs(parsed.query)
        code_candidates = query_params.get("code") or []
        if code_candidates:
            code = code_candidates[0].strip()
            if code:
                return code
        raise ValueError("Redirect URL did not include an authorization code")

    return value


def _complete_console_oauth_flow(flow) -> "Credentials":
    """Guide the user through the console-based OAuth exchange."""

    LOGGER.info(
        "Headless environment detected; using console-based Google Drive OAuth flow."
    )

    if not flow.redirect_uri:
        redirect_uris = flow.client_config.get("redirect_uris") or []
        if redirect_uris:
            flow.redirect_uri = redirect_uris[0]

    authorization_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
    )
    LOGGER.info("Authorize access by visiting:\n%s\n", authorization_url)
    LOGGER.info(
        "After approving the request, return here and paste either the verification "
        "code or the full redirected URL."
    )

    while True:
        user_input = input(
            "Paste the verification code or redirected URL from Google: "
        )
        try:
            code = _extract_code_from_user_input(user_input)
        except ValueError as exc:
            LOGGER.error("%s. Please try again.", exc)
            continue
        try:
            flow.fetch_token(code=code)
        except Exception as exc:  # pragma: no cover - depends on oauthlib internals
            LOGGER.error("Token exchange failed: %s", exc)
            continue
        return flow.credentials


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
            output_path = self.output_handler.write(
                document, markdown, pdf_bytes=pdf_bytes
            )
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


@dataclass(slots=True)
class MindmapProcessor:
    """Coordinate the handwriting-to-mindmap pipeline."""

    connector: CloudConnector
    state: ProcessingState
    llm_client: LLMClient
    output_handler: GoogleDriveMindmapOutputHandler
    prompt: Optional[str] = None

    def run_once(self) -> int:
        processed = 0
        for document in self.connector.list_pdfs():
            if self.state.has_processed(document.identifier):
                LOGGER.debug("Skipping %s; already processed", document.identifier)
                continue
            LOGGER.info("Processing mindmap %s", document.name)
            pdf_bytes = self.connector.download_pdf(document)
            mindmap = self.llm_client.extract_mindmap(
                document, pdf_bytes, prompt=self.prompt
            )
            self.output_handler.write(document, mindmap)
            self.state.mark_processed(document.identifier, name=document.name)
            processed += 1
        return processed

    def run_forever(self, poll_interval: float) -> None:
        LOGGER.info("Starting continuous mindmap processing loop (interval=%s)", poll_interval)
        while True:
            processed = self.run_once()
            LOGGER.info("Iteration complete; processed %s new mindmaps", processed)
            time.sleep(poll_interval)


@dataclass(slots=True)
class AgenticProcessor:
    """Route documents through markdown or mindmap agents based on classification."""

    connector: CloudConnector
    state: ProcessingState
    llm_client: LLMClient
    markdown_output_handler: MarkdownOutputHandler
    mindmap_output_handler: GoogleDriveMindmapOutputHandler
    hashtags: tuple[str, ...]
    orchestration_prompt: Optional[str] = None
    markdown_prompt: Optional[str] = None
    mindmap_prompt: Optional[str] = None

    def run_once(self) -> int:
        processed = 0
        for document in self.connector.list_pdfs():
            if self.state.has_processed(document.identifier):
                LOGGER.debug("Skipping %s; already processed", document.identifier)
                continue

            pdf_bytes = self.connector.download_pdf(document)
            target_pipeline = self._select_pipeline(document, pdf_bytes)
            if target_pipeline == "mindmap":
                LOGGER.info("Routing %s to mindmap agent", document.name)
                mindmap = self.llm_client.extract_mindmap(
                    document, pdf_bytes, prompt=self.mindmap_prompt
                )
                self.mindmap_output_handler.write(document, mindmap)
            else:
                LOGGER.info("Routing %s to markdown agent", document.name)
                markdown = self.llm_client.convert_pdf(
                    document, pdf_bytes, prompt=self.markdown_prompt
                )
                self.markdown_output_handler.write(document, markdown, pdf_bytes=pdf_bytes)

            self.state.mark_processed(document.identifier, name=document.name)
            processed += 1
        return processed

    def run_forever(self, poll_interval: float) -> None:
        LOGGER.info("Starting agentic processing loop (interval=%s)", poll_interval)
        while True:
            processed = self.run_once()
            LOGGER.info("Iteration complete; processed %s new documents", processed)
            time.sleep(poll_interval)

    def _select_pipeline(self, document: CloudDocument, pdf_bytes: bytes) -> str:
        if _has_mindmap_hashtag(document.name, self.hashtags):
            return "mindmap"
        try:
            decision = self.llm_client.classify_document(
                document, pdf_bytes, prompt=self.orchestration_prompt
            )
        except Exception as exc:
            LOGGER.warning("Classification failed; defaulting to markdown (%s)", exc)
            return "markdown"
        if str(decision).lower().strip() == "mindmap":
            return "mindmap"
        return "markdown"


def _build_google_drive_service(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
):
    if not config.google_drive:
        raise ValueError("Google Drive configuration missing")
    from googleapiclient.discovery import build

    gd_config = config.google_drive
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    token_path = gd_config.oauth_token_file
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_path), list(gd_config.scopes)
        )

    if force_token_refresh and token_path.exists():
        try:
            token_path.unlink()
        except OSError:
            LOGGER.warning("Unable to remove existing token cache at %s", token_path)
        credentials = None

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(gd_config.oauth_client_secrets_file),
                list(gd_config.scopes),
            )

            open_browser = bool(
                os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY")
                or os.environ.get("BROWSER")
            )
            prompt = (
                "Please open the following URL in a browser to authorize Google "
                "Drive access. If this host is headless, copy the URL into a "
                "browser on another machine and complete the consent flow: {url}"
            )
            credentials = None
            use_console_flow = force_console_oauth or not open_browser
            if not use_console_flow:
                try:
                    credentials = flow.run_local_server(
                        port=0,
                        open_browser=True,
                        authorization_prompt_message=prompt,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning(
                        "Local server OAuth flow failed (%s); falling back to console flow.",
                        exc,
                    )
                    use_console_flow = True

            if use_console_flow:
                credentials = _complete_console_oauth_flow(flow)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=credentials)


def build_connector(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
    prebuilt_service: "Resource | None" = None,
) -> CloudConnector:
    """Return the configured connector with optional OAuth overrides.

    Args:
        config: Parsed application configuration.
        force_console_oauth: Force the Google Drive connector to use the
            console-based OAuth exchange even when a local browser is available.
        force_token_refresh: Remove any cached Google Drive token so the next
            authorization round-trips through Google and issues a new refresh
            token.
        prebuilt_service: Optional already-authorized Google Drive service.
    """

    if config.provider == "google_drive":
        if not config.google_drive:
            raise ValueError("Google Drive configuration missing")
        service = prebuilt_service or _build_google_drive_service(
            config,
            force_console_oauth=force_console_oauth,
            force_token_refresh=force_token_refresh,
        )
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
    prompt_content = None
    if config.llm.prompt_path and config.llm.prompt_path.exists():
        prompt_content = config.llm.prompt_path.read_text(encoding="utf-8")

    if config.llm.provider == "simple":
        return SimpleLLMClient(prompt=prompt_content)

    if config.llm.provider == "gemini":
        if not config.llm.api_key:
            raise ValueError("llm.api_key must be provided for the Gemini provider")
        if not config.llm.model:
            raise ValueError("llm.model must be provided for the Gemini provider")

        from .llm.gemini import GeminiLLMClient

        return GeminiLLMClient(
            api_key=config.llm.api_key,
            model=config.llm.model,
            prompt=prompt_content,
            temperature=config.llm.temperature,
        )
    raise ValueError(f"Unsupported LLM provider: {config.llm.provider}")


def build_output_handler(
    config: AppConfig, *, drive_service: "Resource | None" = None
) -> MarkdownOutputHandler:
    asset_directory = config.markdown.asset_directory

    if config.markdown.provider == "git":
        if not config.markdown.git:
            raise ValueError("Git output requested but git configuration missing")
        return GitMarkdownOutputHandler(
            repository_path=config.markdown.git.repository_path,
            directory=config.markdown.directory,
            branch=config.markdown.git.branch,
            remote=config.markdown.git.remote,
            commit_message_template=config.markdown.git.commit_message_template,
            push=config.markdown.git.push,
            asset_directory=asset_directory,
        )

    if config.markdown.provider == "obsidian":
        if not config.markdown.obsidian:
            raise ValueError(
                "Obsidian output requested but obsidian configuration missing"
            )
        media_directory = asset_directory or Path("media")
        return ObsidianVaultOutputHandler(
            repository_path=config.markdown.obsidian.repository_path,
            repository_url=config.markdown.obsidian.repository_url,
            directory=config.markdown.directory,
            media_directory=media_directory,
            branch=config.markdown.obsidian.branch,
            remote=config.markdown.obsidian.remote,
            commit_message_template=config.markdown.obsidian.commit_message_template,
            media_mode=config.markdown.obsidian.media_mode,
            media_invert=config.markdown.obsidian.media_invert,
            private_key_path=config.markdown.obsidian.private_key_path,
            known_hosts_path=config.markdown.obsidian.known_hosts_path,
            push=config.markdown.obsidian.push,
        )

    if config.markdown.provider == "google_drive":
        if not config.markdown.google_drive:
            raise ValueError(
                "Google Drive output requested but google_drive configuration missing"
            )
        drive = drive_service or _build_google_drive_service(config)
        return GoogleDriveMarkdownOutputHandler(
            service=drive,
            folder_id=config.markdown.google_drive.folder_id,
            keep_local_copy=config.markdown.google_drive.keep_local_copy,
            local_directory=config.markdown.directory,
        )

    return MarkdownOutputHandler(
        config.markdown.directory, asset_directory=asset_directory
    )


def build_processor(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
):
    """Construct the processor for the configured pipeline."""

    if config.pipeline == "mindmap":
        return _build_mindmap_processor(
            config,
            force_console_oauth=force_console_oauth,
            force_token_refresh=force_token_refresh,
        )
    if config.pipeline == "agentic":
        return _build_agentic_processor(
            config,
            force_console_oauth=force_console_oauth,
            force_token_refresh=force_token_refresh,
        )
    return _build_markdown_processor(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
    )


def _build_markdown_processor(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
) -> PDFProcessor:
    drive_service = None
    if config.provider == "google_drive":
        drive_service = _build_google_drive_service(
            config,
            force_console_oauth=force_console_oauth,
            force_token_refresh=force_token_refresh,
        )

    connector = build_connector(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
        prebuilt_service=drive_service,
    )
    llm_client = build_llm_client(config)
    state = ProcessingState(config.state.path)
    output_handler = build_output_handler(config, drive_service=drive_service)
    prompt_text = _load_prompt(config.markdown.prompt_path) or _load_prompt(
        config.llm.prompt_path
    )
    return PDFProcessor(
        connector=connector,
        state=state,
        llm_client=llm_client,
        output_handler=output_handler,
        prompt=prompt_text,
    )


def _build_mindmap_processor(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
) -> MindmapProcessor:
    if not config.mindmap or not config.mindmap.google_drive:
        raise ValueError(
            "Mindmap pipeline requires mindmap.google_drive configuration"
        )

    drive_service = _build_google_drive_service(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
    )
    connector = build_connector(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
        prebuilt_service=drive_service,
    )
    llm_client = build_llm_client(config)
    state = ProcessingState(config.state.path)

    local_copy_dir = config.markdown.directory if config.mindmap.keep_local_copy else None
    output_handler = GoogleDriveMindmapOutputHandler(
        service=drive_service,
        folder_id=config.mindmap.google_drive.folder_id,
        keep_local_copy=config.mindmap.keep_local_copy,
        local_directory=local_copy_dir,
    )

    prompt_text = _load_prompt(config.mindmap.prompt_path) or _load_prompt(
        config.llm.prompt_path
    )
    return MindmapProcessor(
        connector=connector,
        state=state,
        llm_client=llm_client,
        output_handler=output_handler,
        prompt=prompt_text,
    )


def _load_prompt(path: Optional[Path]) -> Optional[str]:
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _build_agentic_processor(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
) -> AgenticProcessor:
    if not config.mindmap or not config.mindmap.google_drive:
        raise ValueError(
            "Agentic pipeline requires mindmap.google_drive configuration"
        )
    drive_service = _build_google_drive_service(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
    )
    connector = build_connector(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
        prebuilt_service=drive_service,
    )
    llm_client = build_llm_client(config)
    state = ProcessingState(config.state.path)

    markdown_output = build_output_handler(config, drive_service=drive_service)
    local_copy_dir = config.markdown.directory if config.mindmap.keep_local_copy else None
    mindmap_output = GoogleDriveMindmapOutputHandler(
        service=drive_service,
        folder_id=config.mindmap.google_drive.folder_id,
        keep_local_copy=config.mindmap.keep_local_copy,
        local_directory=local_copy_dir,
    )

    orchestration_prompt = _load_prompt(
        (config.agentic and config.agentic.prompt_path) or None
    ) or _load_prompt(config.llm.prompt_path)
    markdown_prompt = _load_prompt(config.markdown.prompt_path) or _load_prompt(
        config.llm.prompt_path
    )
    mindmap_prompt = _load_prompt(config.mindmap.prompt_path) or _load_prompt(
        config.llm.prompt_path
    )

    hashtags = ("mm", "mindmap")
    if config.agentic and config.agentic.hashtags:
        hashtags = config.agentic.hashtags

    return AgenticProcessor(
        connector=connector,
        state=state,
        llm_client=llm_client,
        markdown_output_handler=markdown_output,
        mindmap_output_handler=mindmap_output,
        hashtags=hashtags,
        orchestration_prompt=orchestration_prompt,
        markdown_prompt=markdown_prompt,
        mindmap_prompt=mindmap_prompt,
    )


def _has_mindmap_hashtag(name: str, hashtags: tuple[str, ...]) -> bool:
    lowered = (name or "").lower()
    for tag in hashtags:
        normalized = tag.lower().lstrip("#")
        if f"#{normalized}" in lowered or f"{normalized}" in lowered:
            return True
    return False


__all__ = [
    "PDFProcessor",
    "MindmapProcessor",
    "AgenticProcessor",
    "build_connector",
    "build_llm_client",
    "build_output_handler",
    "build_processor",
]
