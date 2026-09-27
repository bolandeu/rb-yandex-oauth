# yandex-oauth

Общая OAuth-авторизация Яндекса для CLI-инструментов (`ym`, `ywm`, …). Один Яндекс-аккаунт и одно OAuth-приложение — **один токен в общем слоте keychain** (`yandex-oauth:yandex`) для всех инструментов: вход в любом из них авторизует остальные, токен обновляется сам. Без дублирования кода и без `.env`-файлов.

## Что даёт

| Модуль | Назначение |
|---|---|
| `Profile` | Чем инструмент отличается: имя CLI (`ym`), env-переменная токена (`YANDEX_METRIKA_TOKEN`), scopes, название сервиса. Слот keychain общий (`keychain_namespace="yandex-oauth"`) |
| `CredentialStore(profile)` | Keychain ОС (`yandex-oauth:yandex`) + переопределение полей через `YANDEX_OAUTH_YANDEX_<FIELD>` |
| `TokenStore(profile, credentials)` | Где лежит токен, срок действия, автообновление по refresh_token (за 30 дней до истечения, не реже раза в 90 дней), `retry_token_after()` для повтора запроса при 403 «токен протух» |
| `oauth` | Ссылка на согласие, обмен кода на токен, refresh, разбор «ручного» адреса `verification_code#access_token=…` |
| `make_auth_app(profile, store, output, check=…)` | Готовая Typer-команда `auth login / refresh / logout / status [--check]` |
| `credential_status`, `status_report`, `status_exit_code` | Отчёт `auth status --json` по контракту §8 стандарта (`~/Projects/tools/docs/standard-release.md`): `source`, `status`, `expires_at`, без значений секретов |

Порядок поиска токена везде одинаковый: `--token` → `$<TOKEN_ENV>` (CI/скрипты) → `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN` из окружения (режим «только env») → общий keychain.

## Переменные окружения

Одна схема имён на все Яндекс-инструменты: **`YANDEX_OAUTH_YANDEX_<FIELD>`** (namespace `yandex-oauth` + провайдер `yandex` + поле).

| Переменная | Статус | Зачем |
|---|---|---|
| `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN`, `YANDEX_OAUTH_YANDEX_CLIENT_ID`, `YANDEX_OAUTH_YANDEX_CLIENT_SECRET` | **основная** | Сервер без keychain (`doppler run`): access-токен получается по refresh_token при первом запросе и обновляется в памяти процесса; в keychain ничего не пишется. Если задан `…_REFRESH_TOKEN`, keychain не читается вовсе |
| `YANDEX_OAUTH_YANDEX_<FIELD>` (`TOKEN`, `EXPIRES_AT`, …) | основная | Переопределить одно поле из keychain |
| `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET` | legacy | OAuth-приложение для `auth login`; в режиме «только env» — запасной вариант для `…_CLIENT_ID/SECRET`. Новое — задавать под основными именами |
| `<TOKEN_ENV>` инструмента (`YANDEX_METRIKA_TOKEN`, `YANDEX_WEBMASTER_TOKEN`) | legacy | Готовый access-токен без автообновления — только для одного инструмента и разовых запусков |

Keychain недоступен (Linux без Secret Service, контейнер) — чтение не падает, работаем от переменных окружения; не хватает части полей — ошибка `CREDENTIALS_INCOMPLETE` (exit 3) с именами недостающих переменных. `auth login` без keychain сохранить токен не может (`CREDENTIAL_STORE_UNAVAILABLE`).

Яндекс при обновлении выдаёт новый refresh_token, но старый продолжает работать (проверено 2026-09-27) — перезапуск с тем же значением из Doppler безопасен. Срок жизни ограничен: `auth status --json` показывает `expires_at`, заранее перевыпустите refresh_token (`auth login` на Mac → новое значение в Doppler).
`auth login` без `--token` всегда получает **новый** токен (OAuth через браузер) и кладёт его в общий слот; старый из окружения не копируется (только под `--non-interactive`). Файлы `.env` не читаются: секреты живут только в keychain и переменных окружения.

Репозиторий: https://github.com/bolandeu/yandex-oauth. Инструменты подключают его как git-зависимость, закреплённую на релизном теге.

## Подключение к инструменту

`pyproject.toml` инструмента:

```toml
dependencies = ["yandex-oauth>=0.1,<0.2", ...]   # на 0.x минорная версия считается ломающей

[tool.uv.sources]
yandex-oauth = { git = "https://github.com/bolandeu/yandex-oauth", tag = "v0.1.0" }
```

Не `branch = "main"` и не закоммиченный `path =`. Правки одновременно с инструментом — `uv pip install -e ../yandex-oauth` в его venv, без коммита. Переход на новый тег: `tag = "vNEW"` + `uv lock --upgrade-package yandex-oauth` + тесты инструмента, одним коммитом.

`constants.py`:

```python
from yandex_oauth import Profile

PROFILE = Profile(cli_name="ym", token_env="YANDEX_METRIKA_TOKEN", scopes="metrika:read", service="Яндекс.Метрика")
```

Тонкие модули инструмента (`core/oauth.py`, `core/token.py`, `credentials/manager.py`, `commands/auth.py`) реэкспортируют общий код, привязанный к профилю — см. `ym` или `ywm` как образец. `core/errors.py` инструмента импортирует `CliError`/`InvalidArguments`/`CredentialStoreUnavailable`/`AuthRequired` отсюда, чтобы `output.guard` ловил ошибки общего кода.

Клиент API инструмента:

```python
t, self._refreshable = token_store.resolve(token)
if not t:
    raise AuthRequired(PROFILE)
...
if not resp.is_success and self._refreshable:
    # обновит и вернёт токен при 403 invalid token
    new_token = token_store.retry_token_after(resp.status_code, resp.text)
```

## Разработка

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
```

## Версии и релизы

Стандарт — `~/Projects/tools/docs/standard-release.md`.

- Версии в `pyproject.toml` нет: она берётся из git-тега `vX.Y.Z` (uv-dynamic-versioning), в коде — `importlib.metadata.version("yandex-oauth")`.
- `CHANGELOG.md` руками не правят. Каждое заметное изменение — фрагмент: `uv run towncrier create +<slug>.<type>.md -c "…"` (типы: added, changed, deprecated, removed, fixed, security).
- Релиз с `main`: `uv run scripts/release.py patch|minor|major` — гейт, сборка CHANGELOG, коммит `Release vX.Y.Z`, аннотированный тег. Push скрипт не делает, печатает команду.
