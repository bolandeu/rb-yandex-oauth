# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
Между релизами этот файл не правят: изменения — фрагментами в `changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "…"`), `scripts/release.py` собирает их сюда.

<!-- towncrier release notes start -->

## [0.1.0] - 2026-09-17

Первая помеченная версия: общая OAuth-авторизация Яндекса для `ym`, `ywm` и других CLI — `Profile`, `CredentialStore` (keychain), `TokenStore` (автообновление), команда `auth`.
