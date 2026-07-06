# lyricsync

Терминальные **синхронные тексты песен**, которые печатаются в такт играющему
треку — как в тех TikTok-видео с «терминальными» лириксами.

Работает поверх любого MPRIS-плеера (Spotify, mpv, Clementine, браузер) без
авторизации, либо через Spotify Web API. Синхронные тексты (LRC) тянутся из
LRCLIB / Musixmatch / NetEase и кэшируются локально.

## Возможности

- **Два источника, автоопределение:** локальный MPRIS (по умолчанию, без авторизации
  и без обращений к сети за состоянием) → резерв на Spotify Web API.
- **Синхронные тексты** через `syncedlyrics` + прямой резерв на LRCLIB API.
- **Кэш** `.lrc` в `~/.cache/lyricsync/` — повторные проигрывания не перезапрашивают.
- **TikTok-эстетика на `rich`:** текущая строка крупно/цветом, соседние — тускло,
  karaoke-scroll, **typewriter** (посимвольная печать в такт таймкодам).
- **Умная синхронизация:** плавная интерполяция между опросами (~10 Гц), пересчёт при
  seek/skip, заморозка на паузе.
- **Плоский текст** показывается статичным блоком, если синхронных нет.
- Уведомления `notify-send` на смену трека, scrobble-лог, конфиг TOML.

## Установка

### Системные зависимости (Arch Linux)

```bash
sudo pacman -S playerctl python                 # MPRIS + Python
# опционально:
sudo pacman -S libnotify                         # уведомления (notify-send)
yay -S python-pykakasi                            # романизация японского (--romanize)
```

`playerctl` обязателен для MPRIS-режима. Для Spotify: официальный клиент или
`spotify-launcher` (AUR) — любой отдаёт MPRIS `org.mpris.MediaPlayer2.spotify`.

### Пакет

Arch блокирует системный pip (PEP 668), поэтому ставим в venv:

```bash
cd ~/musiclyric
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
# опциональные экстры:
.venv/bin/pip install -e '.[web]'        # Spotify Web API (spotipy)
.venv/bin/pip install -e '.[romanize]'   # pykakasi
```

Точка входа — `lyricsync` (в `.venv/bin/`).

## Использование

```bash
lyricsync                      # авто-источник, показать текст играющего трека
lyricsync --source mpris       # только локальный MPRIS
lyricsync --source web         # только Spotify Web API
lyricsync --player spotify     # конкретный MPRIS-плеер
lyricsync --no-typewriter      # мгновенная смена строк вместо печати
lyricsync --export song.lrc    # только сохранить .lrc, без показа
lyricsync --export             # то же, авто-имя файла
lyricsync --romanize           # транслитерация нелатиницы (нужен pykakasi)
lyricsync --init-config        # создать пример config.toml
```

`Ctrl-C` — выход.

## Синхронизация (если текст отстаёт/спешит)

Отставание обычно от **задержки звука** (Bluetooth-наушники дают 100–300 мс) или
кривых таймкодов в самом LRC. Лечится сдвигом (offset):

- **На лету** прямо во время показа: `+` / `-` двигают на 0.1 с (положительный =
  текст раньше), `0` — сброс. Текущий сдвиг виден в шапке (`⏱ +0.3s`).
- **Флагом:** `lyricsync --offset 0.3` (для Bluetooth обычно 0.2–0.3).
- **Постоянно:** `offset` в `config.toml`.
- Тег `[offset:±ms]` внутри LRC учитывается автоматически.

Если текст «дописывается» слишком поздно — уменьши `typewriter_speed` в конфиге
(0.5–0.6): строка допечатается раньше и не будет плестись за вокалом.

## Spotify Web API (нужен только для `--source web`)

MPRIS-режим Developer-приложение **не требует**. Web API нужен, только если Spotify
управляется удалённо или локального MPRIS нет. Создай приложение на
<https://developer.spotify.com/dashboard>, добавь redirect URI
`http://127.0.0.1:8888/callback` и задай переменные окружения:

```bash
export SPOTIPY_CLIENT_ID=xxxx
export SPOTIPY_CLIENT_SECRET=xxxx
export SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback   # необязательно
```

Первый запуск откроет браузер для OAuth; токен кэшируется в `~/.cache/lyricsync/`.

## Конфиг

`~/.config/lyricsync/config.toml` (создаётся через `--init-config`):

```toml
[lyricsync]
color_current = "bold #ff5f87"
color_next    = "#8a8a8a"
color_prev    = "#5f5f5f"
gradient      = ["#ff5f87", "#5fafff"]   # градиент текущей строки; пусто = сплошной
poll_hz       = 10.0
typewriter    = true
notify        = true
scrobble      = true
romanize      = false
providers     = []                        # напр. ["Lrclib", "NetEase"]
```

Флаги CLI перекрывают конфиг.

## Структура

```
lyricsync/
  cli.py            # argparse, главный цикл
  config.py         # config.toml + дефолты
  lyrics.py         # fetch (syncedlyrics/LRCLIB) + LRC-парсинг + кэш
  display.py        # rich Live: karaoke-scroll + typewriter + ресинхрон
  extras.py         # notify-send, scrobble-лог, романизация
  sources/
    base.py         # PlaybackState + Source ABC
    mpris.py        # generic MPRIS через playerctl
    webapi.py       # Spotify Web API (spotipy, ленивый OAuth)
    detect.py       # авто-фолбэк MPRIS → Web
```

## Заглушки / задел на будущее

- **ASCII album-art** idle-экран (через `chafa`) — не реализован.
- **Романизация** пока покрывает японский (pykakasi); корейский/китайский — задел.
```
