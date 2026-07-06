"""Общий контракт источников воспроизведения."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackState:
    """Снимок состояния плеера в конкретный момент."""

    title: str
    artist: str
    album: str = ""
    position: float = 0.0        # текущая позиция, секунды
    length: float = 0.0          # длительность трека, секунды (0 = неизвестно)
    status: str = "Stopped"      # "Playing" | "Paused" | "Stopped"
    player: str = ""             # имя источника (spotify, chromium, web...)

    @property
    def is_playing(self) -> bool:
        return self.status == "Playing"

    @property
    def track_key(self) -> str:
        """Ключ трека для сравнения и кэша."""
        return f"{self.artist} — {self.title}".strip(" —")

    @property
    def has_track(self) -> bool:
        return bool(self.title or self.artist)


class Source(ABC):
    """Абстрактный источник состояния воспроизведения."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Доступен ли источник прямо сейчас (плеер запущен / есть авторизация)."""

    @abstractmethod
    def poll(self) -> PlaybackState | None:
        """Текущее состояние или None, если ничего не играет / источник пропал."""

    def close(self) -> None:  # noqa: B027 — необязательный хук
        """Освобождение ресурсов. По умолчанию ничего."""
