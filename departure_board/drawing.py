"""All draw_* functions for the RGB LED matrix (except game-specific ones)."""
from __future__ import annotations

import queue
import random
import sys
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

import fetch_departures as fd

from .font import ADV_WIDTH, BITMAP, CHAR_H, CHAR_SPACING, CHAR_W, DESCENDERS, LINE_SPACING
from .constants import BOARD_MARGIN, DEST_MINS_GAP, LINE_ID_DEST_GAP, RIGHT_MARGIN
from .renderer import Renderer, make_draw_helpers
from .weather import ICON_SIZE, WEATHER_ICONS, WeatherData


def draw_frame(off, matrix, renderer: Renderer, rows: List[Dict[str, Any]], header_text: str, city_reference: str, now_text: Optional[str] = None):
    """Draw a complete departure frame.

    off: off-screen canvas (re-used each frame)
    rows: departures (empty => blank list area)
    header_text: text to render in the header (e.g., "Basel SBB -> Zurich HB")
    city_reference: station name used for same-city destination stripping
    """
    # Clear quickly using Fill (avoid per-pixel loops that cost CPU and can stutter PWM thread)
    off.Fill(0, 0, 0)
    amber = (255, 140, 0)

    r = renderer

    # Layout constants:
    HEADER_BASELINE_Y = 2
    RULE_Y = HEADER_BASELINE_Y + CHAR_H + 3  # 2 + 7 + 3 = 12
    DEPARTURES_START_Y = RULE_Y + 1 + 4      # 12 + 1 + 4 = 17
    cap = r.rows_capacity(DEPARTURES_START_Y)
    prepared = r.prepare_rows(rows, city_reference, cap)

    # Drawing helpers --------------------------------------------------
    def glyph_width(ch: str) -> int:
        return r.glyph_width(ch)

    def draw_glyph(x: int, y: int, ch: str):
        bmp = BITMAP.get(ch, BITMAP[' '])
        # Descender whole glyph downward shift per demo for specific chars
        whole_offset = 2 if ch in DESCENDERS else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bmp):
            for dx, bit in enumerate(brow[:glyph_width(ch)]):
                if bit:
                    off.SetPixel(x+dx, y+dy+whole_offset, *amber)

    def measure(text: str) -> int:
        return r.measure(text)

    def draw_text(x: int, y: int, text: str):
        cur = x
        for i, ch in enumerate(text):
            draw_glyph(cur, y, ch)
            cur += glyph_width(ch)
            if i != len(text) - 1:
                cur += CHAR_SPACING
        return cur - x

    # Header: time right, stop name left truncated, 1px padding on each side.
    now_txt = now_text if now_text is not None else datetime.now().strftime('%H:%M')
    inner_left = BOARD_MARGIN + 1
    # Header-specific left margin for stop name: 3px from the edge (includes 1px border + 2px padding)
    header_left = BOARD_MARGIN + 2
    inner_right = r.cols - BOARD_MARGIN - 1  # last drawable column inside header margin
    inner_width = r.cols - 2 * BOARD_MARGIN - 1
    time_w = measure(now_txt)
    # leave 1px gap before inner_right
    time_x = inner_right - time_w  # already leaves gap since inner_right not drawn on
    # Determine stop name similarly to demo logic
    station_city = fd._station_city(city_reference)
    # Derive a display-friendly header: if it contains a comma, prefer the part after the comma
    display_header = header_text.strip()
    if ',' in display_header:
        parts = [p.strip() for p in display_header.split(',')]
        if len(parts) >= 2:
            stop_name = parts[1] or parts[0]
        else:
            stop_name = parts[0]
    else:
        stop_name = display_header
    if station_city and stop_name.lower() == station_city.lower():
        alts = [p.strip() for p in header_text.split(',') if p.strip().lower() != station_city.lower()]
        if alts:
            stop_name = alts[-1]

    # Truncate stop name to fit before time with at least 1px spacing
    # Use header_left to achieve a 3px left margin (vs. 1px general board margin)
    available_w = time_x - header_left - CHAR_SPACING
    if available_w < 0:
        available_w = 0

    def truncate(text: str, max_w: int) -> str:
        acc = []
        cur = 0
        for ch in text:
            w = glyph_width(ch)
            add = w if not acc else CHAR_SPACING + w
            if cur + add > max_w:
                break
            acc.append(ch)
            cur += add
        return ''.join(acc)

    stop_name = truncate(stop_name, available_w)

    header_baseline = HEADER_BASELINE_Y
    # Draw stop name with 3px left margin
    draw_text(header_left, header_baseline, stop_name)
    draw_text(time_x, header_baseline, now_txt)

    # Rule line
    rule_y = RULE_Y
    for x in range(0, r.cols):  # full-width line (ignores horizontal margins)
        off.SetPixel(x, rule_y, *amber)

    # Departure rows start at:
    rows_start_y = DEPARTURES_START_Y
    line_height = CHAR_H + LINE_SPACING
    for idx, row in enumerate(prepared):
        y = rows_start_y + idx * line_height
        ident_col_chars = int(row['ident_col_chars'])
        ident_w = measure('X' * ident_col_chars)
        ident = row['ident_display']
        # Right-align ident within the fixed column width
        pad = max(0, ident_w - measure(ident))
        draw_text(inner_left + pad, y, ident)
        dest_start_x = inner_left + ident_w + LINE_ID_DEST_GAP
        draw_text(dest_start_x, y, row['dest'])
        mins = row['mins']
        digits_w = measure(mins)
        apostrophe_w = glyph_width("'")
        total_minutes_w = digits_w + CHAR_SPACING + apostrophe_w + RIGHT_MARGIN
        digits_start_x = inner_left + inner_width - total_minutes_w
        apostrophe_x = inner_left + inner_width - RIGHT_MARGIN - apostrophe_w
        # Draw digits
        x_cur = digits_start_x
        for i, dch in enumerate(mins):
            draw_glyph(x_cur, y, dch)
            x_cur += glyph_width(dch)
            if i != len(mins) - 1:
                x_cur += CHAR_SPACING
        # Apostrophe after spacing
        # ensure one spacing pixel exists (already accounted in total width calc)
        draw_glyph(apostrophe_x, y, "'")

    return matrix.SwapOnVSync(off)


