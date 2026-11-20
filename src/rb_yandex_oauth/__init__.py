"""yandex-oauth — общая OAuth-авторизация Яндекса для CLI-инструментов.

Один Яндекс-аккаунт, одно OAuth-приложение — один токен в общем слоте
keychain для всех инструментов (ym, ywm, …): вход делается один раз, токен
обновляется сам. Инструмент описывает себя `Profile` и получает:

- `CredentialStore(profile)` — keychain ОС + переменные окружения `YANDEX_OAUTH_YANDEX_<FIELD>`
  (без keychain — только переменные окружения);
- `TokenStore(profile, credentials)` — где лежит токен, не истёк ли, автообновление по refresh_token
  (в режиме «только env» — в памяти процесса);
- `status` — отчёт для `<cli> auth status --json` по контракту §8 стандарта tools и `health_check()` —
  делегат для `Provider.health_check()` инструментов по шаблону cli-generator;
- `oauth` — ссылка на согласие, обмен кода, refresh;
- `make_auth_app(...)` — готовая Typer-команда `auth login|refresh|logout|status`.
"""

from __future__ import annotations

from .credentials import CredentialStore
from .profile import Profile
from .status import Health, Quota, credential_status, health_check, status_exit_code, status_problems, status_report
from .token import TokenStore

__all__ = [
    "CredentialStore",
    "Health",
    "Profile",
    "Quota",
    "TokenStore",
    "credential_status",
    "health_check",
    "status_exit_code",
    "status_problems",
    "status_report",
]
