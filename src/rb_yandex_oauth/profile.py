from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """Чем инструмент отличается в общей схеме авторизации.

    cli_name  — имя команды (тексты подсказок, `<cli> auth login`).
    token_env — «историческая» переменная окружения с готовым токеном
                (YANDEX_METRIKA_TOKEN, YANDEX_WEBMASTER_TOKEN, …).
    scopes    — права OAuth-приложения, нужные инструменту (для подсказок).
    service   — название сервиса для текстов («Яндекс.Метрика»).
    keychain_namespace — общий для всех инструментов: запись keychain
                `yandex-oauth:yandex`, env-переопределения полей
                `YANDEX_OAUTH_YANDEX_<FIELD>`. Один вход — все инструменты.
    """

    cli_name: str
    token_env: str
    scopes: str
    service: str
    provider: str = "yandex"
    # Токен один на все инструменты (один аккаунт, одно OAuth-приложение), поэтому
    # запись keychain и env-переопределения полей общие, а не по имени CLI.
    keychain_namespace: str = "yandex-oauth"

    @property
    def login_cmd(self) -> str:
        return f"{self.cli_name} auth login"