def draw_weather_frame(off, matrix, renderer: Renderer, header_text: str, weather: Optional[WeatherData], now_text: Optional[str] = None):
    """Draw a weather screen with header and a simple pictogram."""
    off.Fill(0, 0, 0)
    amber = (255, 140, 0)
    r = renderer

    HEADER_BASELINE_Y = 2
    RULE_Y = HEADER_BASELINE_Y + CHAR_H + 3
    CONTENT_Y = RULE_Y + 1 + 6

    def glyph_width(ch: str) -> int:
        return r.glyph_width(ch)

    def draw_glyph(x: int, y: int, ch: str):
        bmp = BITMAP.get(ch, BITMAP[' '])
        whole_offset = 2 if ch in DESCENDERS else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bmp):
            for dx, bit in enumerate(brow[:glyph_width(ch)]):
                if bit:
                    off.SetPixel(x+dx, y+dy+whole_offset, *amber)

    def measure(text: str) -> int:
        return r.measure(text)

    def draw_text(x: int, y: int, text: str):
        cur = x
        for i, ch in enumerate(text):
            draw_glyph(cur, y, ch)
            cur += glyph_width(ch)
            if i != len(text) - 1:
                cur += CHAR_SPACING
        return cur - x

    def truncate(text: str, max_w: int) -> str:
        acc = []
        cur = 0
        for ch in text:
            w = glyph_width(ch)
            add = w if not acc else CHAR_SPACING + w
            if cur + add > max_w:
                break
            acc.append(ch)
            cur += add
        return ''.join(acc)

    # Header
    now_txt = now_text if now_text is not None else datetime.now().strftime('%H:%M')
    inner_left = BOARD_MARGIN + 2
    inner_right = r.cols - BOARD_MARGIN - 1
    inner_width = r.cols - 2 * BOARD_MARGIN - 1
    time_w = measure(now_txt)
    time_x = inner_right - time_w
    city = header_text.strip()
    city = truncate(city, max(0, time_x - inner_left - CHAR_SPACING))
    draw_text(inner_left, HEADER_BASELINE_Y, city)
    draw_text(time_x, HEADER_BASELINE_Y, now_txt)

    # Rule
    for x in range(0, r.cols):
        off.SetPixel(x, RULE_Y, *amber)

    # Icon painter from predefined bitmap
    def draw_icon(x0: int, y0: int, kind: str):
        bmp = WEATHER_ICONS.get(kind) or WEATHER_ICONS.get('cloudy')
        if not bmp:
            return
        for yy, row in enumerate(bmp):
            for xx, ch in enumerate(row[:ICON_SIZE]):
                if ch == '1':
                    off.SetPixel(x0 + xx, y0 + yy, *amber)

    # Content text
    # Left column: current temp above the icon
    kind = weather['kind'] if weather else 'cloudy'
    left_x = BOARD_MARGIN + 2
    nowt = weather.get('now_temp') if weather else None
    cur_temp = f"{nowt}\u00b0" if nowt is not None else "--\u00b0"
    draw_text(left_x, CONTENT_Y, truncate(cur_temp, r.cols))
    draw_icon(left_x, CONTENT_Y + CHAR_H + 2, kind)

    # Right column: Min/Max:, Wind, Real feel
    text_x = left_x + ICON_SIZE + 8
    tmin = weather.get('tmin') if weather else None
    tmax = weather.get('tmax') if weather else None
    wind = weather.get('wind') if weather else None
    app = weather.get('app_temp') if weather else None

    line1 = f"Min/Max: {tmin if tmin is not None else '--'}\u00b0/{tmax if tmax is not None else '--'}\u00b0"
    line2 = f"Wind: {wind if wind is not None else '--'}" + (" km/h" if wind is not None else "")
    line3 = f"Real feel: {app if app is not None else '--'}\u00b0"

    draw_text(text_x, CONTENT_Y, truncate(line1, max(0, r.cols - text_x - BOARD_MARGIN)))
    draw_text(text_x, CONTENT_Y + CHAR_H + 3, truncate(line2, max(0, r.cols - text_x - BOARD_MARGIN)))
    draw_text(text_x, CONTENT_Y + 2*(CHAR_H + 3), truncate(line3, max(0, r.cols - text_x - BOARD_MARGIN)))

    return matrix.SwapOnVSync(off)


