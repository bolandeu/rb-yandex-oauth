"""Контракт `auth status` (§8 стандарта tools): форма отчёта и конверта, статусы, коды выхода.

Форма — межинструментальный контракт (tools-watch читает её у всех CLI):
менять её = ломающее изменение (§4).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from importlib import metadata

import httpx
import pytest
import typer

from rb_yandex_oauth import Health, health_check, status_exit_code, status_problems, status_report
from rb_yandex_oauth.auth_command import _tool_version, make_auth_app
from rb_yandex_oauth.errors import AuthRequired, CliError

from . import fake_output
from .conftest import KEY, PROFILE

ENTRY_KEYS = ["provider", "required", "fields", "source", "source_ref", "status", "expires_at", "quota", "message"]


def _json(result) -> dict:
    return json.loads(result.stdout)


def _http_error(code: int) -> CliError:
    request = httpx.Request("GET", "https://api.example/")
    response = httpx.Response(code, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        error = CliError("API_ERROR", f"HTTP {code}")
        error.__cause__ = exc
        return error
    raise AssertionError("unreachable")


class TestEnvelope:
    def test_ok_report_shape(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "t", "expires_at": "2099-01-01T00:00:00+00:00"})
        result = runner.invoke(app, ["auth", "status", "--json"])
        assert result.exit_code == 0
        data = _json(result)
        assert list(data) == ["ok", "tool", "version", "checked_at", "credentials"]
        assert data["ok"] is True and data["tool"] == "demo" and data["checked_at"].endswith("Z")
        entry = data["credentials"][0]
        assert list(entry) == ENTRY_KEYS
        assert entry["status"] == "unchecked" and entry["expires_at"] == "2099-01-01T00:00:00Z"

    def test_expires_at_without_microseconds(self, app, runner, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "t", "expires_at": "2099-01-01T00:00:00.123456+00:00"})
        entry = _json(runner.invoke(app, ["auth", "status", "--json"]))["credentials"][0]
        assert entry["expires_at"] == "2099-01-01T00:00:00Z"

    def test_problem_report_keeps_full_report_next_to_error(self, app, runner):
        result = runner.invoke(app, ["auth", "status", "--json"])
        assert result.exit_code == 3
        data = _json(result)
        assert list(data) == ["ok", "error", "tool", "version", "checked_at", "credentials"]
        assert data["error"]["code"] == "CREDENTIALS_UNHEALTHY" and "yandex (missing)" in data["error"]["message"]
        assert data["error"]["action"]

    def test_human_output(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 3
        assert "✗ yandex: missing" in result.stdout and "CREDENTIALS_UNHEALTHY" not in result.stdout
        assert "Error:" in result.stderr
        fake_keyring[KEY] = json.dumps({"token": "t"})
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0 and "· yandex: unchecked (keychain: keychain service" in result.stdout

    def test_check_without_tool_check_is_unchecked(self, store, runner, fake_keyring):
        root = typer.Typer()
        root.add_typer(make_auth_app(PROFILE, store, fake_output), name="auth")

        @root.callback()
        def main(ctx: typer.Context) -> None:
            ctx.obj = {"json": True}

        fake_keyring[KEY] = json.dumps({"token": "t"})
        result = runner.invoke(root, ["auth", "status", "--check"])
        assert result.exit_code == 0 and _json(result)["credentials"][0]["status"] == "unchecked"

    def test_tool_version_from_output_package(self):
        assert _tool_version("demo") == "0.0.0"  # нет такого console script
        assert _tool_version("pytest") == metadata.version("pytest")


class TestSources:
    def test_env_field_overrides_keychain(self, fake_keyring, store, monkeypatch):
        from rb_yandex_oauth import credential_status

        fake_keyring[KEY] = json.dumps({"token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s"})
        monkeypatch.setenv("YANDEX_OAUTH_YANDEX_TOKEN", "rotated")
        entry = credential_status(store)
        assert entry["source"] == "env"
        assert entry["source_ref"] == "YANDEX_OAUTH_YANDEX_TOKEN; rest from keychain service yandex-oauth:yandex"
        assert "rotated" not in json.dumps(entry)

    def test_missing_names_where_to_put_it(self, store):
        from rb_yandex_oauth import credential_status

        entry = credential_status(store)
        assert entry["source_ref"].startswith("YANDEX_DEMO_TOKEN or YANDEX_OAUTH_YANDEX_REFRESH_TOKEN")
        assert entry["source_ref"].endswith("keychain service yandex-oauth:yandex")


class TestHealthCheck:
    @pytest.fixture(autouse=True)
    def _token(self, fake_keyring):
        fake_keyring[KEY] = json.dumps({"token": "secret-token", "expires_at": "2099-01-01T00:00:00+00:00"})

    def test_ok_with_expiry(self, store):
        health = health_check(store, check=lambda: None)
        assert health == Health(status="ok", expires_at=datetime(2099, 1, 1, tzinfo=UTC))

    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (_http_error(401), "invalid"),
            (_http_error(403), "invalid"),
            (_http_error(429), "unreachable"),
            (_http_error(503), "unreachable"),
            (CliError("PROVIDER_ERROR", "down", exit_code=5), "unreachable"),
            (AuthRequired(PROFILE), "invalid"),
            (httpx.ConnectError("no route"), "unreachable"),
            (RuntimeError("boom"), "unreachable"),
        ],
    )
    def test_failure_mapping(self, store, error, status):
        def check() -> None:
            raise error

        assert health_check(store, check=check).status == status

    def test_timeout(self, store):
        release = threading.Event()
        health = health_check(store, check=lambda: release.wait(5), timeout=0.05)
        release.set()
        assert health.status == "unreachable" and "0.05" in (health.message or "")

    def test_scrubs_secret_values(self, store):
        def check() -> None:
            raise CliError("API_ERROR", "bad token secret-token")

        assert health_check(store, check=check).message == "bad token ***"

    def test_expired_without_refresh(self, fake_keyring, store):
        fake_keyring[KEY] = json.dumps({"token": "t", "expires_at": "2000-01-01T00:00:00+00:00"})
        assert health_check(store, check=lambda: None).status == "expired"


class TestExitCode:
    @staticmethod
    def _report(*entries: tuple[bool, str]) -> dict:
        credentials = [{"provider": f"p{i}", "required": req, "status": st} for i, (req, st) in enumerate(entries)]
        return status_report("demo", "1.0.0", credentials)

    @pytest.mark.parametrize(
        ("entries", "code"),
        [
            ([(True, "ok"), (True, "unchecked")], 0),
            ([(False, "missing"), (False, "unreachable"), (False, "quota_exhausted")], 0),
            ([(True, "missing")], 3),
            ([(True, "unreachable")], 3),
            ([(False, "invalid")], 3),  # необязательный, но неверный — проблема
            ([(False, "expired")], 3),
        ],
    )
    def test_rules(self, entries, code):
        assert status_exit_code(self._report(*entries)) == code

    def test_problems_name_provider_and_status(self):
        assert status_problems(self._report((True, "ok"), (False, "invalid"))) == {"p1": "invalid"}
