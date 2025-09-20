"""Configuration utilities for the Ink2MD project."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Sequence, Tuple


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
    obsidian: Optional["ObsidianOutputConfig"] = None


@dataclass(slots=True)
class ObsidianOutputConfig:
    """Settings specific to synchronising with an Obsidian Git repository."""

    repository_path: Path
    repository_url: str
    branch: str = "main"
    remote: str = "origin"
    commit_message_template: str = (
        "A new file from you has been added: {markdown_path}"
    )
    push: bool = True
    private_key_path: Optional[Path] = None
    known_hosts_path: Optional[Path] = None
    media_mode: Literal["pdf", "png", "jpg"] = "pdf"
    media_invert: bool = False


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
    def _coerce_path(
        value: Optional[str | Path], *, allow_relative: bool = False
    ) -> Optional[Path]:
        if value is None:
            return None
        path = Path(value).expanduser()
        if allow_relative and not path.is_absolute():
            return path
        return path.resolve()

    @staticmethod
    def _expand_env(value: Optional[str | Path]) -> Optional[str | Path]:
        if value is None:
            return None
        if isinstance(value, Path):
            return value
        return os.path.expandvars(str(value))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        provider = data.get("provider", "google_drive")
        poll_interval = float(data.get("poll_interval", 300))

        output_data = data.get("output", {})
        output_provider = output_data.get("provider", "filesystem")
        allow_relative = output_provider in {"git", "obsidian"}
        output_dir = cls._coerce_path(
            output_data.get("directory"), allow_relative=allow_relative
        )
        if output_dir is None:
            raise ValueError("output.directory must be provided in the configuration")
        asset_value = output_data.get("asset_directory")
        asset_dir = cls._coerce_path(
            asset_value, allow_relative=allow_relative
        )

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

        obsidian_cfg = None
        if output_provider == "obsidian":
            obsidian_data = output_data.get("obsidian", {})
            repository_path = cls._coerce_path(
                obsidian_data.get("repository_path")
            )
            if repository_path is None:
                raise ValueError(
                    "output.obsidian.repository_path is required when configuring Obsidian output"
                )
            repository_url = obsidian_data.get("repository_url")
            if not repository_url:
                raise ValueError(
                    "output.obsidian.repository_url is required when configuring Obsidian output"
                )
            private_key_path = cls._coerce_path(
                obsidian_data.get("private_key_path")
            )
            known_hosts_path = cls._coerce_path(
                obsidian_data.get("known_hosts_path")
            )
            media_mode = obsidian_data.get("media_mode", "pdf").lower()
            if media_mode == "jpeg":
                media_mode = "jpg"
            if media_mode not in {"pdf", "png", "jpg"}:
                raise ValueError(
                    "output.obsidian.media_mode must be one of 'pdf', 'png', or 'jpg'"
                )
            media_invert = bool(obsidian_data.get("media_invert", False))
            if media_invert and media_mode not in {"png", "jpg"}:
                raise ValueError(
                    "output.obsidian.media_invert is only supported when media_mode is 'png' or 'jpg'"
                )
            obsidian_cfg = ObsidianOutputConfig(
                repository_path=repository_path,
                repository_url=str(repository_url),
                branch=obsidian_data.get("branch", "main"),
                remote=obsidian_data.get("remote", "origin"),
                commit_message_template=obsidian_data.get(
                    "commit_message_template",
                    "A new file from you has been added: {markdown_path}",
                ),
                push=bool(obsidian_data.get("push", True)),
                private_key_path=private_key_path,
                known_hosts_path=known_hosts_path,
                media_mode=media_mode,  # type: ignore[arg-type]
                media_invert=media_invert,
            )

        if asset_dir is None and output_provider == "obsidian":
            asset_dir = Path("media")

        output = OutputConfig(
            directory=output_dir,
            asset_directory=asset_dir,
            provider=output_provider,
            git=git_cfg,
            obsidian=obsidian_cfg,
        )

        state_path = cls._coerce_path(data["state"]["path"])
        state = StateConfig(path=state_path)

        llm_data = data.get("llm", {})
        llm = LLMConfig(
            provider=llm_data.get("provider", "simple"),
            model=llm_data.get("model"),
            endpoint=llm_data.get("endpoint"),
            api_key=cls._expand_env(llm_data.get("api_key")),
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
    "ObsidianOutputConfig",
    "OutputConfig",
    "StateConfig",
    "load_config",
]
