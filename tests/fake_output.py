"""Минимальный `output`-модуль в духе общей CLI-архитектуры — только то, что нужно auth-командам."""

from __future__ import annotations

import functools
import json
from types import SimpleNamespace

import typer

from yandex_oauth.errors import CliError

JsonOption = typer.Option(False, "--json")
QuietOption = typer.Option(False, "--quiet")
NonInteractiveOption = typer.Option(False, "--non-interactive")

_printed: list[str] = []


def _echo(message: str) -> None:
    typer.echo(message)


human = SimpleNamespace(echo=_echo)


def emit_success(ctx, payload, render_human) -> None:
    if ctx.obj.get("json"):
        typer.echo(json.dumps({"ok": True, **payload}, ensure_ascii=False))
    elif not ctx.obj.get("quiet"):
        render_human(payload)


def emit_error(ctx, error: CliError) -> None:
    if ctx.obj.get("json"):
        typer.echo(json.dumps({"ok": False, "error": error.to_dict()}, ensure_ascii=False))
    else:
        typer.echo(f"Error: {error.message}")
    raise typer.Exit(code=error.exit_code)


def guard(func):
    @functools.wraps(func)
    def wrapper(ctx: typer.Context, *args, **kwargs):
        for flag, key in (("json_output", "json"), ("quiet", "quiet"), ("non_interactive", "non_interactive")):
            if kwargs.get(flag):
                ctx.obj[key] = True
        try:
            return func(ctx, *args, **kwargs)
        except CliError as exc:
            emit_error(ctx, exc)

    return wrapper
