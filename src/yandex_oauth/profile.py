from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """Чем инструмент отличается в общей схеме авторизации.

    cli_name  — имя команды: пространство имён в keychain (`<cli>:yandex`) и
                префикс переменных окружения полей (`<CLI>_YANDEX_<FIELD>`).
    token_env — «историческая» переменная окружения с готовым токеном
                (YANDEX_METRIKA_TOKEN, YANDEX_WEBMASTER_TOKEN, …).
    scopes    — права OAuth-приложения, нужные инструменту (для подсказок).
    service   — название сервиса для текстов («Яндекс.Метрика»).
    """

    cli_name: str
    token_env: str
    scopes: str
    service: str
    provider: str = "yandex"

    @property
    def login_cmd(self) -> str:
        return f"{self.cli_name} auth login"
