"""Контракт `<cli> auth status [--check] --json` (tools/docs/standard-release.md §8).

Два способа встроиться — оба дают одинаковые статусы у всех Яндекс-инструментов:

- инструмент по шаблону cli-generator: его `Provider.health_check()` делегирует сюда,
  а `source`/`required` запись отчёта добавляет сам CLI —

      def health_check(self) -> Health:
          return yandex_oauth.health_check(token_store.store, check=lambda: self.get_json("/counters"))

  (`yandex_oauth.Health` совпадает по полям с `providers.base.Health` шаблона);
- инструмент на `make_auth_app`: команда `auth status` собирает весь отчёт из
  `credential_status` + `status_report`, а exit-код и ошибку `CREDENTIALS_UNHEALTHY` —
  из `status_exit_code` / `status_problems`.

Значения секретов в отчёт не попадают — только имена переменных и слота keychain;
сообщения ошибок от них очищаются.
"""

from __future__ import annotations

import concurrent.futures
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

from . import oauth
from .errors import CliError
from .token import FIELDS, REFRESH_FIELDS, TokenStore, _now

EXIT_OK = 0
EXIT_PROBLEM = 3
CHECK_TIMEOUT = 10.0  # §8: жёсткий лимит на проверку одного провайдера, без повторов
HEALTHY = frozenset({"ok", "unchecked"})
# Проблема даже для необязательного провайдера: учётные данные есть, но негодные.
ALWAYS_PROBLEMS = frozenset({"invalid", "expired"})
OK_STATUSES = ("ok", "unchecked")  # совместимость с 0.1.x

HealthStatus = Literal["ok", "invalid", "expired", "quota_exhausted", "unreachable"]


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    limit: int | None = None
    unit: str = "requests"


@dataclass(frozen=True)
class Health:
    """Итог живой проверки — поля как у `providers.base.Health` шаблона cli-generator."""

    status: HealthStatus = "ok"
    expires_at: datetime | None = None
    quota: Quota | None = None
    message: str | None = None


