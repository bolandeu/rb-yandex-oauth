from __future__ import annotations

from .profile import Profile


class CliError(Exception):
    """Базовая ошибка для всех ожидаемых, показываемых пользователю сбоев CLI.

    Единая для всех инструментов, использующих yandex-oauth: их `output.guard`
    ловит именно этот класс, поэтому ошибки общего кода (OAuth, keychain)
    выводятся так же, как собственные ошибки инструмента.

    Каждая несёт стабильный `code`, человекочитаемое `message`, необязательное
    `action` (что сделать, чтобы разблокироваться) и код выхода процесса.
    Непредвиденные исключения сюда НЕ заворачиваем — пусть падают трейсбеком
    (exit 1), а не прячутся.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        action: str | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.action:
            payload["action"] = self.action
        return payload


class InvalidArguments(CliError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, exit_code=2)


class AuthRequired(CliError):
    def __init__(self, profile: Profile) -> None:
        super().__init__(
            "AUTH_REQUIRED",
            f"Нет токена для провайдера '{profile.provider}'.",
            action=(
                f"Выполните '{profile.login_cmd}' или задайте переменные окружения "
                f"{_env(profile, 'REFRESH_TOKEN')}, {_env(profile, 'CLIENT_ID')}, {_env(profile, 'CLIENT_SECRET')} "
                f"(без keychain, токен обновляется в памяти) либо готовый токен в {profile.token_env}."
            ),
            exit_code=3,
        )


class CredentialStoreUnavailable(CliError):
    def __init__(self, profile: Profile, reason: str) -> None:
        super().__init__(
            "CREDENTIAL_STORE_UNAVAILABLE",
            f"Не удалось обратиться к системному хранилищу ключей для '{profile.provider}': {reason}",
            action=(
                f"Без keychain 'auth login' сохранить токен не может. Задайте переменные окружения "
                f"{_env(profile, 'REFRESH_TOKEN')}, {_env(profile, 'CLIENT_ID')}, {_env(profile, 'CLIENT_SECRET')} "
                f"(или готовый токен в {profile.token_env})."
            ),
            exit_code=1,
        )


class CredentialsIncomplete(CliError):
    """В окружении есть часть полей для обновления токена, но не все — иначе молча было бы «нет токена»."""

    def __init__(self, profile: Profile, missing: list[str]) -> None:
        super().__init__(
            "CREDENTIALS_INCOMPLETE",
            f"Для получения токена '{profile.provider}' из переменных окружения не хватает: {', '.join(missing)}.",
            action=f"Задайте {', '.join(missing)} (или выполните '{profile.login_cmd}' там, где есть keychain).",
            exit_code=3,
        )


class CredentialsUnhealthy(CliError):
    """`auth status` нашёл проблему (§8): отчёт выводится целиком, рядом — эта ошибка, exit 3."""

    def __init__(self, profile: Profile, problems: dict[str, str]) -> None:
        listed = ", ".join(f"{provider} ({status})" for provider, status in problems.items())
        super().__init__(
            "CREDENTIALS_UNHEALTHY",
            f"Учётные данные требуют внимания: {listed}.",
            action=f"Подробности — в `message` каждой записи; войти заново: '{profile.login_cmd}'.",
            exit_code=3,
        )


def _env(profile: Profile, field: str) -> str:
    """Имя переменной окружения поля общего слота: YANDEX_OAUTH_<PROVIDER>_<FIELD>."""
    prefix = profile.keychain_namespace.upper().replace("-", "_")
    return f"{prefix}_{profile.provider.upper()}_{field}"
