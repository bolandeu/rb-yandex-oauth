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

Порядок поиска токена везде одинаковый: `--token` → `$<TOKEN_ENV>` (CI/скрипты) → общий keychain.
`auth login` без `--token` всегда получает **новый** токен (OAuth через браузер) и кладёт его в общий слот; старый из окружения не копируется (только под `--non-interactive`). Файлы `.env` не читаются: секреты живут только в keychain и переменных окружения.

Репозиторий: https://github.com/bolandeu/yandex-oauth. Инструменты подключают его как path-зависимость, поэтому клонировать нужно рядом с ними: `~/Projects/tools/yandex-oauth`.

## Подключение к инструменту

`pyproject.toml` инструмента:

```toml
dependencies = ["yandex-oauth", ...]

[tool.uv.sources]
yandex-oauth = { path = "../yandex-oauth", editable = true }   # пакет лежит рядом в ~/Projects/tools/
```

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
    new_token = token_store.retry_token_after(resp.status_code, resp.text)   # обновит и вернёт токен при 403 invalid token
```

## Разработка

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```
