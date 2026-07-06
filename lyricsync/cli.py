"""CLI lyricsync: автоопределение источника, показ синхронных текстов."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rich.console import Console

from . import __version__
from .config import Config, load_config, write_default_config
from .display import Display
from .extras import notify_track, romanize as romanize_text, scrobble
from .lyrics import Lyrics, export_lrc, fetch_lyrics
from .sources.base import PlaybackState
from .sources.detect import build_source


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lyricsync",
        description="Терминальные синхронные тексты песен в такт играющему треку.",
    )
    p.add_argument(
        "--source", choices=["auto", "mpris", "web"], default="auto",
        help="источник состояния воспроизведения (по умолчанию auto: MPRIS -> Web API)",
    )
    p.add_argument(
        "--player", default=None,
        help="имя MPRIS-плеера (напр. spotify, mpv). По умолчанию — первый доступный",
    )
    p.add_argument(
        "--export", nargs="?", const="AUTO", default=None, metavar="PATH",
        help="не показывать, а сохранить .lrc текущего трека (PATH или авто-имя)",
    )
    p.add_argument(
        "--no-typewriter", action="store_true",
        help="мгновенная смена строк вместо посимвольной печати",
    )
    p.add_argument(
        "--offset", type=float, default=None, metavar="SEC",
        help="сдвиг синхронизации, сек (>0 = текст раньше). В рантайме: +/- , 0 сброс",
    )
    p.add_argument("--no-notify", action="store_true", help="отключить desktop-уведомления")
    p.add_argument("--no-scrobble", action="store_true", help="не вести лог сыгранных треков")
    p.add_argument("--romanize", action="store_true", help="транслитерация нелатиницы (pykakasi)")
    p.add_argument("--no-cache", action="store_true", help="игнорировать кэш, всегда тянуть заново")
    p.add_argument("--config", type=Path, default=None, help="путь к config.toml")
    p.add_argument("--init-config", action="store_true", help="создать пример config.toml и выйти")
    p.add_argument("--version", action="version", version=f"lyricsync {__version__}")
    return p


def _apply_overrides(cfg: Config, args) -> Config:
    """Флаги CLI перекрывают config.toml."""
    if args.no_typewriter:
        cfg.typewriter = False
    if args.no_notify:
        cfg.notify = False
    if args.no_scrobble:
        cfg.scrobble = False
    if args.romanize:
        cfg.romanize = True
    if args.offset is not None:
        cfg.offset = args.offset
    return cfg


def _maybe_romanize(lyrics: Lyrics, cfg: Config) -> Lyrics:
    """Применяет романизацию к строкам, если включена."""
    if not cfg.romanize:
        return lyrics
    for line in lyrics.synced:
        line.text = romanize_text(line.text)
    if lyrics.plain:
        lyrics.plain = "\n".join(romanize_text(l) for l in lyrics.plain.splitlines())
    return lyrics


def _do_export(args, cfg: Config, console: Console) -> int:
    """Режим --export: получить и сохранить .lrc, без показа."""
    source = build_source(args.source, args.player, cfg.cache_dir)
    if source is None:
        console.print("[red]Нет доступного источника воспроизведения.[/red]")
        return 2
    state = source.poll()
    if state is None or not state.has_track:
        console.print("[yellow]Ничего не играет — нечего экспортировать.[/yellow]")
        return 1

    lyrics = fetch_lyrics(
        state.artist, state.title, cfg.cache_dir,
        providers=cfg.providers, use_cache=not args.no_cache,
    )
    if not lyrics.has_content:
        console.print(f"[yellow]Тексты не найдены: {state.track_key}[/yellow]")
        return 1

    if args.export == "AUTO":
        from .lyrics import _slug
        dest = Path(f"{_slug(state.track_key)}.lrc")
    else:
        dest = Path(args.export)
    export_lrc(lyrics, dest)
    kind = "синхронный" if lyrics.is_synced else "плоский"
    console.print(f"[green]Сохранено ({kind}):[/green] {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()

    if args.init_config:
        path = write_default_config(args.config)
        console.print(f"[green]Конфиг:[/green] {path}")
        return 0

    cfg = _apply_overrides(load_config(args.config), args)

    if args.export is not None:
        return _do_export(args, cfg, console)

    return _run_loop(args, cfg, console)


def _run_loop(args, cfg: Config, console: Console) -> int:
    """Главный цикл: ждать плеер -> тянуть тексты -> показывать -> при смене повторить."""
    source = build_source(args.source, args.player, cfg.cache_dir)
    if source is None:
        console.print(
            "[red]Нет доступного источника.[/red] Запусти плеер (Spotify/mpv) "
            "или задай Web API креды (SPOTIPY_CLIENT_ID/SECRET) и --source web."
        )
        return 2

    display = Display(cfg, console)
    last_key: str | None = None

    console.print("[dim]lyricsync запущен. Ctrl-C для выхода.[/dim]")
    try:
        state = _wait_for_track(source, console)
        while state is not None:
            # смена трека: уведомление + scrobble + новые тексты
            if state.track_key != last_key:
                last_key = state.track_key
                if cfg.notify:
                    notify_track(state)
                if cfg.scrobble:
                    scrobble(cfg.scrobble_path, state)
                console.clear()

            lyrics = fetch_lyrics(
                state.artist, state.title, cfg.cache_dir,
                providers=cfg.providers, use_cache=not args.no_cache,
            )
            lyrics = _maybe_romanize(lyrics, cfg)

            if not lyrics.has_content:
                console.clear()
                console.print(
                    f"[dim]♪ {state.artist} — {state.title}[/dim]\n\n"
                    f"[yellow]Тексты не найдены.[/yellow]"
                )
                # ждём смены трека
                state = _wait_change(source, state.track_key, console)
                continue

            # рендерим до смены трека/остановки
            new_state = display.run_track(source, lyrics, state)
            if new_state is None:
                state = _wait_for_track(source, console)
            else:
                state = new_state
    except KeyboardInterrupt:
        console.print("\n[dim]Пока![/dim]")
        return 0
    finally:
        source.close()

    console.print("[dim]Источник пропал. Выход.[/dim]")
    return 0


def _wait_for_track(source, console: Console) -> PlaybackState | None:
    """Ждёт, пока что-нибудь заиграет. None — если источник исчез надолго."""
    misses = 0
    while True:
        state = source.poll()
        if state is not None and state.has_track:
            return state
        misses += 1
        # источник может временно молчать; сдаёмся после ~30с тишины
        if misses > 120:
            return None
        time.sleep(0.25)


def _wait_change(source, current_key: str, console: Console) -> PlaybackState | None:
    """Ждёт смены трека относительно current_key."""
    while True:
        state = source.poll()
        if state is None:
            return _wait_for_track(source, console)
        if state.has_track and state.track_key != current_key:
            return state
        time.sleep(0.25)


if __name__ == "__main__":
    sys.exit(main())
