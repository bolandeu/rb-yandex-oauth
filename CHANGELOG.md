# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
Между релизами этот файл не правят: изменения — фрагментами в `changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "…"`), `scripts/release.py` собирает их сюда.

<!-- towncrier release notes start -->

## [0.3.1] - 2026-09-29

### Changed

- Инструменты разработки приведены к шаблону cli-generator v1.2.7 (release.py, хук docstring по `@app.command`, ty: предупреждения не валят гейт). Пакет не изменился.


## [0.3.0] - 2026-09-27

### Changed

- Дистрибутив переименован: `yandex-oauth` → `rb-yandex-oauth` (стандарт §10: `yandex-oauth` на PyPI — чужой пакет). Импорт `yandex_oauth` не меняется. Потребителям: новое имя в `dependencies` и в ключе `[tool.uv.sources]`, в существующем venv — `uv sync --reinstall-package <дистрибутив>` (см. README).

### Fixed

- `auth status --json`: `expires_at` — без микросекунд, как `checked_at`.


## [0.2.0] - 2026-09-27

### Added

- `yandex_oauth.health_check(store, check)` → `Health` (`status`, `expires_at`, `quota`, `message`) — делегат для `Provider.health_check()` инструментов по шаблону cli-generator: жёсткий лимит 10 с, 401/403 → `invalid`, сеть/429/5xx/таймаут → `unreachable`, значения секретов вычищаются из сообщений. Также `status_problems(report)` и ошибка `CredentialsUnhealthy`.

### Changed

- **Ломающее:** `auth status [--check] --json` из `make_auth_app` выдаёт отчёт §8 (`tool`, `version`, `checked_at`, `credentials[]`) в стандартном конверте вместо `{provider, authenticated, source, valid, …}`; при проблеме — exit 3, `ok: false` и `error` `CREDENTIALS_UNHEALTHY` рядом с отчётом. `--check` без проверочного запроса инструмента больше не ошибка, а статус `unchecked`. `status_exit_code` считает проблемой `invalid`/`expired` и у необязательного провайдера; `expires_at` — в UTC с `Z`; `source_ref` у keychain — `keychain service yandex-oauth:yandex`, при env-переопределении полей — `env` с перечислением всех мест.
- Стандарт релизов tools v1.2.0: канонический `scripts/release.py` из шаблона cli-generator (`--check` — весь гейт, включая сборку и установку wheel и osv-scanner), CI — один job с `release.py --check`; справка команд `auth` защищена хуками, контракт-тестом и снапшотами (§7), у каждой команды есть строка `Example:`.


## [0.1.2] - 2026-09-27

### Added

- `credential_status`, `status_report`, `status_exit_code` — отчёт `auth status --json` по контракту §8 стандарта tools (source, status, expires_at, живая проверка под `--check`) для переиспользования в ym, ywm и других инструментах.
- Вернулись CI (GitHub Actions: один job на ubuntu-24.04 и Python 3.11 — гейт, проверка фрагмента CHANGELOG, сборка и установка wheel, OSV-сканирование) и Dependabot (uv и github-actions раз в месяц, одним PR на экосистему).
- Работа без keychain (Linux-сервер, `doppler run`): если keychain недоступен, чтение не падает; при заданных `YANDEX_OAUTH_YANDEX_REFRESH_TOKEN`, `_CLIENT_ID`, `_CLIENT_SECRET` access-токен получается при первом запросе и обновляется в памяти процесса, ничего не записывая. Если не хватает части переменных — ошибка `CREDENTIALS_INCOMPLETE` (exit 3) с их именами.

### Changed

- README: одна схема имён переменных окружения — `YANDEX_OAUTH_YANDEX_*` основная, `YANDEX_CLIENT_ID/SECRET` и `<TOOL>_TOKEN` — legacy; исправлен устаревший docstring про `<CLI>_YANDEX_<FIELD>`.


## [0.1.1] - 2026-09-27

### Changed

- Версия пакета теперь берётся из git-тега `vX.Y.Z` (uv-dynamic-versioning), CHANGELOG собирается из фрагментов `changelog.d/` (towncrier), релиз — `uv run scripts/release.py patch|minor|major`. Потребителям: зависеть от тега (`tag = "v0.1.0"`), а не от `main`.


## [0.1.0] - 2026-09-17

Первая помеченная версия: общая OAuth-авторизация Яндекса для `ym`, `ywm` и других CLI — `Profile`, `CredentialStore` (keychain), `TokenStore` (автообновление), команда `auth`.
