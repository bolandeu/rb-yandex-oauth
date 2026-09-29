# CLAUDE.md

## Commands

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run scripts/release.py --check                 # весь гейт — перед каждым коммитом
uv run pytest --snapshot-update                   # после правки docstring/help= команд auth — и прочитать diff
uv run towncrier create +<slug>.<type>.md -c "…"   # фрагмент CHANGELOG на каждое заметное изменение
uv run scripts/release.py patch|minor|major       # релиз с main: тег vX.Y.Z (версия только в теге)
```

## Что это

Общая библиотека OAuth-авторизации Яндекса для CLI-инструментов `~/Projects/tools/` (`ym`, `ywm`, …), построенных по единой CLI-архитектуре (skill `cli-generator:cli-builder`). Не CLI сама по себе — подключается как git-зависимость на релизный тег (`[tool.uv.sources]`), см. README и `~/Projects/tools/docs/standard-release.md`.

**Source layout:** `src/yandex_oauth/`

- `profile.py` — `Profile` (cli_name, token_env, scopes, service, provider, `keychain_namespace="yandex-oauth"`) — единственное, чем инструменты отличаются; слот keychain общий для всех (один вход — все инструменты)
- `errors.py` — `CliError` (общий базовый класс: `output.guard` инструментов ловит именно его), `InvalidArguments`, `AuthRequired(profile)`, `CredentialStoreUnavailable(profile, reason)`, `CredentialsUnhealthy(profile, problems)` (exit 3 у `auth status`)
- `credentials.py` — `CredentialStore(profile)`: keychain `yandex-oauth:<provider>` через `keyring`, env-переопределение полей `YANDEX_OAUTH_<PROVIDER>_<FIELD>`
- `oauth.py` — `TokenSet`, `authorize_url`, `parse_manual_token`, `exchange_code`, `refresh_access_token`, `app_credentials_from_env()` (`YANDEX_CLIENT_ID`/`YANDEX_CLIENT_SECRET` — общие для всех инструментов, без префикса)
- `token.py` — `TokenStore(profile, credentials)`: `stored/source/resolve/refresh/store_token_set/retry_token_after/delete`; режим «только env» (`env_only()`: задан `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN` или keychain недоступен) — токен в памяти процесса (`_memory`), keychain не пишется; константы `FIELDS`, `REFRESH_BEFORE` (30 дн.), `REFRESH_AFTER` (90 дн.), `INVALID_TOKEN_RE` (Вебмастер `INVALID_OAUTH_TOKEN`, Метрика `invalid_token`)
- `status.py` — `health_check(store, check)` → `Health` (делегат для `Provider.health_check()` инструментов по шаблону: 10 с, маппинг ошибок, маскирование секретов) и `credential_status/status_report/status_problems/status_exit_code`: контракт `auth status --json` из §8 `~/Projects/tools/docs/standard-release.md` (форма покрыта `tests/test_status.py` — менять = ломающее изменение)
- `auth_command.py` — `make_auth_app(profile, store, output, check=None)`; `_ask` (вопросы в stderr, байтовый ввод, только печатный ASCII); интерактивные подсказки — тоже в stderr, stdout чист для `--json`. Docstring'и команд — литеральные, с подстановками `{cli}`/`{token_env}`/… и строкой `Example:` (§7): их проверяют `scripts/check_command_docstrings.py` (хуки; glob адаптирован под `auth_command.py`), `tests/test_help.py` и снапшоты `tests/snapshots/help/`

**Никаких `.env`:** секреты только в keychain и переменных окружения (пользовательское решение 2026-09-17 — `.env.shared` удалён). Порядок: `--token` → `$TOKEN_ENV` → env-режим (`YANDEX_OAUTH_YANDEX_REFRESH_TOKEN`) → keychain. Схема имён env — в README («Переменные окружения»).

**Keychain недоступен — не ошибка чтения** (серверы на Linux, `doppler run`): `get_credential` логирует предупреждение и работает от env; ошибка только при записи/удалении.

**Инварианты, которые нельзя ломать (на них завязаны тесты инструментов):**
- Общие функции вызываются через атрибут модуля (`oauth.exchange_code`, `oauth.refresh_access_token`, `keyring.set_password`), чтобы тесты инструментов могли патчить `ywm.commands.auth.oauth.exchange_code` / `ywm.core.token.oauth.refresh_access_token` / `<pkg>.credentials.manager.keyring.*` через реэкспорт того же объекта модуля.
- `TokenStore.refresh()` вызывает `oauth.refresh_access_token(refresh_token, client_id, client_secret)` ровно с тремя позиционными аргументами.
- `login` интерактивно не копирует токен из окружения (это бывший баг: протухший токен из окружения подменял получение нового); копирование из env — только под `--non-interactive`.

**Тесты:** `tests/fake_output.py` — минимальный `output`-модуль в духе шаблона; `conftest.py` подменяет keyring in-memory (ключ `("yandex-oauth:yandex", "yandex")`) и чистит env.

## Каждое заметное изменение выходит релизом

Серверы, другие инструменты и Mac ставят только по тегам, не из `main`:
влитое без релиза изменение для них не существует. Изменение с фрагментом
changelog закончено только после релиза: влить в `main` →
`uv run scripts/release.py patch|minor|major` → попросить пользователя
сделать push с `--follow-tags` → назвать новый тег в отчёте. Служебные коммиты
(без фрагмента) ждут следующего релиза. Не оставлять фрагмент на `main` без
релиза, не назвав причину (`~/Projects/tools/docs/standard-release.md` §3).

## Инструмент в системе

Инструмент — один из сервисов `~/Projects/tools/`: корневой агент его
деплоит, хранит ключи (Doppler) и бэкапит данные (S3). Полные правила —
`~/Projects/tools/docs/standard-release.md` §13.

- **Сообщать корневому агенту** (в отчёте пользователю, рядом с тегом
  релиза): новая или переименованная переменная окружения / ключ, новая
  локальная база или новый путь к данным, новая или убранная зависимость от
  другого инструмента, обновлённый токен сохраняется локально, ломающий релиз.
- **Потребители**: перед ломающим изменением проверить, кто пользуется
  инструментом (корневой `AGENTS.md` → Service map), и назвать их в отчёте.
- **Серверы Linux без экрана**: сначала переменные окружения, keychain
  необязателен (его отсутствие при заданной переменной — не ошибка); имена
  переменных — уже существующие; без TTY никаких вопросов; без путей только для Mac.
- **Локальные данные** — в `platformdirs.user_data_dir("<tool>")`, не в
  репозитории; всё состояние — в файле базы, миграции делает сам инструмент;
  сам инструмент данные никуда не выгружает.
