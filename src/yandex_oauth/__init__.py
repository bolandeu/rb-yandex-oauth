"""yandex-oauth — общая OAuth-авторизация Яндекса для CLI-инструментов.

Один Яндекс-аккаунт, одно OAuth-приложение — один токен в общем слоте
keychain для всех инструментов (ym, ywm, …): вход делается один раз, токен
обновляется сам. Инструмент описывает себя `Profile` и получает:

- `CredentialStore(profile)` — keychain ОС + переменные окружения `<CLI>_YANDEX_<FIELD>`;
- `TokenStore(profile, credentials)` — где лежит токен, не истёк ли, автообновление по refresh_token;
- `oauth` — ссылка на согласие, обмен кода, refresh;
- `make_auth_app(...)` — готовая Typer-команда `auth login|refresh|logout|status`.
"""

from __future__ import annotations

from .credentials import CredentialStore
from .profile import Profile
from .token import TokenStore

__all__ = ["Profile", "CredentialStore", "TokenStore"]
