"""Configuration utilities for the Cloud Monitor PDF2MD project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple


@dataclass(slots=True)
class GoogleDriveConfig:
    """Settings required to poll a Google Drive folder.

    When the token cache path is omitted it defaults to `<client_secrets_stem>_token.json`
    in the same directory as the supplied client secrets file.
    """

    folder_id: str
    oauth_client_secrets_file: Path
    oauth_token_file: Path
    page_size: int = 100
    scopes: Tuple[str, ...] = ("https://www.googleapis.com/auth/drive.readonly",)


@dataclass(slots=True)
class LocalFolderConfig:
    """Settings for the built-in local filesystem connector."""

    path: Path


@dataclass(slots=True)
class LLMConfig:
    """Settings describing the Markdown conversion backend."""

    provider: str = "simple"
    model: Optional[str] = None
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    prompt_path: Optional[Path] = None
    temperature: float = 0.0


@dataclass(slots=True)
class GitOutputConfig:
    """Settings for publishing Markdown changes to a Git repository."""

    repository_path: Path
    branch: str = "main"
    remote: str = "origin"
    commit_message_template: str = "Add {document_name}"
    push: bool = False


@dataclass(slots=True)
class OutputConfig:
    """Configuration for writing Markdown results."""

    directory: Path
    asset_directory: Optional[Path] = None
    provider: str = "filesystem"
    git: Optional[GitOutputConfig] = None


@dataclass(slots=True)
class StateConfig:
    """Configuration for persisting processing state."""

    path: Path


@dataclass(slots=True)
class AppConfig:
    """Top-level application configuration."""

    provider: str
    poll_interval: float
    output: OutputConfig
    state: StateConfig
    llm: LLMConfig
    google_drive: Optional[GoogleDriveConfig] = None
    local: Optional[LocalFolderConfig] = None

    @staticmethod
    def _coerce_path(value: Optional[str | Path]) -> Optional[Path]:
        if value is None:
            return None
        return Path(value).expanduser().resolve()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        provider = data.get("provider", "google_drive")
        poll_interval = float(data.get("poll_interval", 300))

        output_data = data.get("output", {})
        output_dir = cls._coerce_path(output_data.get("directory"))
        if output_dir is None:
            raise ValueError("output.directory must be provided in the configuration")
        asset_dir = cls._coerce_path(output_data.get("asset_directory"))
        output_provider = output_data.get("provider", "filesystem")

        git_cfg = None
        if "git" in output_data and output_data["git"] is not None:
            git_data = output_data["git"]
            repository_path = cls._coerce_path(git_data.get("repository_path"))
            if repository_path is None:
                raise ValueError("output.git.repository_path is required when configuring git output")
            git_cfg = GitOutputConfig(
                repository_path=repository_path,
                branch=git_data.get("branch", "main"),
                remote=git_data.get("remote", "origin"),
                commit_message_template=git_data.get(
                    "commit_message_template", "Add {document_name}"
                ),
                push=bool(git_data.get("push", False)),
            )

        output = OutputConfig(
            directory=output_dir,
            asset_directory=asset_dir,
            provider=output_provider,
            git=git_cfg,
        )

        state_path = cls._coerce_path(data["state"]["path"])
        state = StateConfig(path=state_path)

        llm_data = data.get("llm", {})
        llm = LLMConfig(
            provider=llm_data.get("provider", "simple"),
            model=llm_data.get("model"),
            endpoint=llm_data.get("endpoint"),
            api_key=llm_data.get("api_key"),
            prompt_path=cls._coerce_path(llm_data.get("prompt_path")),
            temperature=float(llm_data.get("temperature", 0.0)),
        )

        google_drive_cfg = None
        if "google_drive" in data:
            gd = data["google_drive"]

            oauth_client_secrets_file = cls._coerce_path(
                gd.get("oauth_client_secrets_file")
            )
            if oauth_client_secrets_file is None:
                raise ValueError(
                    "google_drive.oauth_client_secrets_file is required for OAuth-based access"
                )

            token_override = gd.get("oauth_token_file")
            if token_override is not None:
                oauth_token_file = cls._coerce_path(token_override)
            else:
                oauth_token_file = oauth_client_secrets_file.with_name(
                    f"{oauth_client_secrets_file.stem}_token.json"
                )

            scopes: Sequence[str] = gd.get(
                "scopes", ["https://www.googleapis.com/auth/drive.readonly"]
            )
            scopes_tuple = tuple(str(scope) for scope in scopes)

            google_drive_cfg = GoogleDriveConfig(
                folder_id=gd["folder_id"],
                oauth_client_secrets_file=oauth_client_secrets_file,
                oauth_token_file=oauth_token_file,
                page_size=int(gd.get("page_size", 100)),
                scopes=scopes_tuple,
            )

        local_cfg = None
        if "local" in data:
            local_cfg = LocalFolderConfig(path=cls._coerce_path(data["local"]["path"]))

        return cls(
            provider=provider,
            poll_interval=poll_interval,
            output=output,
            state=state,
            llm=llm,
            google_drive=google_drive_cfg,
            local=local_cfg,
        )


def load_config(path: str | Path) -> AppConfig:
    """Load configuration data from a JSON file."""

    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    return AppConfig.from_dict(data)


__all__ = [
    "AppConfig",
    "GoogleDriveConfig",
    "LLMConfig",
    "LocalFolderConfig",
    "GitOutputConfig",
    "OutputConfig",
    "StateConfig",
    "load_config",
]
