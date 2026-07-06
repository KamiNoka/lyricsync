"""Терминальный рендер в стиле TikTok: karaoke-scroll + typewriter на rich.Live."""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from .config import Config
from .lyrics import Lyrics, LyricLine
from .sources.base import PlaybackState, Source


# ── Движок синхронизации ─────────────────────────────────────────────────────

@dataclass
class LineView:
    """Что показать в конкретный момент."""
    index: int              # индекс текущей строки (-1 = ещё не началось)
    reveal: int             # сколько символов текущей строки показать (typewriter)
    line: LyricLine | None  # текущая строка


class LyricEngine:
    """По позиции трека вычисляет текущую строку и прогресс печати."""

    def __init__(self, lyrics: Lyrics):
        self.lines = lyrics.synced

    def _index_at(self, position: float) -> int:
        """Индекс последней строки, чьё время <= position."""
        lo, hi = 0, len(self.lines)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.lines[mid].time <= position:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1

    def view_at(self, position: float, typewriter: bool) -> LineView:
        idx = self._index_at(position)
        if idx < 0:
            return LineView(index=-1, reveal=0, line=None)

        line = self.lines[idx]
        if not typewriter:
            return LineView(index=idx, reveal=len(line.text), line=line)

        # Длительность текущей строки = до следующего тайм-тега (или 3с в конце)
        if idx + 1 < len(self.lines):
            dur = self.lines[idx + 1].time - line.time
        else:
            dur = 3.0
        dur = max(dur, 0.1)

        elapsed = position - line.time
        # Печатаем не всю длительность, а первые ~85% — чтобы строка «дочиталась»
        # до появления следующей и не мигала.
        frac = min(1.0, elapsed / (dur * 0.85))
        reveal = int(round(frac * len(line.text)))
        return LineView(index=idx, reveal=reveal, line=line)


# ── Рендер ───────────────────────────────────────────────────────────────────

