"""Контракт `<cli> auth status [--check] --json` (tools/docs/standard-release.md §8).

Два способа встроиться — оба дают одинаковые статусы у всех Яндекс-инструментов:

- инструмент по шаблону cli-generator: его `Provider.health_check()` делегирует сюда,
  а `source`/`required` запись отчёта добавляет сам CLI —

      def health_check(self) -> Health:
          return rb_yandex_oauth.health_check(token_store.store, check=lambda: self.get_json("/counters"))

  (`rb_yandex_oauth.Health` совпадает по полям с `providers.base.Health` шаблона);
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

import httpx
from rb_credentials.status import (
    Health,
    HealthStatus,
    Quota,  # noqa: F401 — public here since 0.1 (`rb_yandex_oauth.Quota`)
    entry,
    exit_code,
    iso,
    problems,
    report,
    scrub,
)

from . import oauth
from .errors import CliError
from .token import FIELDS, REFRESH_FIELDS, TokenStore

CHECK_TIMEOUT = 10.0  # §8: жёсткий лимит на проверку одного провайдера, без повторов
OK_STATUSES = ("ok", "unchecked")  # совместимость с 0.1.x
# Форма отчёта — одна на весь набор пакетов (rb-credentials, ADR 0017); ниже имена, которые зовут с 0.1.
status_report = report
status_problems = problems
status_exit_code = exit_code
# Заявленные поля провайдера, а не найденные: две машины обязаны давать одинаковый `fields`.
CREDENTIAL_FIELDS = ("token", *REFRESH_FIELDS)


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
        return Health(status="unreachable", message=f"No response within {timeout:g} s.")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _probe(store: TokenStore, check: Callable[[], object]) -> Health:
    env_token = store.env_token()
    bag = {} if env_token else store.current()
    secrets = [env_token, *(bag.get(f) for f in ("token", "refresh_token", "client_secret"))]
    exp = store.expires_at(bag)
    if store.is_expired(bag) and not store.can_refresh(bag):
        return Health(status="expired", expires_at=exp, message=f"Token expired — run '{store.profile.login_cmd}'.")
    try:
        if not env_token and store.env_only() and (not bag.get("token") or store.is_expired(bag)):
            bag = store.refresh()
            exp = store.expires_at(bag)
            secrets.append(bag.get("token"))
        check()
    except Exception as exc:
        return Health(status=_failure_status(exc), expires_at=exp, message=scrub(_message(exc), secrets))
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
    record = entry(store.profile.provider, required=required, fields=CREDENTIAL_FIELDS)
    env_token = store.env_token()
    bag = {} if env_token else store.current()
    env_mode = not env_token and store.env_only()
    keychain_ref = f"keychain service {store.credentials.service_name(store.profile.provider)}"

    if env_token:
        record.update(source="env", source_ref=store.profile.token_env)
    elif env_mode:
        refs = _env_refs(store)
        if refs:
            record.update(source="env", source_ref=", ".join(refs.values()))
    elif bag.get("token"):
        record.update(source="keychain")
        # Env-переменные перекрывают поля keychain по одному: побеждает env, в source_ref — все места.
        overridden = store.credentials.read_fields_from_env(store.profile.provider, FIELDS)
        if overridden:
            refs = ", ".join(store.env_var(f) for f in overridden)
            rest = f"; rest from {keychain_ref}" if set(bag) - set(overridden) else ""
            record.update(source="env", source_ref=refs + rest)
        else:
            record["source_ref"] = keychain_ref

    if record["source"] == "missing":
        env_refs = ", ".join(store.env_var(f) for f in REFRESH_FIELDS)
        record["source_ref"] = f"{store.profile.token_env} or {env_refs} or {keychain_ref}"
        reason = store.credentials.unavailable_reason
        record["message"] = (f"Keychain unavailable ({reason}). " if reason else "") + (
            f"No token: run '{store.profile.login_cmd}' or set {env_refs}."
        )
        return record
    if env_mode and (missing := store.missing_env(bag)):
        record.update(status="missing", message=f"Missing environment variables: {', '.join(missing)}.")
        return record

    record["expires_at"] = iso(store.expires_at(bag))
    if store.is_expired(bag) and not store.can_refresh(bag):
        record.update(status="expired", message=f"Token expired — run '{store.profile.login_cmd}'.")
        return record
    if not live:
        record["status"] = "unchecked"
        return record
    if check is None and not env_mode:
        record.update(status="unchecked", message="The tool set no API check.")
        return record

    health = health_check(store, check or (lambda: None))
    record.update(
        status=health.status,
        expires_at=iso(health.expires_at),
        quota=vars(health.quota) if health.quota else None,
        message=health.message,
    )
    return record


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
