"""Generic MPRIS-источник через playerctl CLI.

Работает с любым MPRIS-совместимым плеером (Spotify, mpv, Clementine,
браузеры), не требует авторизации и не ходит в сеть за состоянием.
"""

from __future__ import annotations

import shutil
import subprocess

from .base import PlaybackState, Source

# Один вызов playerctl отдаёт все поля разом. Разделитель — маловероятный в метаданных.
_SEP = "\x1f"
_FIELDS = (
    "{{playerName}}",
    "{{status}}",
    "{{position}}",      # микросекунды
    "{{mpris:length}}",  # микросекунды
    "{{xesam:title}}",
    "{{xesam:artist}}",
    "{{xesam:album}}",
)
_FORMAT = _SEP.join(_FIELDS)


def _us_to_s(raw: str) -> float:
    """Микросекунды-строка -> секунды. Пусто/мусор -> 0."""
    raw = raw.strip()
    if not raw:
        return 0.0
    try:
        return int(raw) / 1_000_000
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return 0.0


class MprisSource(Source):
    """Читает состояние через `playerctl`. player=None -> первый доступный."""

    name = "mpris"

    def __init__(self, player: str | None = None):
        # player — имя MPRIS-плеера ("spotify"); None = автоматически первый
        self.player = player
        self._bin = shutil.which("playerctl")

    def is_available(self) -> bool:
        if not self._bin:
            return False
        players = self._list_players()
        if not players:
            return False
        if self.player:
            return any(p == self.player or p.startswith(self.player + ".") for p in players)
        return True

    def _list_players(self) -> list[str]:
        try:
            out = subprocess.run(
                [self._bin, "-l"],
                capture_output=True, text=True, timeout=2,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        if out.returncode != 0:
            return []
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]

    def _args(self) -> list[str]:
        args = [self._bin]
        if self.player:
            args += ["-p", self.player]
        return args

    def poll(self) -> PlaybackState | None:
        if not self._bin:
            return None
        try:
            out = subprocess.run(
                self._args() + ["metadata", "--format", _FORMAT],
                capture_output=True, text=True, timeout=2,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if out.returncode != 0 or not out.stdout.strip():
            return None

        parts = out.stdout.rstrip("\n").split(_SEP)
        # Ожидаем 7 полей; добиваем пустыми на случай отсутствующих тегов
        while len(parts) < 7:
            parts.append("")
        player, status, position, length, title, artist, album = parts[:7]

        if not (title or artist):
            return None

        return PlaybackState(
            title=title.strip(),
            artist=artist.strip(),
            album=album.strip(),
            position=_us_to_s(position),
            length=_us_to_s(length),
            status=status.strip() or "Stopped",
            player=player.strip() or (self.player or "mpris"),
        )
