from __future__ import annotations

import os

from yandex_oauth import CredentialStore, dotenv

from .conftest import PROFILE


def test_dotenv_load_marks_only_new_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=2\n")
    monkeypatch.setenv("A", "preset")
    assert dotenv.load(env_file) == env_file
    assert dotenv.KEYS == {"B"}
    assert os.environ["A"] == "preset" and os.environ["B"] == "2"
    assert dotenv.provided("B") and not dotenv.provided("A")


def test_dotenv_load_missing(tmp_path):
    assert dotenv.load(tmp_path / "nope") is None
    assert dotenv.load(None) is None
    assert dotenv.PATH is None


def test_update_line_replaces_via_symlink_and_appends(tmp_path):
    real = tmp_path / ".env.shared"
    real.write_text("OTHER=1\nYANDEX_DEMO_TOKEN=stale\nZ=3")
    link = tmp_path / ".env"
    link.symlink_to(real)
    assert dotenv.update_line(link, "YANDEX_DEMO_TOKEN", "fresh") == real
    assert real.read_text() == "OTHER=1\nYANDEX_DEMO_TOKEN=fresh\nZ=3"
    dotenv.update_line(link, "NEW_KEY", "v")
    assert real.read_text() == "OTHER=1\nYANDEX_DEMO_TOKEN=fresh\nZ=3\nNEW_KEY=v\n"


def test_credential_store_names_and_round_trip(fake_keyring, monkeypatch):
    creds = CredentialStore(PROFILE)
    assert creds.service_name("yandex") == "demo:yandex"
    assert creds.env_var_name("yandex", "token") == "DEMO_YANDEX_TOKEN"
    creds.store_credential("yandex", {"token": "t", "client_id": "c"})
    assert fake_keyring[("demo:yandex", "yandex")] == '{"token": "t", "client_id": "c"}'
    monkeypatch.setenv("DEMO_YANDEX_TOKEN", "env-t")
    assert creds.get_credential("yandex") == {"token": "env-t", "client_id": "c"}
    assert creds.get_secret("yandex", "token") == "env-t"
    creds.delete_credential("yandex")
    creds.delete_credential("yandex")  # повторное удаление — не ошибка
    assert ("demo:yandex", "yandex") not in fake_keyring
