"""Tests for constructing the Google Drive connector."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from ink2md.config import AppConfig
from ink2md.connectors.google_drive import GoogleDriveConnector
from ink2md.processor import build_connector
from ink2md.processor import build_llm_client


def _base_app_config(tmp_path: Path) -> dict:
    return {
        "provider": "google_drive",
        "poll_interval": 30,
        "output": {"directory": str(tmp_path / "output")},
        "state": {"path": str(tmp_path / "state.json")},
        "llm": {"provider": "simple"},
    }


def _install_oauth_modules(
    monkeypatch: pytest.MonkeyPatch,
    credentials_cls: type,
    flow_cls: type,
    build_func,
) -> None:
    google_module = types.ModuleType("google")
    google_module.__path__ = []

    oauth2_module = types.ModuleType("google.oauth2")
    oauth2_module.__path__ = []
    credentials_module = types.ModuleType("google.oauth2.credentials")
    credentials_module.__path__ = []
    credentials_module.Credentials = credentials_cls
    oauth2_module.credentials = credentials_module

    auth_module = types.ModuleType("google.auth")
    auth_module.__path__ = []
    transport_module = types.ModuleType("google.auth.transport")
    transport_module.__path__ = []
    requests_module = types.ModuleType("google.auth.transport.requests")
    requests_module.__path__ = []

    class _Request:  # pragma: no cover - placeholder used for typing
        pass

    requests_module.Request = _Request
    transport_module.requests = requests_module

    google_auth_oauthlib_module = types.ModuleType("google_auth_oauthlib")
    google_auth_oauthlib_module.__path__ = []
    flow_module = types.ModuleType("google_auth_oauthlib.flow")
    flow_module.__path__ = []
    flow_module.InstalledAppFlow = flow_cls

    googleapiclient_module = types.ModuleType("googleapiclient")
    googleapiclient_module.__path__ = []
    discovery_module = types.ModuleType("googleapiclient.discovery")
    discovery_module.__path__ = []
    discovery_module.build = build_func

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_module)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_module)
    monkeypatch.setitem(sys.modules, "google.auth", auth_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", google_auth_oauthlib_module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)
    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery_module)


def test_build_connector_oauth_uses_existing_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DummyCredentials:
        from_file_calls: list[tuple[str, tuple[str, ...]]] = []

        def __init__(
            self,
            valid: bool = True,
            expired: bool = False,
            refresh_token: str | None = None,
            token_json: str = "{\"token\": \"cached\"}",
        ) -> None:
            self.valid = valid
            self.expired = expired
            self.refresh_token = refresh_token
            self._token_json = token_json
            self.refresh_invocations = 0

        @classmethod
        def from_authorized_user_file(cls, filename: str, scopes: list[str]):
            cls.from_file_calls.append((filename, tuple(scopes)))
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            return cls(
                valid=data.get("valid", True),
                expired=data.get("expired", False),
                refresh_token=data.get("refresh_token"),
                token_json=data.get("token_json", "{\"token\": \"cached\"}"),
            )

        def refresh(self, request):  # pragma: no cover - not triggered here
            self.refresh_invocations += 1
            self.valid = True
            self.expired = False

        def to_json(self) -> str:
            return self._token_json

    class DummyInstalledAppFlow:
        from_file_calls: list[tuple[str, tuple[str, ...]]] = []
        run_calls = 0

        @classmethod
        def from_client_secrets_file(cls, filename: str, scopes: list[str]):
            cls.from_file_calls.append((filename, tuple(scopes)))
            return cls()

        def run_local_server(self, port: int = 0):  # pragma: no cover - not triggered here
            type(self).run_calls += 1
            return DummyCredentials()

    def fake_build(service_name: str, version: str, credentials):
        fake_build.calls.append((service_name, version, credentials))
        return object()

    fake_build.calls = []  # type: ignore[attr-defined]

    _install_oauth_modules(monkeypatch, DummyCredentials, DummyInstalledAppFlow, fake_build)

    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"valid": True}), encoding="utf-8")

    config_dict = _base_app_config(tmp_path)
    config_dict["google_drive"] = {
        "folder_id": "folder-xyz",
        "oauth_client_secrets_file": str(client_secrets),
        "oauth_token_file": str(token_file),
    }

    connector = build_connector(AppConfig.from_dict(config_dict))

    assert isinstance(connector, GoogleDriveConnector)
    assert DummyCredentials.from_file_calls == [
        (str(token_file.resolve()), ("https://www.googleapis.com/auth/drive.readonly",)),
    ]
    assert DummyInstalledAppFlow.from_file_calls == []
    assert fake_build.calls[0][2].refresh_invocations == 0


def test_build_connector_oauth_refreshes_expired_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DummyCredentials:
        from_file_calls: list[tuple[str, tuple[str, ...]]] = []

        def __init__(
            self,
            valid: bool = False,
            expired: bool = True,
            refresh_token: str | None = "refresh-token",
            token_json: str = "{\"token\": \"cached\"}",
        ) -> None:
            self.valid = valid
            self.expired = expired
            self.refresh_token = refresh_token
            self._token_json = token_json
            self.refresh_invocations = 0

        @classmethod
        def from_authorized_user_file(cls, filename: str, scopes: list[str]):
            cls.from_file_calls.append((filename, tuple(scopes)))
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            return cls(
                valid=data.get("valid", False),
                expired=data.get("expired", True),
                refresh_token=data.get("refresh_token", "refresh-token"),
                token_json=data.get("token_json", "{\"token\": \"cached\"}"),
            )

        def refresh(self, request):
            self.refresh_invocations += 1
            self.valid = True
            self.expired = False

        def to_json(self) -> str:
            return self._token_json

    class DummyInstalledAppFlow:
        from_file_calls: list[tuple[str, tuple[str, ...]]] = []
        run_calls = 0

        @classmethod
        def from_client_secrets_file(cls, filename: str, scopes: list[str]):  # pragma: no cover - not used
            cls.from_file_calls.append((filename, tuple(scopes)))
            return cls()

        def run_local_server(self, port: int = 0):  # pragma: no cover - not used
            type(self).run_calls += 1
            return DummyCredentials(valid=True, expired=False)

    def fake_build(service_name: str, version: str, credentials):
        fake_build.calls.append((service_name, version, credentials))
        return object()

    fake_build.calls = []  # type: ignore[attr-defined]

    _install_oauth_modules(monkeypatch, DummyCredentials, DummyInstalledAppFlow, fake_build)

    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps({"valid": False, "expired": True, "refresh_token": "refresh-token"}),
        encoding="utf-8",
    )

    config_dict = _base_app_config(tmp_path)
    config_dict["google_drive"] = {
        "folder_id": "folder-refresh",
        "oauth_client_secrets_file": str(client_secrets),
        "oauth_token_file": str(token_file),
    }

    connector = build_connector(AppConfig.from_dict(config_dict))

    assert isinstance(connector, GoogleDriveConnector)
    assert DummyInstalledAppFlow.from_file_calls == []
    assert fake_build.calls[0][2].refresh_invocations == 1
    assert token_file.read_text(encoding="utf-8") == "{\"token\": \"cached\"}"


def test_build_connector_oauth_runs_flow_when_missing_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DummyCredentials:
        def __init__(self, token_json: str = "{\"token\": \"flow\"}") -> None:
            self.valid = True
            self.expired = False
            self.refresh_token = None
            self._token_json = token_json
            self.refresh_invocations = 0

        def refresh(self, request):  # pragma: no cover - not used
            raise AssertionError("refresh should not be called in flow path")

        def to_json(self) -> str:
            return self._token_json

    class DummyInstalledAppFlow:
        from_file_calls: list[tuple[str, tuple[str, ...]]] = []
        run_calls = 0

        @classmethod
        def from_client_secrets_file(cls, filename: str, scopes: list[str]):
            cls.from_file_calls.append((filename, tuple(scopes)))
            return cls()

        def run_local_server(self, port: int = 0, **kwargs):
            type(self).run_calls += 1
            return DummyCredentials()

    def fake_build(service_name: str, version: str, credentials):
        fake_build.calls.append((service_name, version, credentials))
        return object()

    fake_build.calls = []  # type: ignore[attr-defined]

    _install_oauth_modules(monkeypatch, DummyCredentials, DummyInstalledAppFlow, fake_build)

    client_secrets = tmp_path / "client.json"
    client_secrets.write_text("{}", encoding="utf-8")
    config_dict = _base_app_config(tmp_path)
    config_dict["google_drive"] = {
        "folder_id": "folder-flow",
        "oauth_client_secrets_file": str(client_secrets),
    }

    connector = build_connector(AppConfig.from_dict(config_dict))

    assert isinstance(connector, GoogleDriveConnector)
    assert DummyInstalledAppFlow.from_file_calls == [
        (str(client_secrets.resolve()), ("https://www.googleapis.com/auth/drive.readonly",)),
    ]
    assert DummyInstalledAppFlow.run_calls == 1
    token_file = client_secrets.with_name("client_token.json")
    assert token_file.exists()
    assert token_file.read_text(encoding="utf-8") == "{\"token\": \"flow\"}"


def test_build_llm_client_gemini(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ink2md.llm.gemini as gemini_module

    created_kwargs: dict[str, object] = {}

    class DummyGemini:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setattr(gemini_module, "GeminiLLMClient", DummyGemini)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Summarize", encoding="utf-8")

    config_data = _base_app_config(tmp_path)
    config_data["llm"] = {
        "provider": "gemini",
        "model": "models/gemini-2.5-flash",
        "api_key": "secret-key",
        "prompt_path": str(prompt_path),
        "temperature": 0.15,
    }

    config = AppConfig.from_dict(config_data)
    client = build_llm_client(config)

    assert isinstance(client, DummyGemini)
    assert created_kwargs["api_key"] == "secret-key"
    assert created_kwargs["model"] == "models/gemini-2.5-flash"
    assert created_kwargs["prompt"] == "Summarize"
    assert created_kwargs["temperature"] == 0.15
