"""Получение и разбор текстов песен.

Порядок: локальный кэш -> syncedlyrics -> прямой LRCLIB API.
Синхронные тексты хранятся в LRC-формате, парсятся в список (время, строка).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests

LRCLIB_API = "https://lrclib.net/api/get"
_USER_AGENT = "lyricsync/0.1 (https://github.com/kami/lyricsync)"

# [mm:ss.xx] или [mm:ss] — тайм-теги LRC. В строке может быть несколько.
_TIME_TAG = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# [offset:±ms] — общий сдвиг синхронизации, встроенный в LRC.
_OFFSET_TAG = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)


@dataclass
class LyricLine:
    """Одна синхронизированная строка."""
    time: float   # секунды от начала трека
    text: str


@dataclass
class Lyrics:
    """Результат: либо синхронные строки, либо плоский текст."""
    synced: list[LyricLine]           # пусто -> синхронизации нет
    plain: str = ""                   # запасной невыровненный текст
    source: str = ""                  # откуда взяли (cache/syncedlyrics/lrclib)
    track_key: str = ""

    @property
    def is_synced(self) -> bool:
        return bool(self.synced)

    @property
    def has_content(self) -> bool:
        return bool(self.synced or self.plain.strip())


# ── Кэш ────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    """Безопасное имя файла из 'Artist - Title'."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "unknown"


def cache_path_for(cache_dir: Path, artist: str, title: str) -> Path:
    return cache_dir / f"{_slug(f'{artist} - {title}')}.lrc"


# ── Парсинг LRC ──────────────────────────────────────────────────────────────

def parse_lrc(content: str) -> list[LyricLine]:
    """Разбирает LRC-текст в отсортированный список LyricLine.

    Поддерживает несколько тайм-тегов на строке и пропускает метадату ([ar:], [ti:]).
    """
    # Тег [offset:±ms] — общий сдвиг из самого LRC. Положительный = строки раньше.
    file_offset = 0.0
    m_off = _OFFSET_TAG.search(content)
    if m_off:
        try:
            file_offset = int(m_off.group(1)) / 1000.0
        except ValueError:
            file_offset = 0.0

    lines: list[LyricLine] = []
    for raw in content.splitlines():
        tags = list(_TIME_TAG.finditer(raw))
        if not tags:
            continue
        # текст = всё после последнего тайм-тега
        text = raw[tags[-1].end():].strip()
        for m in tags:
            mm = int(m.group(1))
            ss = int(m.group(2))
            frac = m.group(3) or "0"
            # доли: 2 знака = сотые, 3 = тысячные
            frac_val = int(frac) / (10 ** len(frac))
            t = mm * 60 + ss + frac_val - file_offset
            lines.append(LyricLine(time=max(0.0, t), text=text))

    lines.sort(key=lambda l: l.time)
    return lines


# ── Получение ────────────────────────────────────────────────────────────────

def fetch_lyrics(
    artist: str,
    title: str,
    cache_dir: Path,
    providers: list[str] | None = None,
    prefer_synced: bool = True,
    use_cache: bool = True,
) -> Lyrics:
    """Возвращает Lyrics для трека. Пробует кэш, затем сеть."""
    key = f"{artist} — {title}".strip(" —")
    path = cache_path_for(cache_dir, artist, title)

    # 1. Кэш
    if use_cache and path.is_file():
        content = path.read_text(encoding="utf-8")
        synced = parse_lrc(content)
        return Lyrics(
            synced=synced,
            plain="" if synced else content,
            source="cache",
            track_key=key,
        )

    # 2. syncedlyrics (LRCLIB, Musixmatch, NetEase...)
    lrc = _try_syncedlyrics(artist, title, providers, prefer_synced)

    # 3. Прямой LRCLIB API как запасной
    if not lrc:
        lrc = _try_lrclib(artist, title)

    if not lrc:
        return Lyrics(synced=[], plain="", source="none", track_key=key)

    synced = parse_lrc(lrc)
    # Сохраняем в кэш (и синхронный LRC, и плоский текст)
    if use_cache:
        try:
            path.write_text(lrc, encoding="utf-8")
        except OSError:
            pass

    return Lyrics(
        synced=synced,
        plain="" if synced else lrc,
        source="lrclib" if not synced else "syncedlyrics",
        track_key=key,
    )


def _try_syncedlyrics(
    artist: str, title: str, providers: list[str] | None, prefer_synced: bool
) -> str | None:
    """Запрос через библиотеку syncedlyrics. Возвращает сырой LRC/текст или None."""
    try:
        import syncedlyrics
    except ImportError:
        return None

    term = f"{title} {artist}".strip()
    try:
        result = syncedlyrics.search(
            term,
            synced_only=prefer_synced,
            providers=providers or [],
        )
    except Exception:  # noqa: BLE001 — сетевые/парсинг ошибки провайдеров
        result = None

    # Если синхронных не нашли — пробуем ещё раз, разрешая плоский текст
    if not result and prefer_synced:
        try:
            result = syncedlyrics.search(term, plain_only=False, providers=providers or [])
        except Exception:  # noqa: BLE001
            result = None

    return result or None


def _try_lrclib(artist: str, title: str) -> str | None:
    """Прямой запрос к публичному LRCLIB API. Возвращает LRC либо plain."""
    try:
        resp = requests.get(
            LRCLIB_API,
            params={"artist_name": artist, "track_name": title},
            headers={"User-Agent": _USER_AGENT},
            timeout=8,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    # syncedLyrics -> LRC; иначе plainLyrics
    synced = data.get("syncedLyrics")
    if synced:
        return synced
    plain = data.get("plainLyrics")
    return plain or None


# ── Экспорт ──────────────────────────────────────────────────────────────────

def export_lrc(lyrics: Lyrics, dest: Path) -> None:
    """Сохраняет lyrics как .lrc (синхронный) или .txt-подобный файл."""
    if lyrics.is_synced:
        lines = [f"[{_fmt_time(l.time)}]{l.text}" for l in lyrics.synced]
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        dest.write_text(lyrics.plain, encoding="utf-8")


def _fmt_time(t: float) -> str:
    mm = int(t // 60)
    ss = t - mm * 60
    return f"{mm:02d}:{ss:05.2f}"
