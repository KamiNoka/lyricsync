"""Опциональные фишки: уведомления, scrobble-лог, романизация (заглушка)."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from .sources.base import PlaybackState


def notify_track(state: PlaybackState) -> None:
    """Показывает desktop-уведомление о новом треке через notify-send."""
    if not shutil.which("notify-send"):
        return
    try:
        subprocess.run(
            [
                "notify-send",
                "-a", "lyricsync",
                "-i", "audio-x-generic",
                f"♪ {state.title}",
                state.artist,
            ],
            timeout=2,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def scrobble(path: Path, state: PlaybackState, ts: float | None = None) -> None:
    """Дописывает сыгранный трек в JSON-лог (список записей)."""
    entry = {
        "title": state.title,
        "artist": state.artist,
        "album": state.album,
        "player": state.player,
        "ts": ts if ts is not None else time.time(),
    }
    try:
        data = []
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except (ValueError, OSError):
                data = []
        data.append(entry)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ── Романизация (nice-to-have, требует pykakasi) ─────────────────────────────

_kks = None


def romanize(text: str) -> str:
    """Транслитерирует японский в ромадзи, если установлен pykakasi.

    Для других языков/латиницы возвращает текст как есть. Это заглушка-обёртка:
    полноценная поддержка (корейский/китайский) — задел на будущее.
    """
    global _kks
    if _kks is None:
        try:
            import pykakasi
            _kks = pykakasi.kakasi()
        except ImportError:
            _kks = False
    if not _kks:
        return text
    try:
        parts = _kks.convert(text)
        return " ".join(p["hepburn"] for p in parts).strip() or text
    except Exception:  # noqa: BLE001
        return text
