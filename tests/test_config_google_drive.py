"""Configuration validation for the Google Drive connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloud_monitor_pdf2md.config import AppConfig


def _base_config_dict(tmp_path: Path) -> dict:
    return {
        "provider": "google_drive",
        "poll_interval": 10,
        "output": {"directory": str(tmp_path / "output")},
        "state": {"path": str(tmp_path / "state.json")},
        "llm": {"provider": "simple"},
    }


def test_google_drive_config_requires_client_secret_path(tmp_path: Path) -> None:
    config_data = _base_config_dict(tmp_path)
    config_data["google_drive"] = {"folder_id": "folder-123"}

    with pytest.raises(ValueError):
        AppConfig.from_dict(config_data)


def test_google_drive_config_uses_default_token_path(tmp_path: Path) -> None:
    config_data = _base_config_dict(tmp_path)
    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")

    config_data["google_drive"] = {
        "folder_id": "folder-abc",
        "oauth_client_secrets_file": str(client_secrets),
    }

    app_config = AppConfig.from_dict(config_data)

    assert app_config.google_drive is not None
    assert app_config.google_drive.folder_id == "folder-abc"
    assert app_config.google_drive.oauth_client_secrets_file == client_secrets.resolve()
    expected_token = client_secrets.with_name("client_token.json").resolve()
    assert app_config.google_drive.oauth_token_file == expected_token
    assert app_config.google_drive.scopes == (
        "https://www.googleapis.com/auth/drive.readonly",
    )


def test_google_drive_config_respects_token_override(tmp_path: Path) -> None:
    config_data = _base_config_dict(tmp_path)
    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "custom_token.json"

    config_data["google_drive"] = {
        "folder_id": "folder-custom",
        "oauth_client_secrets_file": str(client_secrets),
        "oauth_token_file": str(token_file),
    }

    app_config = AppConfig.from_dict(config_data)

    assert app_config.google_drive is not None
    assert app_config.google_drive.oauth_token_file == token_file.resolve()


def test_google_drive_config_allows_scope_overrides(tmp_path: Path) -> None:
    config_data = _base_config_dict(tmp_path)
    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"

    config_data["google_drive"] = {
        "folder_id": "folder-scoped",
        "oauth_client_secrets_file": str(client_secrets),
        "scopes": [
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    }

    # Provide an explicit token override to ensure custom scopes play nicely together.
    config_data["google_drive"]["oauth_token_file"] = str(token_file)

    app_config = AppConfig.from_dict(config_data)

    assert app_config.google_drive is not None
    assert app_config.google_drive.scopes == (
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    )
