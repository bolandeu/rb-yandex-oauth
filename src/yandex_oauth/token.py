"""Жизненный цикл OAuth-токена: где лежит, не истекает ли, как обновить и сохранить.

В keychain под провайдером `yandex` хранится набор полей:
token, refresh_token, issued_at, expires_at (ISO-8601 UTC), client_id, client_secret.
Обновление возможно, только если есть refresh_token + client_id + client_secret
(т.е. токен получен через `<cli> auth login` OAuth-потоком, а не вставлен вручную).
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from . import oauth
from .credentials import CredentialStore
from .errors import CliError
from .profile import Profile

FIELDS = ["token", "refresh_token", "issued_at", "expires_at", "client_id", "client_secret"]
REFRESH_BEFORE = timedelta(days=30)  # обновлять заранее: refresh_token живёт столько же, сколько access-токен
REFRESH_AFTER = timedelta(days=90)   # и не реже раза в 3 месяца — рекомендация Яндекса для долгоживущих токенов

# Так разные API Яндекса сообщают о протухшем токене:
# Вебмастер — {"error_code":"INVALID_OAUTH_TOKEN"}, Метрика — "invalid_token" / "Invalid oauth_token".
INVALID_TOKEN_RE = re.compile(r"invalid[_ ]?oauth[_ ]?token|invalid_token", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


class TokenStore:
    def __init__(self, profile: Profile, credentials: CredentialStore) -> None:
        self.profile = profile
        self.credentials = credentials

    # --- где лежит ---------------------------------------------------------------

    def stored(self) -> dict[str, str]:
        """Набор полей из keychain (поля можно переопределить env <CLI>_YANDEX_<FIELD>)."""
        return self.credentials.get_credential(self.profile.provider, env_fields=FIELDS) or {}

    def env_token(self) -> str | None:
        return os.getenv(self.profile.token_env)

    def source(self, explicit: str | None = None) -> str | None:
        """Откуда сейчас берётся токен: 'argument' | 'env' | 'keychain' | None (без сети)."""
        if explicit:
            return "argument"
        if self.env_token():
            return "env"
        if self.stored().get("token"):
            return "keychain"
        return None

    # --- срок действия -------------------------------------------------------------

    @staticmethod
    def can_refresh(bag: dict) -> bool:
        return all(bag.get(k) for k in ("refresh_token", "client_id", "client_secret"))

    @staticmethod
    def expires_at(bag: dict) -> datetime | None:
        raw = bag.get("expires_at")
        return datetime.fromisoformat(raw) if raw else None

    def is_expired(self, bag: dict) -> bool:
        exp = self.expires_at(bag)
        return exp is not None and _now() >= exp

    def needs_refresh(self, bag: dict) -> bool:
        """Пора обновлять: до истечения < 30 дней или с выдачи прошло > 90 дней."""
        now = _now()
        exp = self.expires_at(bag)
        if exp is not None and now >= exp - REFRESH_BEFORE:
            return True
        issued = bag.get("issued_at")
        return bool(issued) and now >= datetime.fromisoformat(issued) + REFRESH_AFTER

    # --- запись и обновление ---------------------------------------------------------

    def store_token_set(self, token_set: oauth.TokenSet, client_id: str | None, client_secret: str | None) -> dict:
        now = _now()
        bag: dict[str, str] = {"token": token_set.access_token, "issued_at": now.isoformat()}
        if token_set.refresh_token:
            bag["refresh_token"] = token_set.refresh_token
        if token_set.expires_in:
            bag["expires_at"] = (now + timedelta(seconds=token_set.expires_in)).isoformat()
        if client_id and client_secret:
            bag["client_id"] = client_id
            bag["client_secret"] = client_secret
        self.credentials.store_credential(self.profile.provider, bag)
        return bag

    def refresh(self) -> dict:
        """Обновить токен по refresh_token и перезаписать keychain."""
        bag = self.stored()
        if not self.can_refresh(bag):
            raise CliError(
                "TOKEN_NOT_REFRESHABLE",
                "В keychain нет refresh_token / client_id / client_secret — автообновление невозможно.",
                action=f"Выполните '{self.profile.login_cmd}' OAuth-потоком (с client_id и client_secret), а не с --token.",
            )
        token_set = oauth.refresh_access_token(bag["refresh_token"], bag["client_id"], bag["client_secret"])
        return self.store_token_set(token_set, bag["client_id"], bag["client_secret"])

    def delete(self) -> None:
        self.credentials.delete_credential(self.profile.provider)

    # --- для клиента API ---------------------------------------------------------------

    def resolve(self, explicit: str | None = None) -> tuple[str | None, bool]:
        """(токен, можно ли обновлять). Порядок: аргумент → env → keychain.

        Keychain общий для всех инструментов (один вход — все инструменты).
        Токен из keychain обновляется заранее (истекает в ближайшие 30 дней или
        старше 90 дней). Если обновить не удалось, а токен ещё жив — используем старый.
        """
        if explicit:
            return explicit, False
        env_token = self.env_token()
        if env_token:
            return env_token, False
        bag = self.stored()
        if not bag.get("token"):
            return None, False
        if self.needs_refresh(bag) and self.can_refresh(bag):
            try:
                bag = self.refresh()
            except CliError:
                if self.is_expired(bag):
                    raise
        return bag["token"], self.can_refresh(bag)

    def retry_token_after(self, status_code: int, body: str | None) -> str | None:
        """Если API ответил «токен протух» — обновить и вернуть новый токен для повтора запроса.

        Вызывать один раз на запрос и только если `resolve()` вернул refreshable=True.
        """
        if status_code == 403 and INVALID_TOKEN_RE.search(body or ""):
            return self.refresh()["token"]
        return None
