# yandex-oauth (`rb-yandex-oauth`)

Общая OAuth-авторизация Яндекса для CLI-инструментов (`ym`, `ywm`, …). Один Яндекс-аккаунт и одно OAuth-приложение — **один токен в общем слоте keychain** (`yandex-oauth:yandex`) для всех инструментов: вход в любом из них авторизует остальные, токен обновляется сам. Без дублирования кода и без `.env`-файлов.

## Что даёт

| Модуль | Назначение |
|---|---|
| `Profile` | Чем инструмент отличается: имя CLI (`ym`), env-переменная токена (`YANDEX_METRIKA_TOKEN`), scopes, название сервиса. Слот keychain общий (`keychain_namespace="yandex-oauth"`) |
| `CredentialStore(profile)` | Keychain ОС (`yandex-oauth:yandex`) + переопределение полей через `YANDEX_OAUTH_YANDEX_<FIELD>` |
| `TokenStore(profile, credentials)` | Где лежит токен, срок действия, автообновление по refresh_token (за 30 дней до истечения, не реже раза в 90 дней), `retry_token_after()` для повтора запроса при 403 «токен протух» |
| `oauth` | Ссылка на согласие, обмен кода на токен, refresh, разбор «ручного» адреса `verification_code#access_token=…` |
| `make_auth_app(profile, store, output, check=…)` | Готовая Typer-команда `auth login / refresh / logout / status [--check]` |
| `health_check(store, check)` → `Health` | Делегат для `Provider.health_check()` инструмента по шаблону cli-generator: `status` / `expires_at` / `quota` / `message` одинаково у всех Яндекс-инструментов (§8 стандарта `~/Work/tools/docs/standard-release.md`); 10 с на проверку, 401/403 → `invalid`, сеть/429/5xx → `unreachable` |
| `credential_status`, `status_report`, `status_problems`, `status_exit_code` | Отчёт `auth status --json` по §8 целиком (для `make_auth_app`): `source`, `source_ref`, `status`, `expires_at`, без значений секретов |

Порядок поиска токена везде одинаковый: `--token` → `$<TOKEN_ENV>` (CI/скрипты) → `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN` из окружения (режим «только env») → общий keychain.

## Переменные окружения

Одна схема имён на все Яндекс-инструменты: **`YANDEX_OAUTH_YANDEX_<FIELD>`** (namespace `yandex-oauth` + провайдер `yandex` + поле).

| Переменная | Статус | Зачем |
|---|---|---|
| `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN`, `YANDEX_OAUTH_YANDEX_CLIENT_ID`, `YANDEX_OAUTH_YANDEX_CLIENT_SECRET` | **основная** | Сервер без keychain (запуск с переменными окружения из секрет-менеджера): access-токен получается по refresh_token при первом запросе и обновляется в памяти процесса; в keychain ничего не пишется. Если задан `…_REFRESH_TOKEN`, keychain не читается вовсе |
| `YANDEX_OAUTH_YANDEX_<FIELD>` (`TOKEN`, `EXPIRES_AT`, …) | основная | Переопределить одно поле из keychain |
| `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET` | legacy | OAuth-приложение для `auth login`; в режиме «только env» — запасной вариант для `…_CLIENT_ID/SECRET`. Новое — задавать под основными именами |
| `<TOKEN_ENV>` инструмента (`YANDEX_METRIKA_TOKEN`, `YANDEX_WEBMASTER_TOKEN`) | legacy | Готовый access-токен без автообновления — только для одного инструмента и разовых запусков |

Keychain недоступен (Linux без Secret Service, контейнер) — чтение не падает, работаем от переменных окружения; не хватает части полей — ошибка `CREDENTIALS_INCOMPLETE` (exit 3) с именами недостающих переменных. `auth login` без keychain сохранить токен не может (`CREDENTIAL_STORE_UNAVAILABLE`).