class Renderer:
    """Собирает rich-группу: прошлое сверху, текущее крупно, будущее снизу."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _gradient_text(self, s: str) -> Text:
        """Красит строку градиентом между цветами cfg.gradient."""
        colors = self.cfg.gradient
        txt = Text()
        n = max(len(s), 1)
        for i, ch in enumerate(s):
            color = _lerp_color(colors, i / n)
            txt.append(ch, style=f"bold {color}")
        return txt

    def _current_text(self, s: str) -> Text:
        if self.cfg.gradient and s:
            return self._gradient_text(s)
        return Text(s, style=self.cfg.color_current)

    def render(self, view: LineView, engine: LyricEngine, state: PlaybackState) -> Group:
        blocks: list = []

        # Заголовок трека
        header = Text(f"♪ {state.artist} — {state.title}", style="dim italic")
        blocks.append(Align.center(header))
        blocks.append(Text(""))

        # Только текущая строка: белый текст, контур-сердечки по краям
        if view.line is not None:
            shown = view.line.text[: view.reveal]
            cur = Text()
            cur.append("♡ ", style="white")
            cur.append(shown, style="white")
            # мигающий курсор, пока строка ещё печатается и играет
            if state.is_playing and view.reveal < len(view.line.text):
                cur.append("▌", style="dim")
            cur.append(" ♡", style="white")
            blocks.append(Align.center(cur))
        else:
            blocks.append(Align.center(Text("♡", style="white")))

        # Индикатор паузы
        if not state.is_playing:
            blocks.append(Text(""))
            blocks.append(Align.center(Text("⏸ paused", style="dim")))

        return Group(*blocks)

    def render_plain(self, lyrics: Lyrics, state: PlaybackState) -> Group:
        """Статичный блок для несинхронизированного текста."""
        blocks = [
            Align.center(Text(f"♪ {state.artist} — {state.title}", style="dim italic")),
            Text(""),
            Align.center(Text("(синхронизации нет — статичный текст)", style="dim")),
            Text(""),
        ]
        for line in lyrics.plain.splitlines():
            blocks.append(Align.center(Text(line, style=self.cfg.color_next)))
        return Group(*blocks)


def _lerp_color(colors: list[str], t: float) -> str:
    """Линейная интерполяция по списку hex-цветов. t в [0,1]."""
    if not colors:
        return "#ffffff"
    if len(colors) == 1:
        return colors[0]
    t = min(max(t, 0.0), 1.0)
    seg = t * (len(colors) - 1)
    i = int(seg)
    if i >= len(colors) - 1:
        return colors[-1]
    frac = seg - i
    c1 = _hex_rgb(colors[i])
    c2 = _hex_rgb(colors[i + 1])
    r = round(c1[0] + (c2[0] - c1[0]) * frac)
    g = round(c1[1] + (c2[1] - c1[1]) * frac)
    b = round(c1[2] + (c2[2] - c1[2]) * frac)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ── Главный цикл ─────────────────────────────────────────────────────────────

class Display:
    """Управляет циклом опроса и живым рендером одного трека.

    Возвращает управление, когда трек меняется (нужно перезагрузить lyrics)
    или воспроизведение прекращается.
    """

    def __init__(self, cfg: Config, console: Console | None = None):
        self.cfg = cfg
        self.console = console or Console()
        self.renderer = Renderer(cfg)

    def run_track(
        self,
        source: Source,
        lyrics: Lyrics,
        initial: PlaybackState,
    ) -> PlaybackState | None:
        """Крутит рендер, пока играет initial-трек.

        Возвращает новое состояние при смене трека (для перезагрузки),
        либо None если воспроизведение остановилось/источник пропал.
        """
        interval = 1.0 / max(self.cfg.poll_hz, 1.0)

        # Несинхронизированный текст — просто печатаем статикой и ждём смены трека
        if not lyrics.is_synced:
            return self._run_plain(source, lyrics, initial, interval)

        engine = LyricEngine(lyrics)
        last_state = initial
        # База для интерполяции позиции между опросами
        base_pos = initial.position
        base_mono = time.monotonic()
        # Независимый таймер опроса источника (НЕ завязан на base_mono!)
        last_poll = 0.0

        with Live(
            console=self.console,
            refresh_per_second=max(self.cfg.poll_hz, 15.0),
            screen=False,
            transient=False,
        ) as live:
            while True:
                now = time.monotonic()

                # Опрашиваем источник строго раз в interval, независимо от паузы
                if now - last_poll >= interval:
                    last_poll = now
                    fresh = source.poll()
                    if fresh is None:
                        return None
                    # смена трека -> выходим на перезагрузку lyrics
                    if fresh.track_key != initial.track_key:
                        return fresh

                    was_playing = last_state.is_playing
                    # ресинхрон при seek/skip или смене play/pause
                    expected = base_pos + (now - base_mono) if was_playing else base_pos
                    drift = abs(expected - fresh.position)
                    if drift > 0.5 or fresh.is_playing != was_playing:
                        base_pos = fresh.position
                        base_mono = now
                    last_state = fresh

                # Текущая позиция: на паузе — заморожена, иначе экстраполируем
                if last_state.is_playing:
                    pos = base_pos + (now - base_mono)
                else:
                    pos = base_pos

                view = engine.view_at(pos, self.cfg.typewriter)
                live.update(self._centered(self.renderer.render(view, engine, last_state)))

                time.sleep(0.03)

    def _centered(self, body: Group) -> Align:
        """Центрирует контент по вертикали и горизонтали на всю высоту терминала."""
        return Align.center(body, vertical="middle", height=self.console.size.height)

    def _run_plain(self, source, lyrics, initial, interval) -> PlaybackState | None:
        """Статичный текст: рисуем один раз, ждём смены трека."""
        self.console.clear()
        self.console.print(self.renderer.render_plain(lyrics, initial))
        while True:
            time.sleep(max(interval, 0.5))
            fresh = source.poll()
            if fresh is None:
                return None
            if fresh.track_key != initial.track_key:
                return fresh
