"""Режим «только env»: сервер без keychain, учётные данные из запуск с переменными окружения из секрет-менеджера."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from yandex_oauth import CredentialStore, credential_status, status_exit_code, status_report
from yandex_oauth.errors import CliError, CredentialStoreUnavailable
from yandex_oauth.oauth import TokenSet

from .conftest import KEY, PROFILE

REFRESH = "yandex_oauth.oauth.refresh_access_token"


class TestNoKeychain:
    def test_read_does_not_fail(self, no_keychain):
        creds = CredentialStore(PROFILE)
        assert creds.get_credential("yandex") is None
        assert "No recommended backend" in (creds.unavailable_reason or "")

    def test_write_still_fails(self, no_keychain):
        with pytest.raises(CredentialStoreUnavailable) as exc_info:
            CredentialStore(PROFILE).store_credential("yandex", {"token": "t"})
        assert "YANDEX_OAUTH_YANDEX_REFRESH_TOKEN" in (exc_info.value.action or "")

    def test_token_from_env_refresh(self, no_keychain, env_creds, store):
        with patch(REFRESH, return_value=TokenSet("fresh", None, 3600)) as refresh:
            assert store.resolve() == ("fresh", True)
            assert store.resolve() == ("fresh", True)  # второй раз — из памяти, без сети
        refresh.assert_called_once_with("rt-env", "cid-env", "sec-env")
        assert store.source() == "env"

    def test_retry_refreshes_in_memory(self, no_keychain, env_creds, store):
        with patch(REFRESH, side_effect=[TokenSet("a", "rt-2", 3600), TokenSet("b", None, 3600)]) as refresh:
            store.resolve()
            assert store.retry_token_after(403, '{"error_code":"INVALID_OAUTH_TOKEN"}') == "b"
        assert refresh.call_args.args == ("rt-2", "cid-env", "sec-env")  # новый refresh_token из памяти

    def test_legacy_client_vars(self, no_keychain, monkeypatch, store):
        monkeypatch.setenv("YANDEX_OAUTH_YANDEX_REFRESH_TOKEN", "rt-env")
        monkeypatch.setenv("YANDEX_CLIENT_ID", "cid-legacy")
        monkeypatch.setenv("YANDEX_CLIENT_SECRET", "sec-legacy")
        with patch(REFRESH, return_value=TokenSet("fresh")) as refresh:
            assert store.resolve() == ("fresh", True)
        refresh.assert_called_once_with("rt-env", "cid-legacy", "sec-legacy")

    def test_incomplete_env_names_missing_vars(self, no_keychain, monkeypatch, store):
        monkeypatch.setenv("YANDEX_OAUTH_YANDEX_REFRESH_TOKEN", "rt-env")
        with pytest.raises(CliError) as exc_info:
            store.resolve()
        err = exc_info.value
        assert err.code == "CREDENTIALS_INCOMPLETE" and err.exit_code == 3
        assert "YANDEX_OAUTH_YANDEX_CLIENT_ID" in err.message and "YANDEX_OAUTH_YANDEX_CLIENT_SECRET" in err.message
        with pytest.raises(CliError, match="CLIENT_ID"):
            store.refresh()

    def test_nothing_at_all_is_no_token(self, no_keychain, store):
        assert store.resolve() == (None, False)
        assert store.source() is None

    def test_env_token_still_wins(self, no_keychain, env_creds, monkeypatch, store):
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "ready")
        assert store.resolve() == ("ready", False)


class TestEnvRefreshWithKeychain:
    def test_env_refresh_token_ignores_keychain_and_writes_nothing(self, fake_keyring, env_creds, store):
        fake_keyring[KEY] = json.dumps({"token": "keychain-token"})
        with patch(REFRESH, return_value=TokenSet("fresh", "rt-new", 3600)):
            assert store.resolve() == ("fresh", True)
        assert json.loads(fake_keyring[KEY]) == {"token": "keychain-token"}

    def test_delete_forgets_memory(self, fake_keyring, env_creds, store):
        with patch(REFRESH, return_value=TokenSet("fresh")):
            store.resolve()
        store.delete()
        assert store._memory is None


class TestStatus:
    def test_keychain_unchecked(self, fake_keyring, store):
        fake_keyring[KEY] = json.dumps(
            {
                "token": "t",
                "refresh_token": "r",
                "client_id": "c",
                "client_secret": "s",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        )
        entry = credential_status(store)
        assert entry["source"] == "keychain" and entry["source_ref"] == "keychain service yandex-oauth:yandex"
        assert entry["status"] == "unchecked" and entry["expires_at"].startswith("2099")
        assert entry["fields"] == ["token", "refresh_token", "client_id", "client_secret"]

    def test_missing_without_keychain(self, no_keychain, store):
        entry = credential_status(store)
        assert entry["source"] == "missing" and entry["status"] == "missing"
        assert "Keychain unavailable" in entry["message"] and "YANDEX_OAUTH_YANDEX_REFRESH_TOKEN" in entry["message"]

    def test_env_presence_without_network(self, no_keychain, env_creds, store):
        with patch(REFRESH) as refresh:
            entry = credential_status(store)
        refresh.assert_not_called()
        assert entry["source"] == "env" and entry["status"] == "unchecked"
        assert entry["source_ref"] == (
            "YANDEX_OAUTH_YANDEX_REFRESH_TOKEN, YANDEX_OAUTH_YANDEX_CLIENT_ID, YANDEX_OAUTH_YANDEX_CLIENT_SECRET"
        )
        assert "rt-env" not in json.dumps(entry)  # значения секретов в отчёт не попадают

    def test_env_live_check(self, no_keychain, env_creds, store):
        calls = []
        with patch(REFRESH, return_value=TokenSet("fresh", None, 3600)):
            entry = credential_status(store, live=True, check=lambda: calls.append(store.resolve()))
        assert entry["status"] == "ok" and entry["expires_at"]
        assert calls == [("fresh", True)]

    def test_env_live_refresh_rejected(self, no_keychain, env_creds, store):
        with patch(REFRESH, side_effect=CliError("OAUTH_REFRESH_FAILED", "bad refresh")):
            entry = credential_status(store, live=True)
        assert entry["status"] == "invalid" and entry["message"] == "bad refresh"

    def test_unreachable_and_incomplete(self, no_keychain, monkeypatch, store):
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "ready")

        def down() -> None:
            raise CliError("PROVIDER_ERROR", "timeout", exit_code=5)

        assert credential_status(store, live=True, check=down)["status"] == "unreachable"
        monkeypatch.delenv("YANDEX_DEMO_TOKEN")
        monkeypatch.setenv("YANDEX_OAUTH_YANDEX_REFRESH_TOKEN", "rt")
        entry = credential_status(store)
        assert entry["status"] == "missing" and "CLIENT_SECRET" in entry["message"]

    def test_expired_and_keychain_live_without_check(self, fake_keyring, store):
        fake_keyring[KEY] = json.dumps({"token": "t", "expires_at": "2000-01-01T00:00:00+00:00"})
        assert credential_status(store)["status"] == "expired"
        fake_keyring[KEY] = json.dumps({"token": "t"})
        assert credential_status(store, live=True)["status"] == "unchecked"

    def test_report_shape_and_exit_code(self, fake_keyring, store):
        ok = credential_status(store, required=False)  # необязательный и отсутствует — не проблема
        report = status_report("demo", "1.2.3", [ok])
        assert list(report) == ["tool", "version", "checked_at", "credentials"]
        assert report["checked_at"].endswith("Z")
        assert list(ok) == [
            "provider",
            "required",
            "fields",
            "source",
            "source_ref",
            "status",
            "expires_at",
            "quota",
            "message",
        ]
        assert status_exit_code(report) == 0
        assert status_exit_code(status_report("demo", "1", [credential_status(store)])) == 3
