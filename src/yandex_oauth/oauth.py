"""OAuth Яндекса: ссылка на согласие, обмен кода на токен, обновление по refresh_token."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass

import httpx

from .errors import CliError

AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"  # noqa: S105 — URL, не пароль
NEW_APP_URL = "https://oauth.yandex.ru/client/new"

# OAuth-приложение одно на все Яндекс-инструменты — переменные без префикса CLI.
CLIENT_ID_ENV = "YANDEX_CLIENT_ID"
CLIENT_SECRET_ENV = "YANDEX_CLIENT_SECRET"  # noqa: S105 — имя env-переменной, не пароль


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None  # секунд с момента выдачи


def app_credentials_from_env() -> tuple[str | None, str | None]:
    return os.getenv(CLIENT_ID_ENV), os.getenv(CLIENT_SECRET_ENV)


def authorize_url(client_id: str) -> str:
    return f"{AUTHORIZE_URL}?response_type=code&client_id={client_id}"


def parse_manual_token(value: str) -> TokenSet:
    """Принять токен как есть или адрес вида …verification_code#access_token=…&expires_in=…

    Такой адрес выдаёт «ручной» способ (response_type=token) — без refresh_token,
    поэтому обновляться такой токен не сможет.
    """
    value = value.strip()
    if "#" not in value and "access_token=" not in value:
        return TokenSet(value)
    params = dict(urllib.parse.parse_qsl(value.split("#", 1)[-1]))
    if "error" in params:
        raise CliError("OAUTH_MANUAL_FAILED", f"Яндекс OAuth вернул ошибку: {params['error']}")
    expires = params.get("expires_in", "")
    return TokenSet(params.get("access_token", "").strip(), None, int(expires) if expires.isdigit() else None)


def _token_request(data: dict, *, code: str, action: str) -> TokenSet:
    try:
        resp = httpx.post(TOKEN_URL, data=data, timeout=30.0)
        resp.raise_for_status()
        body = resp.json()
        return TokenSet(body["access_token"], body.get("refresh_token"), body.get("expires_in"))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        detail = getattr(getattr(exc, "response", None), "text", "") or str(exc)
        raise CliError(code, f"Яндекс OAuth: {detail}", action=action) from exc


def exchange_code(code: str, client_id: str, client_secret: str) -> TokenSet:
    """Обменять код авторизации (из браузера) на набор токенов."""
    return _token_request(
        {"grant_type": "authorization_code", "code": code, "client_id": client_id, "client_secret": client_secret},
        code="OAUTH_EXCHANGE_FAILED",
        action="Проверьте код авторизации, client_id и client_secret приложения.",
    )


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> TokenSet:
    """Получить новый access-токен по refresh_token без участия пользователя."""
    return _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret},
        code="OAUTH_REFRESH_FAILED",
        action="Refresh-токен отозван или истёк — выполните 'auth login' заново.",
    )
