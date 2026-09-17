"""Учётные данные в keychain ОС + переменные окружения.

«Учётные данные» — небольшой словарь именованных полей, хранящийся одним
JSON-блобом на провайдера. Пространство имён — имя CLI из профиля:
запись keychain `<cli>:<provider>`, переменные окружения `<CLI>_<PROVIDER>_<FIELD>`
(например YM_YANDEX_TOKEN). Переменные окружения переопределяют поля из
keychain по одному — CI может подменить ротированный токен, не трогая остальное.
"""

from __future__ import annotations

import json
import os

import keyring
import keyring.errors

from .errors import CredentialStoreUnavailable
from .profile import Profile


class CredentialStore:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile

    # --- имена ---------------------------------------------------------------

    def service_name(self, provider: str) -> str:
        return f"{self.profile.cli_name}:{provider}"

    def env_var_name(self, provider: str, field: str) -> str:
        return f"{self.profile.cli_name.upper()}_{provider.upper()}_{field.upper()}"

    # --- набор полей -----------------------------------------------------------

    def read_fields_from_env(self, provider: str, fields: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for field in fields:
            value = os.environ.get(self.env_var_name(provider, field))
            if value is not None:
                result[field] = value
        return result

    def get_credential(self, provider: str, *, env_fields: list[str] | None = None) -> dict[str, str] | None:
        try:
            stored_raw = keyring.get_password(self.service_name(provider), provider)
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc
        stored: dict[str, str] = json.loads(stored_raw) if stored_raw else {}
        fields_to_check = env_fields or list(stored.keys()) or ["api_key"]
        merged = {**stored, **self.read_fields_from_env(provider, fields_to_check)}
        return merged or None

    def store_credential(self, provider: str, fields: dict[str, str]) -> None:
        try:
            keyring.set_password(self.service_name(provider), provider, json.dumps(fields))
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    def delete_credential(self, provider: str) -> None:
        try:
            keyring.delete_password(self.service_name(provider), provider)
        except keyring.errors.PasswordDeleteError:
            pass  # уже отсутствует — удаление не ошибка
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    # --- обёртки для одного секрета --------------------------------------------

    def get_secret(self, provider: str, field: str = "api_key") -> str | None:
        credential = self.get_credential(provider, env_fields=[field])
        return credential.get(field) if credential else None

    def store_secret(self, provider: str, secret: str, field: str = "api_key") -> None:
        self.store_credential(provider, {field: secret})

    def read_secret_from_env(self, provider: str, field: str = "api_key") -> str | None:
        return self.read_fields_from_env(provider, [field]).get(field)

    def delete_secret(self, provider: str) -> None:
        self.delete_credential(provider)
