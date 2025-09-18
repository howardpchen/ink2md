"""Configuration utilities for the Cloud Monitor PDF2MD project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(slots=True)
class GoogleDriveConfig:
    """Settings required to poll a Google Drive folder."""

    folder_id: str
    service_account_file: Optional[Path] = None
    delegated_user: Optional[str] = None
    page_size: int = 100


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
class OutputConfig:
    """Configuration for writing Markdown results."""

    directory: Path
    asset_directory: Optional[Path] = None


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

        output_dir = cls._coerce_path(data["output"]["directory"])
        asset_dir = cls._coerce_path(data["output"].get("asset_directory"))
        output = OutputConfig(directory=output_dir, asset_directory=asset_dir)

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
            google_drive_cfg = GoogleDriveConfig(
                folder_id=gd["folder_id"],
                service_account_file=cls._coerce_path(gd.get("service_account_file")),
                delegated_user=gd.get("delegated_user"),
                page_size=int(gd.get("page_size", 100)),
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
    "OutputConfig",
    "StateConfig",
    "load_config",
]