Яндекс при обновлении выдаёт новый refresh_token, но старый продолжает работать (проверено 2026-09-27) — перезапуск с тем же значением из секрет-менеджер безопасен. Срок жизни ограничен: `auth status --json` показывает `expires_at`, заранее перевыпустите refresh_token (`auth login` на Mac → новое значение в секрет-менеджер).
`auth login` без `--token` всегда получает **новый** токен (OAuth через браузер) и кладёт его в общий слот; старый из окружения не копируется (только под `--non-interactive`). Файлы `.env` не читаются: секреты живут только в keychain и переменных окружения.

Репозиторий: https://github.com/bolandeu/yandex-oauth. Инструменты подключают его как git-зависимость, закреплённую на релизном теге.

## Подключение к инструменту

`pyproject.toml` инструмента:

```toml
dependencies = ["rb-yandex-oauth>=0.3,<0.4", ...]   # на 0.x минорная версия считается ломающей

[tool.uv.sources]
rb-yandex-oauth = { git = "https://github.com/bolandeu/yandex-oauth", tag = "v0.3.0" }
```

Имя дистрибутива — `rb-yandex-oauth` (§10 стандарта: `yandex-oauth` на PyPI — чужой пакет), импорт по-прежнему `yandex_oauth`. Не `branch = "main"` и не закоммиченный `path =`. Правки одновременно с инструментом — `uv pip install -e ../yandex-oauth` в его venv, без коммита. Переход на новый тег: `tag = "vNEW"` + `uv lock --upgrade-package rb-yandex-oauth` + тесты инструмента, одним коммитом.

Переход с `yandex-oauth` (до v0.3.0) на `rb-yandex-oauth`: поменять имя и в `dependencies`, и в ключе `[tool.uv.sources]`. **Ловушка dev-venv:** `uv sync` после переименования ставит новый дистрибутив и удаляет старый — вместе с общими файлами, и console script инструмента может пропасть, так что `uv run <cli>` молча запустит другой `<cli>` из PATH (старый глобальный). Один раз: `uv sync --reinstall-package <дистрибутив инструмента>` (и `--reinstall-package rb-yandex-oauth`, если `import yandex_oauth` сломался).

`constants.py`:

```python
from yandex_oauth import Profile

PROFILE = Profile(cli_name="ym", token_env="YANDEX_METRIKA_TOKEN", scopes="metrika:read", service="Яндекс.Метрика")
```

Тонкие модули инструмента (`core/oauth.py`, `core/token.py`, `credentials/manager.py`, `commands/auth.py`) реэкспортируют общий код, привязанный к профилю — см. `ym` или `ywm` как образец. `core/errors.py` инструмента импортирует `CliError`/`InvalidArguments`/`CredentialStoreUnavailable`/`AuthRequired` отсюда, чтобы `output.guard` ловил ошибки общего кода.

`auth status [--check] --json` из `make_auth_app` — отчёт §8 в стандартном конверте: `ok: true` и отчёт при exit 0; при exit 3 — `ok: false`, `error` (`CREDENTIALS_UNHEALTHY`) и тот же отчёт. `tool` — `Profile.cli_name`, `version` — версия дистрибутива, который ставит console script с этим именем. Инструмент по шаблону cli-generator со своими `providers/` вместо этого делегирует проверку из `health_check()`:

```python
def health_check(self) -> Health:
    return yandex_oauth.health_check(token_store.store, check=lambda: self.get_json("/management/v1/counters"))
```

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

Гейт — `gate check`, он идёт на этой машине до коммита (`.agents/antagor/antagor.toml`). Справка команд `auth` — это docstring'и в `auth_command.py` (подстановки `{cli}`, `{token_env}`… и обязательная строка `Example:`). Поменяли поведение команды — поменяйте её docstring в том же коммите; снапшоты справки для профиля `demo` — `tests/snapshots/help/`, обновление: `uv run pytest --snapshot-update` и прочитать diff.

## Версии и релизы

- Версии в `pyproject.toml` нет: она берётся из git-тега `vX.Y.Z` (uv-dynamic-versioning), в коде — `importlib.metadata.version("rb-yandex-oauth")`.
- Релиз — `antagor publish` (Antagor ставит тег; `CHANGELOG.md` и теги руками не правят).