def screensaver_random_pos(renderer: Renderer, now_txt: str) -> Tuple[int, int]:
    """Return a random (x, y) that keeps the time string fully on screen with a 3px border."""
    time_w = renderer.measure(now_txt)
    min_x = 3
    max_x = max(min_x, renderer.cols - time_w - 3)
    min_y = 3
    max_y = max(min_y, renderer.rows - CHAR_H - 3)
    return (random.randint(min_x, max_x), random.randint(min_y, max_y))


def draw_screensaver_frame(off, matrix, renderer: Renderer, now_text: Optional[str] = None, pos: Optional[Tuple[int, int]] = None, dim: int = 60):
    """Draw a minimal screensaver: just the current time at the given position (or centered).

    dim: apparent brightness 0-100 as a fraction of the panel's full output at the current
         hardware brightness. Pixel values are scaled to compensate so that dim=40 means
         40% of maximum visible brightness, not 40% of 255 further attenuated by hardware.
         matrix.brightness is never changed (avoids hardware reset side-effects).
    """
    off.Fill(0, 0, 0)
    # Compensate for hardware brightness so dim=40 means 40% of the panel's full output,
    # not 40% of 255 further attenuated by hardware brightness (which would be ~24% effective).
    h_brightness = max(1, getattr(matrix, 'brightness', 100))
    raw_scale = max(0.0, min(100.0, dim)) / h_brightness
    scale = min(1.0, raw_scale)
    amber = (int(255 * scale), int(140 * scale), 0)
    r = renderer

    now_txt = now_text if now_text is not None else datetime.now().strftime('%H:%M')

    def glyph_width(ch: str) -> int:
        return r.glyph_width(ch)

    def draw_glyph(x: int, y: int, ch: str) -> None:
        bmp = BITMAP.get(ch, BITMAP[' '])
        whole_offset = 2 if ch in DESCENDERS else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bmp):
            for dx, bit in enumerate(brow[:glyph_width(ch)]):
                if bit:
                    off.SetPixel(x + dx, y + dy + whole_offset, *amber)

    if pos is not None:
        x, y = pos
    else:
        time_w = r.measure(now_txt)
        x = (r.cols - time_w) // 2
        y = (r.rows - CHAR_H) // 2

    cur = x
    for i, ch in enumerate(now_txt):
        draw_glyph(cur, y, ch)
        cur += glyph_width(ch)
        if i != len(now_txt) - 1:
            cur += CHAR_SPACING

    return matrix.SwapOnVSync(off)


