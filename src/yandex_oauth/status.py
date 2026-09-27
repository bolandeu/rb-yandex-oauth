"""Контракт `<cli> auth status [--check] --json` (tools/docs/standard-release.md §8).

Инструменты Яндекса собирают отчёт из этих функций, чтобы `tools-watch`
видел все их одинаково:

    entry = credential_status(store, live=check_flag, check=lambda: client.get_counters_sync())
    report = status_report("ym", version("rb-yandex-metrica"), [entry])
    raise SystemExit(status_exit_code(report))

Значения секретов в отчёт не попадают — только имена переменных и слота keychain.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx

from . import oauth
from .errors import CliError
from .token import REFRESH_FIELDS, TokenStore, _now

EXIT_OK = 0
EXIT_PROBLEM = 3
OK_STATUSES = ("ok", "unchecked")


def credential_status(
    store: TokenStore,
    *,
    live: bool = False,
    check: Callable[[], None] | None = None,
    required: bool = True,
) -> dict:
    """Один элемент `credentials` отчёта: откуда токен, срок, (под `live`) принимает ли его API.

    live  — флаг `--check`: без него только наличие (`unchecked`/`missing`), без сети.
    check — самый дешёвый read-only запрос инструмента к API (таймаут — его забота,
            §8 требует 10 с). Должен бросать CliError: exit_code 5 (сеть/5xx) →
            `unreachable`, остальное → `invalid`. В режиме «только env» перед ним
            токен получается по refresh_token — это уже проверка refresh_token.
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

    if env_token:
        entry.update(fields=["token"], source="env", source_ref=store.profile.token_env)
    elif env_mode:
        refs = _env_refs(store)
        if refs:
            entry.update(fields=list(refs), source="env", source_ref=", ".join(refs.values()))
    elif bag.get("token"):
        entry.update(
            fields=[f for f in ("token", *REFRESH_FIELDS) if bag.get(f)],
            source="keychain",
            source_ref=store.credentials.service_name(store.profile.provider),
        )

    if entry["source"] == "missing":
        reason = store.credentials.unavailable_reason
        entry["message"] = (f"Keychain недоступен ({reason}). " if reason else "") + (
            f"Нет токена: выполните '{store.profile.login_cmd}' или задайте "
            + ", ".join(store.env_var(f) for f in REFRESH_FIELDS)
            + "."
        )
        return entry
    if env_mode and (missing := store.missing_env(bag)):
        entry.update(status="missing", message=f"Не хватает переменных окружения: {', '.join(missing)}.")
        return entry

    exp = store.expires_at(bag)
    entry["expires_at"] = exp.isoformat() if exp else None
    if store.is_expired(bag) and not store.can_refresh(bag):
        entry.update(status="expired", message=f"Токен истёк — выполните '{store.profile.login_cmd}'.")
        return entry
    if not live:
        entry["status"] = "unchecked"
        return entry

    try:
        if env_mode and (not bag.get("token") or store.is_expired(bag)):
            exp = store.expires_at(store.refresh())
            entry["expires_at"] = exp.isoformat() if exp else None
        if check is not None:
            check()
        elif not env_mode:
            entry["status"] = "unchecked"  # инструмент не дал запроса к API — проверить нечем
            return entry
    except CliError as exc:
        unreachable = exc.exit_code == 5 or isinstance(exc.__cause__, httpx.TransportError)
        entry.update(status="unreachable" if unreachable else "invalid", message=exc.message)
        return entry
    entry["status"] = "ok"
    return entry


def status_report(tool: str, version: str, credentials: list[dict]) -> dict:
    """Весь JSON `auth status` по §8: инструмент, версия, время проверки, список учётных данных."""
    return {
        "tool": tool,
        "version": version,
        "checked_at": _now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "credentials": credentials,
    }


def status_exit_code(report: dict) -> int:
    """0 — все обязательные ok/unchecked (необязательные могут быть missing), иначе 3."""
    problems = [c for c in report["credentials"] if c["required"] and c["status"] not in OK_STATUSES]
    return EXIT_PROBLEM if problems else EXIT_OK


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
