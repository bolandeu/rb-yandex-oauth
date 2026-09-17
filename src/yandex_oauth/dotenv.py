"""Запасной источник переменных: `.env` рядом с инструментом.

В репозиториях инструментов `.env` — gitignored-симлинк на общий файл
`~/Projects/credentials/.env.shared`, где лежат токены и OAuth-приложение для
всех Яндекс-инструментов. Уже заданные переменные окружения не
перезаписываются; запоминаем путь и какие ключи пришли именно из файла —
чтобы `auth status`/`doctor` показывали источник `dotenv`, а `auth login`
предлагал обновить протухший токен прямо в файле.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PATH: Path | None = None
KEYS: frozenset[str] = frozenset()


def load(path: str | Path | None) -> Path | None:
    """Подгрузить файл (обычно результат `dotenv.find_dotenv()` из cli.py инструмента)."""
    global PATH, KEYS
    if not path or not Path(path).is_file():
        PATH, KEYS = None, frozenset()
        return None
    KEYS = frozenset(k for k, v in dotenv_values(path).items() if v is not None and k not in os.environ)
    load_dotenv(path)
    PATH = Path(path)
    return PATH


def provided(key: str) -> bool:
    """Пришла ли переменная именно из .env (а не была задана в окружении заранее)."""
    return key in KEYS


def update_line(path: Path, key: str, value: str) -> Path:
    """Заменить строку `KEY=…` в файле (симлинк разыменовывается — пишем в общий
    .env.shared), остальное содержимое не трогая. Если строки нет — добавить в конец."""
    real = path.resolve()
    lines = real.read_text(encoding="utf-8").splitlines(keepends=True)
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}\n"
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{prefix}{value}\n")
    real.write_text("".join(lines), encoding="utf-8")
    return real
