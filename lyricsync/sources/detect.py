"""Автоопределение источника: MPRIS сначала, Web API в качестве резерва."""

from __future__ import annotations

from .base import Source
from .mpris import MprisSource
from .webapi import WebApiSource


def build_source(
    mode: str = "auto",
    player: str | None = None,
    cache_dir=None,
) -> Source | None:
    """Возвращает готовый источник по режиму.

    mode: "auto" | "mpris" | "web".
    player: имя MPRIS-плеера ("spotify") для фильтра, только для mpris/auto.
    """
    if mode == "mpris":
        src = MprisSource(player=player)
        return src if src.is_available() else None

    if mode == "web":
        src = WebApiSource(cache_dir=cache_dir)
        return src if src.is_available() else None

    # auto: MPRIS без авторизации предпочтительнее
    mpris = MprisSource(player=player)
    if mpris.is_available():
        return mpris

    web = WebApiSource(cache_dir=cache_dir)
    if web.is_available():
        return web

    return None
