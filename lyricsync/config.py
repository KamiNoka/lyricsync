"""Конфигурация lyricsync: дефолты + чтение ~/.config/lyricsync/config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

# Пути по умолчанию (уважаем XDG)
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

DEFAULT_CONFIG_PATH = XDG_CONFIG / "lyricsync" / "config.toml"
DEFAULT_CACHE_DIR = XDG_CACHE / "lyricsync"


@dataclass
class Config:
    """Настройки приложения. Значения переопределяются config.toml и флагами CLI."""

    # Цвета (rich-совместимые: имена, #hex или "r,g,b" в градиенте)
    color_current: str = "bold #ff5f87"      # текущая строка — яркая
    color_next: str = "#8a8a8a"              # следующая — тускло
    color_prev: str = "#5f5f5f"              # предыдущая — ещё тусклее
    gradient: list[str] = field(default_factory=list)  # напр. ["#ff5f87", "#5fafff"]

    # Тайминг
    poll_hz: float = 10.0        # частота опроса позиции
    typewriter: bool = True      # печатать по символам или менять строку целиком

    # Пути
    cache_dir: Path = DEFAULT_CACHE_DIR

    # Поведение
    notify: bool = True          # notify-send на смену трека
    scrobble: bool = True        # лог сыгранных треков в JSON
    romanize: bool = False       # транслитерация нелатиницы (нужен pykakasi)

    # Провайдеры lyrics для syncedlyrics (пусто = все по умолчанию)
    providers: list[str] = field(default_factory=list)

    @property
    def scrobble_path(self) -> Path:
        return self.cache_dir / "scrobbles.json"


def load_config(path: Path | None = None) -> Config:
    """Читает config.toml поверх дефолтов. Отсутствие файла — не ошибка."""
    cfg = Config()
    cfg_path = path or DEFAULT_CONFIG_PATH

    if cfg_path.is_file():
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
        cfg = _merge(cfg, data)

    # Гарантируем существование кэш-директории
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _merge(cfg: Config, data: dict) -> Config:
    """Накладывает значения из toml на дефолтный Config (плоская секция [lyricsync] или корень)."""
    # Поддерживаем как корневые ключи, так и секцию [lyricsync]
    src = data.get("lyricsync", data)

    updates: dict = {}
    for key in (
        "color_current", "color_next", "color_prev", "gradient",
        "poll_hz", "typewriter", "notify", "scrobble", "romanize", "providers",
    ):
        if key in src:
            updates[key] = src[key]

    if "cache_dir" in src:
        updates["cache_dir"] = Path(src["cache_dir"]).expanduser()

    return replace(cfg, **updates)


def write_default_config(path: Path | None = None) -> Path:
    """Создаёт пример config.toml, если его ещё нет. Возвращает путь."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if not cfg_path.exists():
        cfg_path.write_text(_SAMPLE_TOML, encoding="utf-8")
    return cfg_path


_SAMPLE_TOML = """\
# ~/.config/lyricsync/config.toml
[lyricsync]
# Цвета в формате rich: имя, #hex или стиль ("bold #ff5f87")
color_current = "bold #ff5f87"
color_next = "#8a8a8a"
color_prev = "#5f5f5f"

# Градиент для текущей строки (список hex). Пусто = сплошной color_current.
gradient = []

# Частота опроса позиции (Гц)
poll_hz = 10.0

# Печатать построчно по символам (typewriter) или менять строку целиком
typewriter = true

# Уведомления и лог
notify = true
scrobble = true

# Транслитерация нелатинских текстов (требует pykakasi)
romanize = false

# Провайдеры lyrics (пусто = все). Напр.: ["Lrclib", "NetEase", "Musixmatch"]
providers = []

# cache_dir = "~/.cache/lyricsync"
"""
