# CLAUDE.md

## Commands

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

## Что это

Общая библиотека OAuth-авторизации Яндекса для CLI-инструментов `~/Projects/tools/` (`ym`, `ywm`, …), построенных по единой CLI-архитектуре (skill `cli-generator:cli-builder`). Не CLI сама по себе — подключается как path-зависимость (`[tool.uv.sources]`), см. README.

**Source layout:** `src/yandex_oauth/`

- `profile.py` — `Profile` (cli_name, token_env, scopes, service, provider, `keychain_namespace="yandex-oauth"`) — единственное, чем инструменты отличаются; слот keychain общий для всех (один вход — все инструменты)
- `errors.py` — `CliError` (общий базовый класс: `output.guard` инструментов ловит именно его), `InvalidArguments`, `AuthRequired(profile)`, `CredentialStoreUnavailable(profile, reason)`
- `credentials.py` — `CredentialStore(profile)`: keychain `yandex-oauth:<provider>` через `keyring`, env-переопределение полей `YANDEX_OAUTH_<PROVIDER>_<FIELD>`
- `oauth.py` — `TokenSet`, `authorize_url`, `parse_manual_token`, `exchange_code`, `refresh_access_token`, `app_credentials_from_env()` (`YANDEX_CLIENT_ID`/`YANDEX_CLIENT_SECRET` — общие для всех инструментов, без префикса)
- `token.py` — `TokenStore(profile, credentials)`: `stored/source/resolve/refresh/store_token_set/retry_token_after/delete`; константы `FIELDS`, `REFRESH_BEFORE` (30 дн.), `REFRESH_AFTER` (90 дн.), `INVALID_TOKEN_RE` (Вебмастер `INVALID_OAUTH_TOKEN`, Метрика `invalid_token`)
- `auth_command.py` — `make_auth_app(profile, store, output, check=None)`; `_ask` (вопросы в stderr, байтовый ввод, только печатный ASCII); интерактивные подсказки — тоже в stderr, stdout чист для `--json`

**Никаких `.env`:** секреты только в keychain и переменных окружения (пользовательское решение 2026-09-17 — `.env.shared` удалён). Порядок: `--token` → `$TOKEN_ENV` → keychain.

**Инварианты, которые нельзя ломать (на них завязаны тесты инструментов):**
- Общие функции вызываются через атрибут модуля (`oauth.exchange_code`, `oauth.refresh_access_token`, `keyring.set_password`), чтобы тесты инструментов могли патчить `ywm.commands.auth.oauth.exchange_code` / `ywm.core.token.oauth.refresh_access_token` / `<pkg>.credentials.manager.keyring.*` через реэкспорт того же объекта модуля.
- `TokenStore.refresh()` вызывает `oauth.refresh_access_token(refresh_token, client_id, client_secret)` ровно с тремя позиционными аргументами.
- `login` интерактивно не копирует токен из окружения (это бывший баг: протухший токен из окружения подменял получение нового); копирование из env — только под `--non-interactive`.

**Тесты:** `tests/fake_output.py` — минимальный `output`-модуль в духе шаблона; `conftest.py` подменяет keyring in-memory (ключ `("yandex-oauth:yandex", "yandex")`) и чистит env.
