"""Жизненный цикл OAuth-токена: где лежит, не истекает ли, как обновить и сохранить.

В keychain под провайдером `yandex` хранится набор полей:
token, refresh_token, issued_at, expires_at (ISO-8601 UTC), client_id, client_secret.
Обновление возможно, только если есть refresh_token + client_id + client_secret
(т.е. токен получен через `<cli> auth login` OAuth-потоком, а не вставлен вручную).
Любое поле переопределяется переменной окружения `YANDEX_OAUTH_YANDEX_<FIELD>`.

Режим «только env» (сервер без keychain, `doppler run`): задан
`YANDEX_OAUTH_YANDEX_REFRESH_TOKEN` или keychain недоступен. Тогда keychain не
читается и не пишется: access-токен получается по refresh_token при первом
обращении и обновляется только в памяти процесса.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from . import oauth
from .credentials import CredentialStore
from .errors import CliError, CredentialsIncomplete
from .profile import Profile

FIELDS = ["token", "refresh_token", "issued_at", "expires_at", "client_id", "client_secret"]
REFRESH_FIELDS = ("refresh_token", "client_id", "client_secret")
REFRESH_BEFORE = timedelta(days=30)  # обновлять заранее: refresh_token живёт столько же, сколько access-токен
REFRESH_AFTER = timedelta(days=90)  # и не реже раза в 3 месяца — рекомендация Яндекса для долгоживущих токенов

# Так разные API Яндекса сообщают о протухшем токене:
# Вебмастер — {"error_code":"INVALID_OAUTH_TOKEN"}, Метрика — "invalid_token" / "Invalid oauth_token".
INVALID_TOKEN_RE = re.compile(r"invalid[_ ]?oauth[_ ]?token|invalid_token", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


class TokenStore:
    def __init__(self, profile: Profile, credentials: CredentialStore) -> None:
        self.profile = profile
        self.credentials = credentials
        self._memory: dict[str, str] | None = None  # токен, полученный в режиме «только env»

    # --- где лежит ---------------------------------------------------------------

    def env_var(self, field: str) -> str:
        """Имя переменной окружения поля: YANDEX_OAUTH_YANDEX_<FIELD>."""
        return self.credentials.env_var_name(self.profile.provider, field)

    def stored(self) -> dict[str, str]:
        """Набор полей: keychain, поверх — env YANDEX_OAUTH_YANDEX_<FIELD> по одному полю.

        Если в env задан refresh_token — keychain не читается вовсе (режим «только env»).
        В этом режиме client_id/client_secret можно взять и из legacy
        YANDEX_CLIENT_ID/YANDEX_CLIENT_SECRET.
        """
        if os.getenv(self.env_var("refresh_token")):
            bag = self.credentials.read_fields_from_env(self.profile.provider, FIELDS)
        else:
            bag = self.credentials.get_credential(self.profile.provider, env_fields=FIELDS) or {}
        if self.env_only():
            env_cid, env_secret = oauth.app_credentials_from_env()
            if env_cid and not bag.get("client_id"):
                bag["client_id"] = env_cid
            if env_secret and not bag.get("client_secret"):
                bag["client_secret"] = env_secret
        return bag

    def env_only(self) -> bool:
        """Режим «только env»: refresh_token задан в окружении или keychain недоступен."""
        return bool(os.getenv(self.env_var("refresh_token"))) or self.credentials.unavailable_reason is not None

    def current(self) -> dict[str, str]:
        """Токен из памяти процесса (режим «только env»), иначе — stored()."""
        return self._memory if self._memory is not None else self.stored()

    def env_token(self) -> str | None:
        return os.getenv(self.profile.token_env)

    def source(self, explicit: str | None = None) -> str | None:
        """Откуда сейчас берётся токен: 'argument' | 'env' | 'keychain' | None (без сети)."""
        if explicit:
            return "argument"
        if self.env_token():
            return "env"
        bag = self.current()
        if self.env_only():
            return "env" if bag.get("token") or self.can_refresh(bag) else None
        return "keychain" if bag.get("token") else None

    def missing_env(self, bag: dict) -> list[str]:
        """Каких переменных не хватает для получения токена из env (пусто — всё есть или env не используется)."""
        if bag.get("token") or not any(bag.get(f) for f in REFRESH_FIELDS):
            return []
        return [self.env_var(f) for f in REFRESH_FIELDS if not bag.get(f)]

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
        bag = self._make_bag(token_set, client_id, client_secret)
        self.credentials.store_credential(self.profile.provider, bag)
        return bag

    @staticmethod
    def _make_bag(token_set: oauth.TokenSet, client_id: str | None, client_secret: str | None) -> dict[str, str]:
        now = _now()
        bag: dict[str, str] = {"token": token_set.access_token, "issued_at": now.isoformat()}
        if token_set.refresh_token:
            bag["refresh_token"] = token_set.refresh_token
        if token_set.expires_in:
            bag["expires_at"] = (now + timedelta(seconds=token_set.expires_in)).isoformat()
        if client_id and client_secret:
            bag["client_id"] = client_id
            bag["client_secret"] = client_secret
        return bag

    def refresh(self) -> dict:
        """Обновить токен по refresh_token: в keychain, а в режиме «только env» — в памяти процесса."""
        bag = self.current()
        if self.env_only() and not self.can_refresh(bag):
            raise CredentialsIncomplete(self.profile, [self.env_var(f) for f in REFRESH_FIELDS if not bag.get(f)])
        if not self.can_refresh(bag):
            raise CliError(
                "TOKEN_NOT_REFRESHABLE",
                "В keychain нет refresh_token / client_id / client_secret — автообновление невозможно.",
                action=f"Выполните '{self.profile.login_cmd}' OAuth-потоком (с client_id и client_secret), а не с --token.",
            )
        token_set = oauth.refresh_access_token(bag["refresh_token"], bag["client_id"], bag["client_secret"])
        if not self.env_only():
            return self.store_token_set(token_set, bag["client_id"], bag["client_secret"])
        fresh = self._make_bag(token_set, bag["client_id"], bag["client_secret"])
        fresh.setdefault("refresh_token", bag["refresh_token"])  # Яндекс не всегда выдаёт новый
        self._memory = fresh
        return fresh

    def delete(self) -> None:
        self._memory = None
        self.credentials.delete_credential(self.profile.provider)

    # --- для клиента API ---------------------------------------------------------------

    def resolve(self, explicit: str | None = None) -> tuple[str | None, bool]:
        """(токен, можно ли обновлять). Порядок: аргумент → env → keychain.

        Keychain общий для всех инструментов (один вход — все инструменты).
        Токен из keychain обновляется заранее (истекает в ближайшие 30 дней или
        старше 90 дней). Если обновить не удалось, а токен ещё жив — используем старый.
        В режиме «только env» токена нет, пока его не получили по refresh_token
        из окружения — это делается здесь же, при первом обращении.
        """
        if explicit:
            return explicit, False
        env_token = self.env_token()
        if env_token:
            return env_token, False
        bag = self.current()
        if not bag.get("token"):
            if not self.env_only():
                return None, False
            if missing := self.missing_env(bag):
                raise CredentialsIncomplete(self.profile, missing)
            if not self.can_refresh(bag):
                return None, False
            return self.refresh()["token"], True
        # Токен в памяти только что получен — обновляем его, лишь когда истёк
        # (проактивное «за 30 дней» — для keychain, иначе каждый вызов шёл бы в сеть).
        due = self.is_expired(bag) if self._memory is not None else self.needs_refresh(bag)
        if due and self.can_refresh(bag):
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
