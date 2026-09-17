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
            action=f"Выполните '{profile.login_cmd}' или задайте переменную {profile.token_env}.",
            exit_code=3,
        )


class CredentialStoreUnavailable(CliError):
    def __init__(self, profile: Profile, reason: str) -> None:
        super().__init__(
            "CREDENTIAL_STORE_UNAVAILABLE",
            f"Не удалось обратиться к системному хранилищу ключей для '{profile.provider}': {reason}",
            action=f"Задайте токен через переменную окружения {profile.token_env} вместо 'auth login'.",
            exit_code=1,
        )
