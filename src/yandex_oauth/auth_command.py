"""Готовая Typer-команда `auth login|refresh|logout|status` — одна на все инструменты.

Инструмент передаёт свой `output`-модуль (guard/emit_success/опции — из общей
CLI-архитектуры), чтобы вывод, JSON-конверт и обработка ошибок были ровно
такими же, как у его собственных команд.
"""

from __future__ import annotations

import re
import sys
import webbrowser
from collections.abc import Callable
from types import ModuleType

import typer

from . import oauth
from .errors import CliError, InvalidArguments
from .profile import Profile
from .token import TokenStore, _now

CLIENT_ID_ENV = oauth.CLIENT_ID_ENV
CLIENT_SECRET_ENV = oauth.CLIENT_SECRET_ENV


def _ask(text: str, hide: bool = False) -> str:
    """Спросить строку в терминале, устойчиво к мусору в вводе.

    Вопрос пишется в stderr (stdout остаётся чистым для --json). Ответ читается
    байтами; остаются только печатные ASCII-символы без пробелов по краям: все
    значения здесь (client_id, secret, код, токен) — латиница, а лишние переносы,
    пробелы и половинки UTF-8-символов (macOS: русская буква + backspace) — мусор,
    от которого input() падал с UnicodeDecodeError.
    """
    sys.stderr.write(f"{text}: ")
    sys.stderr.flush()
    if hide and sys.stdin.isatty() and sys.platform != "win32":
        import termios

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        quiet_attrs = list(old_attrs)
        quiet_attrs[3] &= ~termios.ECHO
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, quiet_attrs)
            raw = sys.stdin.buffer.readline()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            sys.stderr.write("\n")
    elif hide and sys.stdin.isatty():
        import getpass

        raw = getpass.getpass("").encode("utf-8", errors="ignore")
    else:
        raw = sys.stdin.buffer.readline()
    if not raw:
        raise typer.Abort()
    return re.sub(r"[^\x20-\x7e]", "", raw.decode("utf-8", errors="ignore")).strip()


