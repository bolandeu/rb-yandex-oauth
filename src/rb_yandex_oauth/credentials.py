"""Учётные данные в keychain ОС + переменные окружения — через общий `rb-credentials`.

Хранилище — `rb_credentials.Store` с неймспейсом профиля (`yandex-oauth` по умолчанию): запись keychain
`yandex-oauth:<provider>`, переменные окружения `YANDEX_OAUTH_<PROVIDER>_<FIELD>`, которые переопределяют поля
из keychain по одному. Здесь остаётся только то, что принадлежит этому пакету: неймспейс из профиля и маппинг
ошибок на `CredentialStoreUnavailable`.

Если keychain недоступен (Linux-сервер без Secret Service, контейнер), чтение не падает: работаем от переменных
окружения, причина видна в `unavailable_reason`. Падает только запись/удаление — сохранять некуда.
"""

from __future__ import annotations

import keyring  # noqa: F401 — реэкспорт: тесты подменяют `rb_yandex_oauth.credentials.keyring.*`
from rb_credentials import Store, StoreUnavailable

from .errors import CredentialStoreUnavailable
from .profile import Profile


class CredentialStore:
    """Учётные данные одного профиля: общий store плюс ошибки этого пакета."""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._store = Store(profile.keychain_namespace)

    # --- имена ---------------------------------------------------------------

    @property
    def namespace(self) -> str:
        return self.profile.keychain_namespace

    @property
    def unavailable_reason(self) -> str | None:
        """Почему keychain не прочитался при последнем обращении (None — прочитался)."""
        return self._store.unavailable_reason

    def service_name(self, provider: str) -> str:
        return self._store.service_name(provider)

    def env_var_name(self, provider: str, field: str) -> str:
        return self._store.env_var_name(provider, field)

    # --- набор полей -----------------------------------------------------------

    def read_fields_from_env(self, provider: str, fields: list[str]) -> dict[str, str]:
        return self._store.read_from_env(provider, fields)

    def get_credential(self, provider: str, *, env_fields: list[str] | None = None) -> dict[str, str] | None:
        return self._store.get(provider, env_fields=env_fields)

    def store_credential(self, provider: str, fields: dict[str, str]) -> None:
        try:
            self._store.store(provider, fields)
        except StoreUnavailable as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    def delete_credential(self, provider: str) -> None:
        try:
            self._store.delete(provider)
        except StoreUnavailable as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    # --- обёртки для одного секрета --------------------------------------------

    def get_secret(self, provider: str, field: str = "api_key") -> str | None:
        return self._store.get_secret(provider, field)

    def store_secret(self, provider: str, secret: str, field: str = "api_key") -> None:
        try:
            self._store.store_secret(provider, secret, field)
        except StoreUnavailable as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    def read_secret_from_env(self, provider: str, field: str = "api_key") -> str | None:
        return self._store.read_secret_from_env(provider, field)

    def delete_secret(self, provider: str) -> None:
        self.delete_credential(provider)