def health_check(
    store: TokenStore,
    check: Callable[[], object],
    *,
    timeout: float = CHECK_TIMEOUT,
) -> Health:
    """Живая проверка токена для `Provider.health_check()` инструмента: статус, срок, сообщение.

    check — самый дешёвый read-only запрос инструмента к API. В режиме «только env»
    перед ним токен получается по refresh_token (это заодно проверка refresh_token).
    Всё вместе ограничено `timeout` секундами. Ошибки → статус: CliError с exit_code 5,
    сетевая ошибка, HTTP 429/5xx, таймаут → `unreachable`; 401/403 и прочие CliError → `invalid`.
    Наличие токена (`missing`) решает вызывающий — сюда приходят, когда он есть.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_probe, store, check).result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return Health(status="unreachable", message=f"Нет ответа за {timeout:g} с.")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _probe(store: TokenStore, check: Callable[[], object]) -> Health:
    env_token = store.env_token()
    bag = {} if env_token else store.current()
    secrets = [env_token, *(bag.get(f) for f in ("token", "refresh_token", "client_secret"))]
    exp = store.expires_at(bag)
    if store.is_expired(bag) and not store.can_refresh(bag):
        return Health(status="expired", expires_at=exp, message=f"Токен истёк — выполните '{store.profile.login_cmd}'.")
    try:
        if not env_token and store.env_only() and (not bag.get("token") or store.is_expired(bag)):
            bag = store.refresh()
            exp = store.expires_at(bag)
            secrets.append(bag.get("token"))
        check()
    except Exception as exc:
        return Health(status=_failure_status(exc), expires_at=exp, message=_scrub(_message(exc), secrets))
    return Health(status="ok", expires_at=exp)


def _failure_status(exc: Exception) -> HealthStatus:
    cause = exc if isinstance(exc, httpx.HTTPError) else exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return "invalid" if cause.response.status_code in (401, 403) else "unreachable"
    if isinstance(cause, httpx.TransportError):
        return "unreachable"
    if isinstance(exc, CliError):
        return "unreachable" if exc.exit_code == 5 else "invalid"
    return "unreachable"


def _message(exc: Exception) -> str:
    return exc.message if isinstance(exc, CliError) else f"{type(exc).__name__}: {exc}"


def _scrub(message: str, secrets: list[str | None]) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if moment else None


def credential_status(
    store: TokenStore,
    *,
    live: bool = False,
    check: Callable[[], object] | None = None,
    required: bool = True,
) -> dict:
    """Один элемент `credentials` отчёта: откуда токен, срок, (под `live`) принимает ли его API.

    live  — флаг `--check`: без него только наличие (`unchecked`/`missing`/`expired`), без сети.
    check — запрос к API для `health_check`. Без него под `live` в режиме «только env»
            проверяется только получение токена по refresh_token, иначе — `unchecked`.
    """
    entry: dict = {
        "provider": store.profile.provider,
        "required": required,
        "fields": [],
        "source": "missing",
        "source_ref": None,
        "status": "missing",
        "expires_at": None,
        "quota": None,
        "message": None,
    }
    env_token = store.env_token()
    bag = {} if env_token else store.current()
    env_mode = not env_token and store.env_only()
    keychain_ref = f"keychain service {store.credentials.service_name(store.profile.provider)}"

    if env_token:
        entry.update(fields=["token"], source="env", source_ref=store.profile.token_env)
    elif env_mode:
        refs = _env_refs(store)
        if refs:
            entry.update(fields=list(refs), source="env", source_ref=", ".join(refs.values()))
    elif bag.get("token"):
        entry.update(fields=[f for f in ("token", *REFRESH_FIELDS) if bag.get(f)], source="keychain")
        # Env-переменные перекрывают поля keychain по одному: побеждает env, в source_ref — все места.
        overridden = store.credentials.read_fields_from_env(store.profile.provider, FIELDS)
        if overridden:
            refs = ", ".join(store.env_var(f) for f in overridden)
            rest = f"; rest from {keychain_ref}" if set(bag) - set(overridden) else ""
            entry.update(source="env", source_ref=refs + rest)
        else:
            entry["source_ref"] = keychain_ref

    if entry["source"] == "missing":
        env_refs = ", ".join(store.env_var(f) for f in REFRESH_FIELDS)
        entry["source_ref"] = f"{store.profile.token_env} or {env_refs} or {keychain_ref}"
        reason = store.credentials.unavailable_reason
        entry["message"] = (f"Keychain недоступен ({reason}). " if reason else "") + (
            f"Нет токена: выполните '{store.profile.login_cmd}' или задайте {env_refs}."
        )
        return entry
    if env_mode and (missing := store.missing_env(bag)):
        entry.update(status="missing", message=f"Не хватает переменных окружения: {', '.join(missing)}.")
        return entry

    entry["expires_at"] = _iso(store.expires_at(bag))
    if store.is_expired(bag) and not store.can_refresh(bag):
        entry.update(status="expired", message=f"Токен истёк — выполните '{store.profile.login_cmd}'.")
        return entry
    if not live:
        entry["status"] = "unchecked"
        return entry
    if check is None and not env_mode:
        entry.update(status="unchecked", message="Инструмент не задал проверочного запроса к API.")
        return entry

    health = health_check(store, check or (lambda: None))
    entry.update(
        status=health.status,
        expires_at=_iso(health.expires_at),
        quota=vars(health.quota) if health.quota else None,
        message=health.message,
    )
    return entry


def status_report(tool: str, version: str, credentials: list[dict]) -> dict:
    """Весь отчёт `auth status` по §8: инструмент, версия, время проверки, список учётных данных.

    Конверт (`ok`, а при exit 3 — ещё `error` CREDENTIALS_UNHEALTHY) добавляет команда.
    """
    return {
        "tool": tool,
        "version": version,
        "checked_at": _iso(_now()),
        "credentials": credentials,
    }


def is_problem(entry: dict) -> bool:
    """Запись валит `auth status`: invalid/expired — всегда, прочее не ok/unchecked — если провайдер обязателен."""
    if entry["status"] in ALWAYS_PROBLEMS:
        return True
    return entry["required"] and entry["status"] not in HEALTHY


def status_problems(report: dict) -> dict[str, str]:
    """Провайдер → статус для всех проблемных записей (для ошибки CREDENTIALS_UNHEALTHY)."""
    return {entry["provider"]: entry["status"] for entry in report["credentials"] if is_problem(entry)}


def status_exit_code(report: dict) -> int:
    """0 — нет проблемных записей (см. `is_problem`), иначе 3."""
    return EXIT_PROBLEM if status_problems(report) else EXIT_OK


def _env_refs(store: TokenStore) -> dict[str, str]:
    """Поле → имя переменной окружения, из которой оно реально взято (значения не читаем в отчёт)."""
    legacy = {"client_id": oauth.CLIENT_ID_ENV, "client_secret": oauth.CLIENT_SECRET_ENV}
    refs: dict[str, str] = {}
    for field in ("token", *REFRESH_FIELDS):
        if os.getenv(store.env_var(field)):
            refs[field] = store.env_var(field)
        elif field in legacy and os.getenv(legacy[field]):
            refs[field] = legacy[field]
    return refs
