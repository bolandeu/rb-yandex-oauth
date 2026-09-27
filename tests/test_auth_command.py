"""Команда auth: login/refresh/logout/status на нейтральном профиле."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

from yandex_oauth.errors import CliError
from yandex_oauth.oauth import TokenSet

from .conftest import KEY


def _json(result) -> dict:
    return json.loads(result.stdout)


class TestLogin:
    def test_with_token_stores_in_keychain(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["auth", "login", "--token", "abc", "--json"])
        assert result.exit_code == 0, result.stdout
        bag = json.loads(fake_keyring[KEY])
        assert bag["token"] == "abc" and "refresh_token" not in bag
        assert _json(runner.invoke(app, ["auth", "status", "--json"]))["source"] == "keychain"

    def test_global_token_option(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["--token", "glob", "auth", "login", "--json"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(fake_keyring[KEY])["token"] == "glob"

    def test_manual_url_parses_token_and_expiry(self, app, runner, fake_keyring):
        url = "https://oauth.yandex.ru/verification_code#access_token=y0_manual&expires_in=31536000&token_type=bearer"
        result = runner.invoke(app, ["auth", "login", "--token", url, "--json"])
        assert result.exit_code == 0, result.stdout
        bag = json.loads(fake_keyring[KEY])
        assert bag["token"] == "y0_manual" and "refresh_token" not in bag and bag["expires_at"]
        data = _json(result)
        assert data["refreshable"] is False and 360 <= data["days_left"] <= 365

    def test_manual_url_error(self, app, runner):
        result = runner.invoke(
            app,
            [
                "auth",
                "login",
                "--token",
                "https://oauth.yandex.ru/verification_code#error=unauthorized_client",
                "--json",
            ],
        )
        assert result.exit_code == 1
        assert _json(result)["error"]["code"] == "OAUTH_MANUAL_FAILED"

    def test_option_values_are_stripped(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["auth", "login", "--token", "  y0_tok\n", "--json"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(fake_keyring[KEY])["token"] == "y0_tok"

    def test_non_interactive_without_token_exit_2(self, app, runner):
        result = runner.invoke(app, ["auth", "login", "--non-interactive", "--json"])
        assert result.exit_code == 2

    def test_non_interactive_reads_env_token(self, app, runner, fake_keyring, monkeypatch):
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "from-env")
        result = runner.invoke(app, ["auth", "login", "--non-interactive"])
        assert result.exit_code == 0, result.stdout
        assert "from-env" in fake_keyring[KEY]

    def test_interactive_ignores_env_token_and_runs_oauth(self, app, runner, fake_keyring, monkeypatch):
        """Протухший токен в окружении/.env не должен подменять получение нового."""
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "stale")
        monkeypatch.setenv("YANDEX_CLIENT_ID", "cid")
        monkeypatch.setenv("YANDEX_CLIENT_SECRET", "sec")
        with (
            patch("yandex_oauth.auth_command.webbrowser.open") as browser,
            patch("yandex_oauth.oauth.exchange_code", return_value=TokenSet("fresh", "rt-1", 3600)) as exchange,
        ):
            result = runner.invoke(app, ["auth", "login", "--json"], input="the-code\n")
        assert result.exit_code == 0, result.stdout
        browser.assert_called_once()
        assert "client_id=cid" in browser.call_args[0][0]
        exchange.assert_called_once_with("the-code", "cid", "sec")
        bag = json.loads(fake_keyring[KEY])
        assert bag["token"] == "fresh" and bag["refresh_token"] == "rt-1"
        assert bag["client_id"] == "cid" and bag["client_secret"] == "sec" and bag["expires_at"]
        data = _json(result)
        assert data["method"] == "oauth" and data["refreshable"] is True and data["days_left"] == 0

    def test_explicit_client_creds_in_non_interactive_fail(self, app, runner):
        result = runner.invoke(
            app, ["auth", "login", "--client-id", "c", "--client-secret", "s", "--non-interactive", "--json"]
        )
        assert result.exit_code == 2

    def test_interactive_reuses_stored_client_creds(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "old", "client_id": "cid", "client_secret": "sec"})
        with (
            patch("yandex_oauth.auth_command.webbrowser.open"),
            patch("yandex_oauth.oauth.exchange_code", return_value=TokenSet("new", "rt", 100)) as exchange,
        ):
            result = runner.invoke(app, ["auth", "login"], input="code\n")
        assert result.exit_code == 0, result.stdout
        exchange.assert_called_once_with("code", "cid", "sec")

    def test_interactive_enter_then_token(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["auth", "login", "--json"], input="\npasted-token\n")
        assert result.exit_code == 0, result.stdout
        assert json.loads(fake_keyring[KEY])["token"] == "pasted-token"
        assert _json(result)["refreshable"] is False

    def test_ask_drops_broken_utf8_bytes(self, monkeypatch):
        from yandex_oauth.auth_command import _ask

        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"\xd12c8a9c2d\n"), encoding="utf-8"))
        assert _ask("Client ID") == "2c8a9c2d"


class TestRefreshLogoutStatus:
    def test_refresh_command(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "old", "refresh_token": "rt", "client_id": "c", "client_secret": "s"})
        with patch("yandex_oauth.oauth.refresh_access_token", return_value=TokenSet("new", "rt2", 86400 * 365)) as rf:
            result = runner.invoke(app, ["auth", "refresh", "--json"])
        assert result.exit_code == 0, result.stdout
        rf.assert_called_once_with("rt", "c", "s")
        assert json.loads(fake_keyring[KEY])["token"] == "new"
        assert _json(result)["days_left"] >= 364

    def test_refresh_without_refresh_token_fails(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "manual"})
        result = runner.invoke(app, ["auth", "refresh", "--json"])
        assert result.exit_code == 1
        assert _json(result)["error"]["code"] == "TOKEN_NOT_REFRESHABLE"

    def test_status_without_token(self, app, runner):
        data = _json(runner.invoke(app, ["auth", "status", "--json"]))
        assert data["authenticated"] is False and data["source"] is None

    def test_status_check_valid_and_invalid(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "t"})
        data = _json(runner.invoke(app, ["auth", "status", "--check", "--json"]))
        assert data["valid"] is True and data["refreshable"] is False
        app.checks["raise"] = CliError("API_ERROR", "403 invalid", exit_code=1)
        data = _json(runner.invoke(app, ["auth", "status", "--check", "--json"]))
        assert data["valid"] is False and data["error"] == "403 invalid"

    def test_logout(self, app, runner, fake_keyring):
        runner.invoke(app, ["auth", "login", "--token", "abc"])
        assert runner.invoke(app, ["auth", "logout"]).exit_code == 0
        assert KEY not in fake_keyring
