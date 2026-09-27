"""Тесты никогда не трогают настоящий keychain и не зависят от окружения разработчика."""

from __future__ import annotations

import os

import pytest
import typer
from typer.testing import CliRunner

from yandex_oauth import CredentialStore, Profile, TokenStore
from yandex_oauth.auth_command import make_auth_app

from . import fake_output

PROFILE = Profile(cli_name="demo", token_env="YANDEX_DEMO_TOKEN", scopes="demo:read", service="Демо")
KEY = ("yandex-oauth:yandex", "yandex")  # общий слот для всех инструментов


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_delete_password(service: str, username: str) -> None:
        store.pop((service, username), None)

    monkeypatch.setattr("yandex_oauth.credentials.keyring.set_password", fake_set_password)
    monkeypatch.setattr("yandex_oauth.credentials.keyring.get_password", fake_get_password)
    monkeypatch.setattr("yandex_oauth.credentials.keyring.delete_password", fake_delete_password)
    for var in list(os.environ):
        if var.startswith("YANDEX_"):
            monkeypatch.delenv(var)
    return store


@pytest.fixture
def store() -> TokenStore:
    return TokenStore(PROFILE, CredentialStore(PROFILE))


@pytest.fixture
def app(store: TokenStore):
    """Корневое приложение с глобальными опциями --json/--non-interactive/--token и sub-app auth."""
    checks: dict = {"raise": None}

    def check(ctx: typer.Context) -> None:
        if checks["raise"]:
            raise checks["raise"]

    root = typer.Typer()
    root.add_typer(make_auth_app(PROFILE, store, fake_output, check=check), name="auth")

    @root.callback()
    def main(
        ctx: typer.Context,
        token: str = typer.Option(None, "--token"),
        json_output: bool = typer.Option(False, "--json"),
        non_interactive: bool = typer.Option(False, "--non-interactive"),
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj.update({"token": token, "json": json_output, "non_interactive": non_interactive, "quiet": False})

    setattr(root, "checks", checks)  # атрибут, которого нет у Typer
    return root


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def no_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keychain недоступен, как на Linux-сервере без Secret Service: любое обращение бросает."""
    import keyring.errors

    def broken(*args, **kwargs):
        raise keyring.errors.NoKeyringError("No recommended backend was available.")

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(f"yandex_oauth.credentials.keyring.{name}", broken)


@pytest.fixture
def env_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_OAUTH_YANDEX_REFRESH_TOKEN", "rt-env")
    monkeypatch.setenv("YANDEX_OAUTH_YANDEX_CLIENT_ID", "cid-env")
    monkeypatch.setenv("YANDEX_OAUTH_YANDEX_CLIENT_SECRET", "sec-env")
