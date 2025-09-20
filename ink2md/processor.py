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
)
from .state import ProcessingState

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


def build_connector(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
) -> CloudConnector:
    """Return the configured connector with optional OAuth overrides.

    Args:
        config: Parsed application configuration.
        force_console_oauth: Force the Google Drive connector to use the
            console-based OAuth exchange even when a local browser is available.
        force_token_refresh: Remove any cached Google Drive token so the next
            authorization round-trips through Google and issues a new refresh
            token.
    """

    if config.provider == "google_drive":
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


def build_output_handler(config: AppConfig) -> MarkdownOutputHandler:
    asset_directory = config.output.asset_directory

    if config.output.provider == "git":
        if not config.output.git:
            raise ValueError("Git output requested but git configuration missing")
        return GitMarkdownOutputHandler(
            repository_path=config.output.git.repository_path,
            directory=config.output.directory,
            branch=config.output.git.branch,
            remote=config.output.git.remote,
            commit_message_template=config.output.git.commit_message_template,
            push=config.output.git.push,
            asset_directory=asset_directory,
        )

    if config.output.provider == "obsidian":
        if not config.output.obsidian:
            raise ValueError(
                "Obsidian output requested but obsidian configuration missing"
            )
        media_directory = asset_directory or Path("media")
        return ObsidianVaultOutputHandler(
            repository_path=config.output.obsidian.repository_path,
            repository_url=config.output.obsidian.repository_url,
            directory=config.output.directory,
            media_directory=media_directory,
            branch=config.output.obsidian.branch,
            remote=config.output.obsidian.remote,
            commit_message_template=config.output.obsidian.commit_message_template,
            media_mode=config.output.obsidian.media_mode,
            media_invert=config.output.obsidian.media_invert,
            private_key_path=config.output.obsidian.private_key_path,
            known_hosts_path=config.output.obsidian.known_hosts_path,
            push=config.output.obsidian.push,
        )

    return MarkdownOutputHandler(
        config.output.directory, asset_directory=asset_directory
    )


def build_processor(
    config: AppConfig,
    *,
    force_console_oauth: bool = False,
    force_token_refresh: bool = False,
) -> PDFProcessor:
    """Construct the PDF processor with optional Google Drive OAuth overrides.

    Args:
        config: Parsed application configuration.
        force_console_oauth: Propagate the console-mode OAuth requirement to the
            connector.
        force_token_refresh: Drop any cached OAuth token before building the
            connector so the run performs a fresh authorization.
    """

    connector = build_connector(
        config,
        force_console_oauth=force_console_oauth,
        force_token_refresh=force_token_refresh,
    )
    llm_client = build_llm_client(config)
    state = ProcessingState(config.state.path)
    output_handler = build_output_handler(config)
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
    "build_output_handler",
    "build_processor",
]
