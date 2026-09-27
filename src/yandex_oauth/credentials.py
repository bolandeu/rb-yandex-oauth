"""Учётные данные в keychain ОС + переменные окружения.

«Учётные данные» — небольшой словарь именованных полей, хранящийся одним
JSON-блобом на провайдера. Пространство имён общее для всех инструментов
(`Profile.keychain_namespace`, по умолчанию `yandex-oauth`): запись keychain
`yandex-oauth:<provider>`, переменные окружения `YANDEX_OAUTH_<PROVIDER>_<FIELD>`.
Переменные окружения переопределяют поля из keychain по одному — CI может
подменить ротированный токен, не трогая остальное.

Если keychain недоступен (Linux-сервер без Secret Service, контейнер), чтение
не падает: работаем только от переменных окружения, причина запоминается в
`unavailable_reason`. Падает только запись/удаление — сохранять некуда.
"""

from __future__ import annotations

import json
import logging
import os

import keyring
import keyring.errors

from .errors import CredentialStoreUnavailable
from .profile import Profile

log = logging.getLogger(__name__)


class CredentialStore:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        # Почему keychain не прочитался при последнем обращении (None — прочитался).
        self.unavailable_reason: str | None = None

    # --- имена ---------------------------------------------------------------

    @property
    def namespace(self) -> str:
        return self.profile.keychain_namespace

    def service_name(self, provider: str) -> str:
        return f"{self.namespace}:{provider}"

    def env_var_name(self, provider: str, field: str) -> str:
        prefix = self.namespace.upper().replace("-", "_")
        return f"{prefix}_{provider.upper()}_{field.upper()}"

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
            self.unavailable_reason = None
        except keyring.errors.KeyringError as exc:
            # Нет keychain — не повод падать: для этого и есть переменные окружения.
            if self.unavailable_reason is None:  # предупредить один раз, а не на каждое чтение
                log.warning("keychain недоступен (%s); учётные данные — только из переменных окружения", exc)
            self.unavailable_reason = str(exc) or type(exc).__name__
            stored_raw = None
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
