"""Источник через Spotify Web API (spotipy, OAuth).

Инициализируется лениво — только когда реально выбран/нужен. Требует
Spotify Developer app (Client ID/Secret) и разрешение user-read-playback-state.
Учётные данные берутся из переменных окружения:

    SPOTIPY_CLIENT_ID
    SPOTIPY_CLIENT_SECRET
    SPOTIPY_REDIRECT_URI   (по умолчанию http://127.0.0.1:8888/callback)
"""

from __future__ import annotations

import os

from .base import PlaybackState, Source

_SCOPE = "user-read-playback-state user-read-currently-playing"
_DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"


class WebApiSource(Source):
    """Опрашивает Spotify Web API. Тяжёлые импорты и OAuth — по требованию."""

    name = "web"

    def __init__(self, cache_dir=None):
        self._sp = None            # ленивый spotipy.Spotify
        self._init_failed = False  # чтобы не долбить OAuth повторно
        self._cache_dir = cache_dir

    def _ensure_client(self) -> bool:
        """Создаёт spotipy-клиент при первом обращении. False — если нельзя."""
        if self._sp is not None:
            return True
        if self._init_failed:
            return False

        client_id = os.environ.get("SPOTIPY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
        if not (client_id and client_secret):
            self._init_failed = True
            return False

        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
        except ImportError:
            self._init_failed = True
            return False

        redirect = os.environ.get("SPOTIPY_REDIRECT_URI", _DEFAULT_REDIRECT)
        cache_path = None
        if self._cache_dir is not None:
            cache_path = str(self._cache_dir / "spotify-token.json")

        try:
            auth = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect,
                scope=_SCOPE,
                cache_path=cache_path,
                open_browser=True,
            )
            self._sp = spotipy.Spotify(auth_manager=auth)
        except Exception:  # noqa: BLE001 — любая ошибка OAuth = недоступно
            self._init_failed = True
            return False
        return True

    def is_available(self) -> bool:
        # Доступен, если заданы креды и клиент поднимается. Сам вызов сети — в poll().
        if not (os.environ.get("SPOTIPY_CLIENT_ID") and os.environ.get("SPOTIPY_CLIENT_SECRET")):
            return False
        return self._ensure_client()

    def poll(self) -> PlaybackState | None:
        if not self._ensure_client():
            return None
        try:
            cur = self._sp.current_playback()
        except Exception:  # noqa: BLE001 — сетевые/токен ошибки не должны валить цикл
            return None

        if not cur or not cur.get("item"):
            return None

        item = cur["item"]
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        album = item.get("album", {}).get("name", "")

        return PlaybackState(
            title=item.get("name", ""),
            artist=artists,
            album=album,
            position=cur.get("progress_ms", 0) / 1000,
            length=item.get("duration_ms", 0) / 1000,
            status="Playing" if cur.get("is_playing") else "Paused",
            player="spotify-web",
        )