def make_auth_app(
    profile: Profile,
    store: TokenStore,
    output: ModuleType,
    *,
    check: Callable[[typer.Context], None] | None = None,
) -> typer.Typer:
    """Собрать sub-app `auth` для инструмента.

    check — необязательный живой запрос к API для `auth status --check`
    (например `lambda ctx: services.get_client(ctx).get_counters_sync()`);
    должен бросать CliError инструмента при отказе API.
    """
    app = typer.Typer(help=f"OAuth-токен {profile.service}: вход, статус, обновление, выход.")
    human = output.human

    def _describe(bag: dict) -> dict:
        """Срок действия и возможность автообновления — для status/login/refresh."""
        exp = store.expires_at(bag)
        days_left = (exp - _now()).days if exp else None
        return {
            "expires_at": exp.isoformat() if exp else None,
            "days_left": days_left,
            "refreshable": store.can_refresh(bag),
        }

    def _oauth_flow(cid: str, secret: str, interactive: bool) -> oauth.TokenSet:
        if not interactive:
            raise InvalidArguments("OAuth-поток требует ввода кода из браузера; в --non-interactive передайте --token.")
        url = oauth.authorize_url(cid)
        # Подсказки интерактивного потока — в stderr, как и вопросы _ask:
        # stdout остаётся чистым для --json.
        typer.echo("\nОткрываю браузер для авторизации...", err=True)
        typer.echo(f"Если браузер не открылся, перейдите вручную:\n{url}\n", err=True)
        webbrowser.open(url)
        code = _ask("Вставьте код авторизации от Яндекса")
        if not code:
            raise InvalidArguments("Код авторизации не введён.")
        return oauth.exchange_code(code, cid, secret)

    # --- login ---------------------------------------------------------------------

    def login(
        ctx: typer.Context,
        token: str | None = typer.Option(
            None,
            "--token",
            help="Готовый OAuth-токен или адрес …verification_code#access_token=… (без автообновления).",
        ),
        client_id: str | None = typer.Option(None, "--client-id", help=f"ID OAuth-приложения (или ${CLIENT_ID_ENV})."),
        client_secret: str | None = typer.Option(
            None, "--client-secret", help=f"Секрет приложения (или ${CLIENT_SECRET_ENV})."
        ),
        non_interactive: bool = output.NonInteractiveOption,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        interactive = not (ctx.obj.get("non_interactive") or non_interactive)
        token, client_id, client_secret = (v.strip() or None if v else None for v in (token, client_id, client_secret))
        token = token or ctx.obj.get("token")
        stored = store.stored()
        env_cid, env_secret = oauth.app_credentials_from_env()
        cid = client_id or env_cid or stored.get("client_id")
        secret = client_secret or env_secret or stored.get("client_secret")

        token_set: oauth.TokenSet | None = None
        method = "token"
        if token:
            token_set = oauth.parse_manual_token(token)
        elif client_id and client_secret:
            token_set, method = _oauth_flow(client_id, client_secret, interactive), "oauth"
        elif not interactive:
            # CI/агенты: скопировать готовый токен из окружения в keychain, иначе ошибка.
            env_token = store.env_token()
            if not env_token:
                raise InvalidArguments(
                    f"Нет токена: передайте --token или задайте ${profile.token_env} "
                    f"(OAuth-поток через браузер в --non-interactive недоступен)."
                )
            token_set = oauth.TokenSet(env_token)
        elif cid and secret:
            # Интерактивно старый токен из окружения/.env намеренно НЕ копируем:
            # login нужен, чтобы получить новый взамен протухшего.
            token_set, method = _oauth_flow(cid, secret, interactive), "oauth"
        else:
            cid = _ask("Client ID OAuth-приложения (Enter — вставить готовый токен)")
            if cid:
                secret = _ask("Client secret приложения", hide=True)
                token_set, method = _oauth_flow(cid, secret, interactive), "oauth"
            else:
                token_set = oauth.parse_manual_token(_ask(f"Вставьте OAuth-токен {profile.service}", hide=True))
        if not token_set.access_token:
            raise InvalidArguments("Пустой токен.")

        bag = store.store_token_set(token_set, cid, secret)

        payload = {
            "provider": profile.provider,
            "method": method,
            "stored": "keychain",
            **_describe(bag),
        }

        def render(d: dict) -> None:
            human.echo("[green]Токен сохранён в системном keychain.[/green]")
            if d["expires_at"]:
                human.echo(
                    f"Действует до {d['expires_at'][:10]} ({d['days_left']} дн.), "
                    f"автообновление: {'да' if d['refreshable'] else 'нет'}"
                )
            else:
                human.echo(
                    "[yellow]Срок действия неизвестен, автообновление невозможно (токен вставлен вручную).[/yellow]"
                )

        output.emit_success(ctx, payload, render)

    login.__doc__ = f"""Получить OAuth-токен и сохранить в keychain вместе с refresh_token — дальше он обновляется сам.

    Токен общий для всех Яндекс-инструментов (один слот keychain): вход в одном
    из них авторизует и остальные. Без опций возьмёт client_id/client_secret
    приложения из окружения (${CLIENT_ID_ENV}/${CLIENT_SECRET_ENV}) или из keychain
    с прошлого входа, откроет браузер и попросит код; если их нет — спросит.
    Старый токен из ${profile.token_env} при этом не копируется: login нужен,
    чтобы получить новый.

    \b
    Порядок источников: --token → --client-id/--client-secret →
    (только --non-interactive: ${profile.token_env}) → client_id/secret из
    окружения или keychain → интерактивные вопросы.

    \b
      {profile.cli_name} auth login                          # обычный путь: браузер → код → готово
      {profile.cli_name} auth login --token y0_AgAAAA...     # вставить готовый токен (обновляться не будет)
      {profile.cli_name} auth login --token 'https://oauth.yandex.ru/verification_code#access_token=...&expires_in=...'
      {profile.cli_name} auth login --non-interactive        # скопировать ${profile.token_env} в keychain (CI)

    Создать приложение: {oauth.NEW_APP_URL}
    Нужные права: {profile.scopes}
    """
    app.command("login")(output.guard(login))

    # --- refresh -------------------------------------------------------------------

    def refresh(
        ctx: typer.Context,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        bag = store.refresh()
        output.emit_success(
            ctx,
            {"provider": profile.provider, "refreshed": True, **_describe(bag)},
            lambda d: human.echo(
                f"[green]Токен обновлён.[/green] Действует до {d['expires_at'][:10]} ({d['days_left']} дн.)"
            ),
        )

    refresh.__doc__ = f"""Принудительно обновить токен по refresh_token и перезаписать keychain (без браузера).

    Обычно не нужно: CLI сам обновляет токен за 30 дней до истечения и при 403 от API.
    Полезно для cron/агентов.

    \b
      {profile.cli_name} auth refresh --json
    """
    app.command("refresh")(output.guard(refresh))

    # --- logout --------------------------------------------------------------------

    def logout(
        ctx: typer.Context,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        """Удалить токен, refresh_token и данные приложения из keychain (переменные окружения не трогает)."""
        store.delete()
        output.emit_success(
            ctx, {"provider": profile.provider}, lambda d: human.echo("Учётные данные удалены из keychain.")
        )

    app.command("logout")(output.guard(logout))

    # --- status --------------------------------------------------------------------

    def auth_status(
        ctx: typer.Context,
        check_flag: bool = typer.Option(False, "--check", help="Проверить токен живым запросом к API."),
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        source = store.source(ctx.obj.get("token"))
        bag = store.stored() if source == "keychain" else {}
        payload: dict = {
            "provider": profile.provider,
            "authenticated": source is not None,
            "source": source,
            **_describe(bag),
        }
        if check_flag and source is not None:
            if check is None:
                raise InvalidArguments("--check не поддерживается этим инструментом.")
            try:
                check(ctx)
                payload["valid"] = True
            except CliError as exc:
                payload["valid"] = False
                payload["error"] = exc.message

        def render(d: dict) -> None:
            if not d["authenticated"]:
                human.echo(f"Токена нет. Выполните '{profile.login_cmd}' или задайте ${profile.token_env}.")
                return
            line = f"Токен найден (источник: {d['source']})."
            if d["expires_at"]:
                line += (
                    f" Действует до {d['expires_at'][:10]} ({d['days_left']} дн.), "
                    f"автообновление: {'да' if d['refreshable'] else 'нет'}."
                )
            human.echo(line)
            if "valid" in d:
                human.echo(
                    "[green]API принимает токен.[/green]"
                    if d["valid"]
                    else f"[red]API отверг токен:[/red] {d['error']}"
                )

        output.emit_success(ctx, payload, render)

    auth_status.__doc__ = f"""Есть ли токен, откуда он (argument / env / keychain), срок действия и автообновление.

    \b
      {profile.cli_name} auth status --json
      {profile.cli_name} auth status --check      # + реальный запрос к API
    """
    app.command("status")(output.guard(auth_status))

    return app
