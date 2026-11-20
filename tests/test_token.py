"""Жизненный цикл токена: проактивное и реактивное автообновление."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from rb_yandex_oauth import token as token_mod
from rb_yandex_oauth.errors import CliError
from rb_yandex_oauth.oauth import TokenSet

from .conftest import KEY


def _bag(
    fake_keyring,
    *,
    expires_in_days: float | None,
    refreshable: bool = True,
    token: str = "old",
    age_days: float | None = None,
) -> None:
    bag = {"token": token}
    if age_days is not None:
        bag["issued_at"] = (token_mod._now() - timedelta(days=age_days)).isoformat()
    if refreshable:
        bag.update(refresh_token="rt", client_id="c", client_secret="s")
    if expires_in_days is not None:
        bag["expires_at"] = (token_mod._now() + timedelta(days=expires_in_days)).isoformat()
    fake_keyring[KEY] = json.dumps(bag)


class TestResolve:
    def test_far_from_expiry_no_refresh(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=200)
        with patch("rb_yandex_oauth.oauth.refresh_access_token") as rf:
            tok, refreshable = store.resolve()
        assert tok == "old" and refreshable is True
        rf.assert_not_called()

    def test_expiring_soon_refreshes_and_stores(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=10)
        with patch("rb_yandex_oauth.oauth.refresh_access_token", return_value=TokenSet("new", "rt2", 3600)) as rf:
            tok, _ = store.resolve()
        assert tok == "new"
        rf.assert_called_once_with("rt", "c", "s")
        assert json.loads(fake_keyring[KEY])["refresh_token"] == "rt2"

    def test_older_than_90_days_refreshes_even_if_far_from_expiry(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=200, age_days=91)
        with patch("rb_yandex_oauth.oauth.refresh_access_token", return_value=TokenSet("new", "rt2", 3600)) as rf:
            tok, _ = store.resolve()
        assert tok == "new"
        rf.assert_called_once()

    def test_younger_than_90_days_no_refresh(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=200, age_days=89)
        with patch("rb_yandex_oauth.oauth.refresh_access_token") as rf:
            store.resolve()
        rf.assert_not_called()

    def test_refresh_failure_keeps_old_token_if_still_valid(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=10)
        with patch("rb_yandex_oauth.oauth.refresh_access_token", side_effect=CliError("OAUTH_REFRESH_FAILED", "down")):
            tok, _ = store.resolve()
        assert tok == "old"

    def test_refresh_failure_raises_if_expired(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=-1)
        with patch("rb_yandex_oauth.oauth.refresh_access_token", side_effect=CliError("OAUTH_REFRESH_FAILED", "down")):
            with pytest.raises(CliError, match="down"):
                store.resolve()

    def test_manual_token_never_refreshes(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=None, refreshable=False)
        assert store.resolve() == ("old", False)

    def test_env_wins_over_keychain(self, fake_keyring, store, monkeypatch):
        _bag(fake_keyring, expires_in_days=200)
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "env")
        assert store.resolve() == ("env", False)

    def test_explicit_wins_over_everything(self, fake_keyring, store, monkeypatch):
        _bag(fake_keyring, expires_in_days=200)
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "env")
        assert store.resolve("arg") == ("arg", False)

    def test_field_env_override(self, fake_keyring, store, monkeypatch):
        """YANDEX_OAUTH_YANDEX_TOKEN переопределяет поле token из общего keychain-набора."""
        _bag(fake_keyring, expires_in_days=None, refreshable=False)
        monkeypatch.setenv("YANDEX_OAUTH_YANDEX_TOKEN", "field-env")
        assert store.resolve() == ("field-env", False)

    def test_keychain_slot_is_shared_between_profiles(self, fake_keyring, store):
        """Один вход — все инструменты: другой профиль читает тот же слот."""
        from rb_yandex_oauth import CredentialStore, Profile, TokenStore

        _bag(fake_keyring, expires_in_days=200)
        other = Profile(cli_name="other", token_env="YANDEX_OTHER_TOKEN", scopes="x", service="Другой")
        assert TokenStore(other, CredentialStore(other)).resolve() == ("old", True)


class TestSource:
    def test_none(self, store):
        assert store.source() is None

    def test_argument_env_keychain(self, fake_keyring, store, monkeypatch):
        assert store.source("x") == "argument"
        fake_keyring[KEY] = json.dumps({"token": "kc"})
        assert store.source() == "keychain"
        monkeypatch.setenv("YANDEX_DEMO_TOKEN", "real")
        assert store.source() == "env"


class TestRetry:
    @pytest.mark.parametrize(
        "body",
        [
            '{"error_code":"INVALID_OAUTH_TOKEN"}',
            '{"errors":[{"error_type":"invalid_token","message":"Invalid oauth_token"}]}',
        ],
    )
    def test_invalid_token_bodies_trigger_refresh(self, fake_keyring, store, body):
        _bag(fake_keyring, expires_in_days=200)
        with patch("rb_yandex_oauth.oauth.refresh_access_token", return_value=TokenSet("new", "rt2", 3600)):
            assert store.retry_token_after(403, body) == "new"
        assert json.loads(fake_keyring[KEY])["token"] == "new"

    def test_other_403_not_retried(self, fake_keyring, store):
        _bag(fake_keyring, expires_in_days=200)
        with patch("rb_yandex_oauth.oauth.refresh_access_token") as rf:
            assert store.retry_token_after(403, "forbidden: no rights") is None
            assert store.retry_token_after(401, "INVALID_OAUTH_TOKEN") is None
        rf.assert_not_called()

    def test_refresh_without_refresh_token_fails(self, fake_keyring, store):
        fake_keyring[KEY] = json.dumps({"token": "manual"})
        with pytest.raises(CliError) as exc_info:
            store.refresh()
        assert exc_info.value.code == "TOKEN_NOT_REFRESHABLE"
        assert "demo auth login" in (exc_info.value.action or "")
