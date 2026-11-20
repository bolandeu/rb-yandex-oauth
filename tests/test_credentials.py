from __future__ import annotations

from rb_yandex_oauth import CredentialStore

from .conftest import PROFILE


def test_credential_store_names_and_round_trip(fake_keyring, monkeypatch):
    creds = CredentialStore(PROFILE)
    assert creds.service_name("yandex") == "yandex-oauth:yandex"
    assert creds.env_var_name("yandex", "token") == "YANDEX_OAUTH_YANDEX_TOKEN"
    creds.store_credential("yandex", {"token": "t", "client_id": "c"})
    assert fake_keyring[("yandex-oauth:yandex", "yandex")] == '{"token": "t", "client_id": "c"}'
    monkeypatch.setenv("YANDEX_OAUTH_YANDEX_TOKEN", "env-t")
    assert creds.get_credential("yandex") == {"token": "env-t", "client_id": "c"}
    assert creds.get_secret("yandex", "token") == "env-t"
    creds.delete_credential("yandex")
    creds.delete_credential("yandex")  # повторное удаление — не ошибка
    assert ("yandex-oauth:yandex", "yandex") not in fake_keyring
