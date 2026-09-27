# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
Между релизами этот файл не правят: изменения — фрагментами в `changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "…"`), `scripts/release.py` собирает их сюда.

<!-- towncrier release notes start -->

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