def _normalize_for_display(text: str) -> str:
    """Map characters not in the font to their closest renderable equivalent.

    1. If the character is already in the font, keep it.
    2. Try NFD decomposition (strips diacritics): u\u0301->u, e\u0301->e, etc.
    3. Try the opposite case as a last resort.
    4. Skip characters that still can't be mapped.
    """
    result = []
    for ch in text:
        if ch in BITMAP:
            result.append(ch)
            continue
        # NFD strips combining diacritical marks (U+0300-U+036F)
        nfd = unicodedata.normalize('NFD', ch)
        base = nfd[0]
        if base in BITMAP:
            result.append(base)
            continue
        alt = base.upper() if base.islower() else base.lower()
        if alt in BITMAP:
            result.append(alt)
            continue
        # Unknown - skip silently
    return ''.join(result)


def draw_telegram_frame(off, matrix, renderer: Renderer, message: str):
    """Draw a Telegram message overlay with word-wrap, no header."""
    off.Fill(0, 0, 0)
    amber = (255, 140, 0)
    r = renderer

    MSG_START_Y = 3
    inner_width = r.cols - 6

    def glyph_width(ch: str) -> int:
        return r.glyph_width(ch)

    def draw_glyph(x: int, y: int, ch: str) -> None:
        bmp = BITMAP.get(ch, BITMAP[' '])
        whole_offset = 2 if ch in DESCENDERS else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bmp):
            for dx, bit in enumerate(brow[:glyph_width(ch)]):
                if bit:
                    off.SetPixel(x + dx, y + dy + whole_offset, *amber)

    def draw_text(x: int, y: int, text: str) -> None:
        cur = x
        for i, ch in enumerate(text):
            draw_glyph(cur, y, ch)
            cur += glyph_width(ch)
            if i != len(text) - 1:
                cur += CHAR_SPACING

    def wrap(text: str, max_w: int) -> List[str]:
        lines: List[str] = []
        current = ''
        for word in text.split():
            candidate = (current + ' ' + word).strip()
            if r.measure(candidate) <= max_w:
                current = candidate
            else:
                if current:
                    lines.append(current)
                if r.measure(word) > max_w:
                    partial = ''
                    for ch in word:
                        if r.measure(partial + ch) > max_w:
                            break
                        partial += ch
                    current = partial
                else:
                    current = word
        if current:
            lines.append(current)
        return lines

    line_height = CHAR_H + LINE_SPACING
    available = r.rows - MSG_START_Y - 3
    max_lines = available // line_height
    if available - max_lines * line_height >= CHAR_H + 1:
        max_lines += 1

    normalized = _normalize_for_display(message)
    for i, line in enumerate(wrap(normalized, inner_width)[:max_lines]):
        draw_text(3, MSG_START_Y + i * line_height, line)

    return matrix.SwapOnVSync(off)


def draw_menu_frame(off, matrix, renderer: Renderer, username: str, game_list: List[str], selection: int):
    """Draw the game selection menu."""
    off.Fill(0, 0, 0)
    draw_glyph, draw_text, measure = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 2

    # Username line
    name_label = _normalize_for_display(f"Name: {username}")
    draw_text(BOARD_MARGIN + 1, y, name_label)
    y += line_h + 3  # extra gap after name

    # Game list with selector
    for i, game_name in enumerate(game_list):
        prefix = "> " if i == selection else "  "
        text = _normalize_for_display(prefix + game_name)
        draw_text(BOARD_MARGIN + 1, y, text)
        y += line_h
        if y + CHAR_H > renderer.rows - BOARD_MARGIN:
            break

    return matrix.SwapOnVSync(off)


def _start_telegram_poller(token: str, allowed_chat_ids: str, msg_queue: 'queue.Queue[str]') -> None:
    """Long-poll the Telegram Bot API in a daemon thread and push received messages to msg_queue."""
    allowed = {s.strip() for s in allowed_chat_ids.split(',') if s.strip()}
    base_url = f'https://api.telegram.org/bot{token}'
    offset = 0
    while True:
        try:
            resp = requests.get(
                f'{base_url}/getUpdates',
                params={'timeout': 25, 'offset': offset},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get('ok'):
                time.sleep(5)
                continue
            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message') or update.get('channel_post')
                if msg is None:
                    continue
                text = (msg.get('text') or '').strip()
                if not text:
                    continue
                chat_id = str(msg.get('chat', {}).get('id', ''))
                if allowed and chat_id not in allowed:
                    print(f'[telegram] ignoring message from chat {chat_id}', file=sys.stderr)
                    continue
                print(f'[telegram] message from {chat_id}: {text!r}', file=sys.stderr)
                try:
                    msg_queue.put_nowait(text)
                except queue.Full:
                    pass
        except Exception as e:  # noqa: BLE001
            print(f'[telegram] polling error: {e}', file=sys.stderr)
            time.sleep(5)
