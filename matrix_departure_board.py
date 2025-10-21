#!/usr/bin/env python3
"""Display Swiss public transport departures on a 128x64 RGB LED matrix (hzeller/rpi-rgb-led-matrix).

This script is intended to run directly on a Raspberry Pi with an attached
RGB matrix via an Adafruit HAT or similar interface supported by the
hzeller/rpi-rgb-led-matrix library.

Features:
- Fetches departures using local helper module `fetch_departures` (requests -> Opendata API)
- Renders simple fixed 5x7 style font (mono width glyphs) onto offscreen canvas
- Auto refresh loop (default 30s)
- Destination truncation to fit available width
- Optional destination filter for direct connections
- Graceful fallback text output if library not available (for dev on non-Pi)

Usage (examples):
  sudo python3 matrix_departure_board.py --stop "Basel, Aeschenplatz"
  sudo python3 matrix_departure_board.py --stop "Basel, Aeschenplatz" --limit 6 --refresh 20
  sudo python3 matrix_departure_board.py --stop "Basel, Aeschenplatz" --dest "Basel SBB" --limit 4

Note: Must be run with root permissions for GPIO access (sudo).
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
import subprocess
import os
from typing import List, Dict, Any, Optional, Callable

import fetch_departures as fd
import threading
import requests
try:
    from rotary_encoder import RotaryEncoder  # type: ignore
    _HAVE_ENCODER = True
except Exception:  # noqa: BLE001
    RotaryEncoder = None  # type: ignore
    _HAVE_ENCODER = False

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore
    MATRIX_AVAILABLE = True
except Exception:  # noqa: BLE001
    MATRIX_AVAILABLE = False

# --------------------------------------------------------------------------------------
# Simple 5x7 font (subset). Reuse subset of characters needed for typical display
# (Digits, basic latin letters, space, apostrophe, dash, umlauts).
# Representation: list of 7 strings of '0'/'1'.
# --------------------------------------------------------------------------------------
FONT = {
    ' ': ["00000"] * 7,
    '°': [
        "01100",
        "10010",
        "10010",
        "01100",
        "00000",
        "00000",
        "00000",
    ],
    '0': ["01110","10001","10011","10101","11001","10001","01110"],
    '1': ["00100","01100","00100","00100","00100","00100","01110"],
    '2': ["01110","10001","00001","00010","00100","01000","11111"],
    '3': ["11110","00001","00001","01110","00001","00001","11110"],
    '4': ["10010","10010","10010","11111","00010","00010","00010"],
    '5': ["11111","10000","10000","11110","00001","00001","11110"],
    '6': ["01110","10000","10000","11110","10001","10001","01110"],
    '7': ["11111","00001","00010","00100","01000","01000","01000"],
    '8': ["01110","10001","10001","01110","10001","10001","01110"],
    '9': ["01110","10001","10001","01111","00001","00001","01110"],
    'A': ["01110","10001","10001","11111","10001","10001","10001"],
    'B': ["11110","10001","10001","11110","10001","10001","11110"],
    'C': ["01110","10001","10000","10000","10000","10001","01110"],
    'D': ["11110","10001","10001","10001","10001","10001","11110"],
    'E': ["11111","10000","10000","11110","10000","10000","11111"],
    'F': ["11111","10000","10000","11110","10000","10000","10000"],
    'G': ["01110","10001","10000","10111","10001","10001","01110"],
    'H': ["10001","10001","10001","11111","10001","10001","10001"],
    'I': ["11100","01000","01000","01000","01000","01000","11100"],
    'J': ["01110","00010","00010","00010","00010","10010","01100"],
    'K': ["10001","10010","10100","11000","10100","10010","10001"],
    'L': ["10000","10000","10000","10000","10000","10000","11110"],
    'M': ["10001","11011","10101","10001","10001","10001","10001"],
    'N': ["10001","11001","11001","10101","10011","10011","10001"],
    'O': ["01110","10001","10001","10001","10001","10001","01110"],
    'P': ["11110","10001","10001","11110","10000","10000","10000"],
    'Q': ["01110","10001","10001","10001","10101","10010","01101"],
    'R': ["11110","10001","10001","11110","10100","10010","10001"],
    'S': ["01110","10001","10000","01110","00001","10001","01110"],
    'T': ["11111","00100","00100","00100","00100","00100","00100"],
    'U': ["10001","10001","10001","10001","10001","10001","01110"],
    'V': ["10001","10001","10001","10001","10001","01010","00100"],
    'W': ["10001","10001","10001","10001","10101","10101","01010"],
    'X': ["10001","10001","01010","00100","01010","10001","10001"],
    'Y': ["10001","10001","01010","00100","00100","00100","00100"],
    'Z': ["11111","00001","00010","00100","01000","10000","11111"],
    'a': ["00000","00000","01110","00001","01111","10001","01111"],
    'b': ["10000","10000","11110","10001","10001","10001","11110"],
    'c': ["00000","00000","01110","10000","10000","10001","01110"],
    'd': ["00001","00001","01111","10001","10001","10001","01111"],
    'e': ["00000","00000","01110","10001","11111","10000","01110"],
    'f': ["00110","01000","01000","11100","01000","01000","01000"],
    'g': ["01110","10001","10001","10001","01111","00001","01110"],
    'h': ["10000","10000","10110","11001","10001","10001","10001"],
    'i': ["01000","00000","11000","01000","01000","01000","11100"],
    'j': ["00100","00000","01100","00100","00100","00100","11000"],
    'k': ["10000","10000","10010","10100","11000","10100","10010"],
    'l': ["11000","01000","01000","01000","01000","01000","11100"],
    'm': ["00000","00000","11010","10101","10101","10101","10101"],
    'n': ["00000","00000","10110","11001","10001","10001","10001"],
    'o': ["00000","00000","01110","10001","10001","10001","01110"],
    'p': ["11110","10001","10001","10001","11110","10000","10000"],
    'q': ["01110","10001","10001","10001","01111","00001","00001"],
    'r': ["00000","00000","10110","11000","10000","10000","10000"],
    's': ["00000","00000","01111","10000","01110","00001","11110"],
    't': ["01000","01000","11100","01000","01000","01000","01110"],
    'u': ["00000","00000","10001","10001","10001","10011","01101"],
    'v': ["00000","00000","10001","10001","10001","01010","00100"],
    'w': ["00000","00000","10001","10001","10101","10101","01010"],
    'x': ["00000","00000","10001","01010","00100","01010","10001"],
    'y': ["10001","10001","10001","10001","01111","00001","01110"],
    'z': ["00000","00000","11111","00010","00100","01000","11111"],
    '-': ["00000","00000","00000","11100","00000","00000","00000"],
    "'": ["10000","10000","10000","00000","00000","00000","00000"],
    '/': ["00010","00010","00100","00100","00100","01000","01000"],
    ':': ["00000","00000","01000","00000","01000","00000","00000"],
    ',': ["00000","00000","00000","00000","00000","00000","01000"],
    'Ä': ["01110","10001","10001","11111","10001","10001","10001"],
    'Ö': ["01110","10001","10001","10001","10001","10001","01110"],
    'Ü': ["10001","10001","10001","10001","10001","10001","01110"],
    'ä': ["01010","00000","01110","00001","01111","10001","01111"],
    'ö': ["01010","00000","01110","10001","10001","10001","01110"],
    'ü': ["01010","00000","10001","10001","10001","10011","01101"],
    '→': [
        "00000",
        "00100",
        "00010",
        "11111",
        "00010",
        "00100",
        "00000",
    ],
}

BITMAP = {ch: [[1 if c == '1' else 0 for c in row] for row in rows] for ch, rows in FONT.items()}
CHAR_W = 5
CHAR_H = 7
# Visual advance spacing: 1px between glyph runs
CHAR_SPACING = 1
# Vertical spacing between rows
LINE_SPACING = 5
# Variable advance overrides:
ADV_WIDTH = {
    ' ': 2,
    '°': 4,
    '-': 3,
    "'": 1,
    ',': 1,
    ':': 3,
    'i': 3,
    'l': 3,
    'j': 3,
    't': 4,
    'k': 4,
    'f': 4,
    'r': 4,
    'J': 4,
    'I': 3,
    'L': 4,
}
DESCENDERS = {'p','g','q','y','j'}

# Board size defaults (can override with CLI)
DEFAULT_ROWS = 64
DEFAULT_COLS = 128

# Layout constants
LINE_ID_DEST_GAP = 5
DEST_MINS_GAP = 4
RIGHT_MARGIN = 1
MIN_IDENT_CHARS = 2
BOARD_MARGIN = 1  # ensure 1px dark border on all sides

# ----------------------------- Weather support -----------------------------
# Minimal weather integration using Open-Meteo (no API key needed)
# We'll render two weather screens: Basel and Zürich.

class WeatherData(Dict[str, Any]):
    pass

WEATHER_CITIES = [
    {
        'city': 'Basel',
        'lat': 47.5596,
        'lon': 7.5886,
        'header': 'Basel',
    },
    {
        'city': 'Zürich',
        'lat': 47.3769,
        'lon': 8.5417,
        'header': 'Zürich',
    },
]

def _w_code_to_kind_desc(code: int) -> Dict[str, str]:
    """Map Open-Meteo weather_code to a coarse kind and description.
    Kinds: sunny, partly, cloudy, fog, rain, snow, thunder
    """
    # Ref: https://open-meteo.com/en/docs
    if code in (0,):
        return {'kind': 'sunny', 'desc': 'Sonnig'}
    if code in (1, 2):
        return {'kind': 'partly', 'desc': 'Wolkig'}
    if code in (3,):
        return {'kind': 'cloudy', 'desc': 'Bedeckt'}
    if code in (45, 48):
        return {'kind': 'fog', 'desc': 'Nebel'}
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return {'kind': 'rain', 'desc': 'Regen'}
    if code in (71, 73, 75, 77, 85, 86):
        return {'kind': 'snow', 'desc': 'Schnee'}
    if code in (95, 96, 99):
        return {'kind': 'thunder', 'desc': 'Gewitter'}
    return {'kind': 'cloudy', 'desc': 'Wetter'}

# Predefined 15x15 pixel icons (1 = lit, 0 = dark). Easy to edit.
# Keys should match values from _w_code_to_kind_desc.kind
ICON_SIZE = 15
WEATHER_ICONS: Dict[str, List[str]] = {
    'sunny': ["000000000000000","000000010000000","001000010000100","000100000001000","000000111000000","000001000100000","000010000010000","011010000010110","000010000010000","000001000100000","000000111000000","000100000001000","001000010000100","000000010000000","000000000000000"],
    'partly': ["000000000000000","000000010000000","001000010000100","000100000001000","000000111000000","000001000100000","000010000010000","011010000111000","000010011000100","000001100001110","000001000010001","000101000000001","001000100000001","000000011111110","000000000000000"],
    'cloudy': ["000000000000000","000000000000000","000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","000001111111100","000000000000000","000000000000000"],
    'fog': ["000000000000000","000000000000000","000000000000000","000011111111110","000000000000000","011111111111000","000000000000000","000111111111111","000000000000000","111111111110000","000000000000000","001111111111100","000000000000000","000000000000000","000000000000000"],
    'rain': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","000001111111100","000000000000000","000100100100100","001001001001000","010010010010000"],
    'snow': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000100","100001100001110","100010000010001","010010000010001","001110000000001","000010000000010","010001111111100","000000000000000","000100010000100","100000000100000","000001000000010"],
    'thunder': ["000001110000000","000010001100000","001100000010000","010000000111000","100000011000110","100001100001001","010010000000001","001110000000001","000010000100010","000001101011100","000000010000000","000000111110000","000000000100000","000000001000000","000000010000000"],
}

def fetch_weather(lat: float, lon: float, timeout: float = 6.0) -> WeatherData:
    tz = 'Europe/Zurich'
    url = (
        'https://api.open-meteo.com/v1/forecast'
        f'?latitude={lat}&longitude={lon}'
        '&current=temperature_2m,weather_code,relative_humidity_2m,apparent_temperature,wind_speed_10m'
        '&daily=temperature_2m_max,temperature_2m_min,uv_index_max,precipitation_probability_max'
        f'&timezone={tz}'
    )
    # Split timeouts similar to departures
    connect_timeout = min(1.0, max(0.2, timeout / 3.0))
    read_timeout = max(2.5, timeout)
    r = requests.get(url, timeout=(connect_timeout, read_timeout))
    r.raise_for_status()
    j = r.json()
    cur = j.get('current', {}) or j.get('current_weather', {})
    daily = j.get('daily', {})
    # Some variants use 'current_weather'; normalize keys
    temp_now = cur.get('temperature_2m') if 'temperature_2m' in cur else cur.get('temperature')
    wcode = int(cur.get('weather_code') if 'weather_code' in cur else cur.get('weathercode', 0) or 0)
    kind_desc = _w_code_to_kind_desc(wcode)
    tmin_list = list(daily.get('temperature_2m_min') or []) if daily else []
    tmax_list = list(daily.get('temperature_2m_max') or []) if daily else []
    pprob_list = list(daily.get('precipitation_probability_max') or []) if daily else []
    uvmax_list = list(daily.get('uv_index_max') or []) if daily else []
    tmin0 = tmin_list[0] if tmin_list else None
    tmax0 = tmax_list[0] if tmax_list else None
    pprob0 = pprob_list[0] if pprob_list else None
    uvmax0 = uvmax_list[0] if uvmax_list else None
    out: WeatherData = WeatherData(
        now_temp=round(float(temp_now)) if temp_now is not None else None,
        app_temp=round(float(cur.get('apparent_temperature'))) if cur.get('apparent_temperature') is not None else None,
        rh=int(cur.get('relative_humidity_2m')) if cur.get('relative_humidity_2m') is not None else None,
        wind=round(float(cur.get('wind_speed_10m'))) if cur.get('wind_speed_10m') is not None else None,
        code=wcode,
        kind=kind_desc['kind'],
        desc=kind_desc['desc'],
        tmin=round(float(tmin0)) if tmin0 is not None else None,
        tmax=round(float(tmax0)) if tmax0 is not None else None,
        pprob=int(round(float(pprob0))) if pprob0 is not None else None,
        uvmax=int(round(float(uvmax0))) if uvmax0 is not None else None,
    )
    return out


class Renderer:
    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows

    def glyph_width(self, ch: str) -> int:
        return ADV_WIDTH.get(ch, CHAR_W)

    def measure(self, text: str) -> int:
        if not text:
            return 0
        w = 0
        for i, ch in enumerate(text):
            w += self.glyph_width(ch)
            if i != len(text) - 1:
                w += CHAR_SPACING
        return w

    def rows_capacity(self, start_y: int) -> int:
        """Compute number of departure rows fitting starting at start_y (baseline of first row).

        Leaves a bottom BOARD_MARGIN row unused as border.
        """
        available = self.rows - start_y - BOARD_MARGIN
        line_height = CHAR_H + LINE_SPACING
        full = available // line_height
        leftover = available - full * line_height
        if leftover >= CHAR_H + 1:  # allow one more if glyph fits sans spacing fully
            full += 1
        return full

    def prepare_rows(self, rows: List[Dict[str, Any]], origin: str, cap: int) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for r in rows[:cap]:
            cat = (r.get('category') or '').strip().upper()
            num = (r.get('number') or '').strip()
            # Identifier column logic:
            # - Trams: show numeric part only, 2-char column (right-aligned if 1 digit)
            # - Trains/others: show category letters only (strip digits), max 3 chars, 3-char column right-aligned
            if cat in {'T', 'TRAM'} and num:
                ident_display = num
                ident_col_chars = MIN_IDENT_CHARS
            else:
                letters = ''.join(ch for ch in cat if ch.isalpha()).upper() or cat[:3].upper()
                ident_display = letters[:3]
                ident_col_chars = 3
            station_city = fd._station_city(origin)
            # Allow an explicit destination override (e.g., platform label)
            dest_override = r.get('_dest_override')
            if dest_override:
                dest = str(dest_override)
            else:
                dest_raw = (r.get('dest') or '').replace('\n',' ')
                dest = fd._strip_same_city(dest_raw, station_city)
                dest = fd.BAHNHOF_PATTERN.sub('Bhf', dest)
            mins = int(r.get('mins') or 0)
            # width budgeting with variable advance
            ident_w = self.measure('X' * ident_col_chars)
            digits = str(mins)
            digits_w = self.measure(digits)
            apostrophe_w = self.glyph_width("'")
            inner_width = self.cols - 2 * BOARD_MARGIN
            total_minutes_w = digits_w + CHAR_SPACING + apostrophe_w + RIGHT_MARGIN
            digits_start_x = BOARD_MARGIN + inner_width - total_minutes_w
            dest_start_x = BOARD_MARGIN + ident_w + LINE_ID_DEST_GAP
            max_dest_w = digits_start_x - DEST_MINS_GAP - dest_start_x
            if max_dest_w < 0:
                max_dest_w = 0
            # truncate destination
            draw_chars: List[str] = []
            cur = 0
            for ch in dest:
                gw = self.glyph_width(ch)
                add = gw if not draw_chars else CHAR_SPACING + gw
                if cur + add > max_dest_w:
                    break
                draw_chars.append(ch)
                cur += add
            out.append({
                'ident_display': ident_display,
                'ident_col_chars': str(ident_col_chars),
                'dest': ''.join(draw_chars),
                'mins': str(mins),
            })
        return out

# Matrix specific drawing -----------------------------------------------------

def draw_frame(off, matrix: RGBMatrix, renderer: Renderer, rows: List[Dict[str, Any]], header_text: str, city_reference: str, now_text: Optional[str] = None):  # type: ignore[name-defined]
    """Draw a complete frame.

    off: off-screen canvas (re-used each frame)
    rows: departures (empty => blank list area)
    header_text: text to render in the header (e.g., "Basel SBB → Zürich HB")
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


def draw_weather_frame(off, matrix: RGBMatrix, renderer: Renderer, header_text: str, weather: Optional[WeatherData], now_text: Optional[str] = None):  # type: ignore[name-defined]
    """Draw a weather screen with header and a simple pictogram.

    Content layout:
    - Header: city left (derived from header_text), time right
    - Rule line
    - Middle: icon on left, temps and conditions on right
    - Bottom line: extra info if space allows
    """
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
    cur_temp = f"{nowt}°" if nowt is not None else "--°"
    draw_text(left_x, CONTENT_Y, truncate(cur_temp, r.cols))
    draw_icon(left_x, CONTENT_Y + CHAR_H + 2, kind)

    # Right column: Min/Max:, Wind, Real feel
    text_x = left_x + ICON_SIZE + 8
    tmin = weather.get('tmin') if weather else None
    tmax = weather.get('tmax') if weather else None
    wind = weather.get('wind') if weather else None
    app = weather.get('app_temp') if weather else None

    line1 = f"Min/Max: {tmin if tmin is not None else '--'}°/{tmax if tmax is not None else '--'}°"
    line2 = f"Wind: {wind if wind is not None else '--'}" + (" km/h" if wind is not None else "")
    line3 = f"Real feel: {app if app is not None else '--'}°"

    draw_text(text_x, CONTENT_Y, truncate(line1, max(0, r.cols - text_x - BOARD_MARGIN)))
    draw_text(text_x, CONTENT_Y + CHAR_H + 3, truncate(line2, max(0, r.cols - text_x - BOARD_MARGIN)))
    draw_text(text_x, CONTENT_Y + 2*(CHAR_H + 3), truncate(line3, max(0, r.cols - text_x - BOARD_MARGIN)))

    return matrix.SwapOnVSync(off)


def run_loop(opts: argparse.Namespace):
    if not MATRIX_AVAILABLE:
        print("rgbmatrix library not available. Falling back to plain text output (developer mode).", file=sys.stderr)
        while True:
            rows = fd.fetch_stationboard(opts.stop, opts.limit * 4, transportations=None if opts.all else ['tram','train'])
            if opts.dest:
                nf = fd._normalize(opts.dest)
                rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
            # Sort strictly by current minutes-to-departure to avoid inversions
            rows.sort(key=lambda r: r.get('mins', 0))
            rows = rows[:opts.limit]
            for r in rows:
                print(fd.format_departure(r, opts.stop))
            print('-' * 40)
            time.sleep(opts.refresh)
        return
    # Build screen list (two existing tram stops + third: Basel SBB → Zürich HB, trains only)
    def _make_stop_screen(name: str) -> Dict[str, Any]:
        return {
            'origin': name,
            'header': name,
            'city_ref': name,
            'transportations': None if opts.all else ['tram','train'],
            'dest_filter': None,
        }
    screens: List[Dict[str, Any]] = []
    default_stops = ["Basel, Aeschenplatz", "Basel, Denkmal"]
    if opts.stop not in default_stops:
        screens.append(_make_stop_screen(opts.stop))
    for s in default_stops:
        screens.append(_make_stop_screen(s))
    # Third screen: trains Basel SBB → Zürich HB only
    screens.append({
        'origin': 'Basel SBB',
        'header': 'Basel → Zürich',
        'city_ref': 'Basel SBB',
        'transportations': ['train'],
        'dest_filter': 'Zürich HB',
    })

    # Add two weather screens (Basel & Zürich)
    for w in WEATHER_CITIES:
        screens.append({
            'type': 'weather',
            'header': w['header'],
            'city': w['city'],
            'lat': w['lat'],
            'lon': w['lon'],
        })

    # --- Simplified State Machine --------------------------------------------------
    # Initial active screen index (prefer the one matching --stop without dest filter)
    try:
        current_index = next(i for i, sc in enumerate(screens) if sc['origin'] == opts.stop and sc['dest_filter'] is None)
    except StopIteration:
        current_index = 0
    active_screen = screens[current_index]
    # Display rows currently shown (page slice) and the full fetched list for current screen
    departures: List[Dict[str, Any]] = []          # current page slice to render
    departures_all: List[Dict[str, Any]] = []      # full list from last fetch for current screen
    page_toggle: int = 0                           # 0 = first 4, 1 = next 4
    force_first_page: bool = False                 # after a stop change, hold page 0 until next rotation
    rotation_alternate: int = 0                    # 0 => next rotation toggles page; 1 => next rotation changes stop
    last_fetch_time = 0.0                          # timestamp of last successful fetch
    next_scheduled_fetch = 0.0                     # when to fetch (rotation delay, periodic refresh)
    fetch_interval = max(15.0, float(opts.refresh))  # periodic refresh (>=15s)
    rotate_fetch_delay = max(0.05, getattr(opts, 'rotate_fetch_delay', 0.5))
    encoder = None
    encoder_started_early = False
    last_rotation_accept = 0.0                     # low-level debounce between pulses
    last_rotation_action = 0.0                     # high-level action cooldown to merge bouncy pulses
    rotation_action_cooldown = float(getattr(opts, 'rotate_action_cooldown', 0.3))
    last_button_event = 0.0                        # last button press time (to guard rotations after click)
    rotate_guard_after_button = 0.25               # seconds to ignore rotation after a click
    rotation_min_interval = float(getattr(opts, 'rotate_min_interval', 0.08))

    rotation_queue: List[int] = []                 # accumulate raw deltas (optional future use)

    def schedule_fetch(delay: float = 0.0):
        nonlocal next_scheduled_fetch
        t = time.time() + delay
        if next_scheduled_fetch == 0.0 or t < next_scheduled_fetch:
            next_scheduled_fetch = t

    # Weather cache
    weather_cache: Dict[str, Dict[str, Any]] = {}
    # keys -> {'data': WeatherData|None, 'ts': float}

    def _accept_rotation(direction: int):
        nonlocal current_index, active_screen, departures, departures_all, page_toggle, force_first_page
        current_index = (current_index + (1 if direction > 0 else -1)) % len(screens)
        active_screen = screens[current_index]
        # Blank departures immediately – display will show empty area for half second
        departures = []
        departures_all = []
        page_toggle = 0  # reset to first page on stop change
        force_first_page = True  # ensure the new stop displays page 0 until next rotation
        schedule_fetch(rotate_fetch_delay)

    def _on_rotate(raw_delta: int):  # noqa: D401
        nonlocal last_rotation_accept, last_rotation_action, rotation_alternate
        now = time.time()
        # Guard: ignore rotation shortly after a button press (mechanical press can jiggle encoder)
        if (now - last_button_event) < rotate_guard_after_button:
            return
        if now - last_rotation_accept < rotation_min_interval:
            return  # debounce / noise filter
        # Coalesce multiple pulses from one physical twist
        if now - last_rotation_action < rotation_action_cooldown:
            return
        last_rotation_accept = now
        direction = 1 if raw_delta > 0 else -1
        if getattr(opts, 'encoder_debug', False):
            print(f"[encoder] detent delta={direction} at {now:.3f} alt={rotation_alternate}", file=sys.stderr)
        # Alternate: first rotation toggles page, next rotation changes stop
        if rotation_alternate == 0:
            _toggle_page()
        else:
            _accept_rotation(direction)
        rotation_alternate = 1 - rotation_alternate
        last_rotation_action = now

    def _update_display_rows_from_page():
        nonlocal departures
        effective_page = 0 if force_first_page else page_toggle
        start = effective_page * opts.limit
        end = start + opts.limit
        departures = departures_all[start:end]

    def _toggle_page():
        nonlocal page_toggle, force_first_page
        # Once user toggles, we no longer force page 0
        if force_first_page:
            force_first_page = False
        page_toggle = 0 if page_toggle == 1 else 1
        if getattr(opts, 'encoder_debug', False):
            print(f"[encoder] page toggle -> page {page_toggle}", file=sys.stderr)
        if page_toggle == 1 and len(departures_all) <= opts.limit:
            schedule_fetch(0.0)
        _update_display_rows_from_page()

    def _on_button():
        """Toggle between first and next 4 departures for current stop."""
        nonlocal page_toggle, last_button_event
        nowb = time.time()
        # Additional guard to ignore accidental rapid repeats (<100ms)
        if (nowb - last_button_event) < 0.1:
            return
        last_button_event = nowb
        _toggle_page()

    # Early encoder init (before RGBMatrix) if requested
    if _HAVE_ENCODER and RotaryEncoder is not None and not getattr(opts, 'no_encoder', False) and getattr(opts, 'encoder_early', False):
        if opts.encoder_debug:
            print("[encoder] Early init requested before RGBMatrix", file=sys.stderr)
        try:
            if opts.encoder_delay > 0:
                if opts.encoder_debug:
                    print(f"[encoder] Sleeping {opts.encoder_delay:.3f}s before early init", file=sys.stderr)
                time.sleep(opts.encoder_delay)
            encoder = RotaryEncoder(
                pin_clk=opts.enc_clk,
                pin_dt=opts.enc_dt,
                pin_sw=opts.enc_sw,
                on_rotate=_on_rotate,
                on_button=_on_button,
                force_polling=opts.enc_poll,
                debug=opts.encoder_debug,
                steps_per_detent=max(1, int(getattr(opts, 'enc_steps_per_detent', 2))),
            )
            encoder.start()
            encoder_started_early = True
            print("Rotary encoder active (early)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[encoder] Early init failed: {e}", file=sys.stderr)

    # Matrix path
    options = RGBMatrixOptions()
    options.rows = opts.rows
    options.cols = opts.cols
    # The rgbmatrix library uses 'hardware_mapping' (older docs sometimes refer to gpio-mapping)
    # Accept --gpio-mapping CLI for user familiarity but map to hardware_mapping attribute.
    try:
        options.hardware_mapping = opts.gpio_mapping  # type: ignore[attr-defined]
    except AttributeError:  # Fallback if attribute name differs in older lib
        # Some very old versions used 'gpio_mapping'; if present, set it dynamically.
        if hasattr(options, 'gpio_mapping'):
            setattr(options, 'gpio_mapping', opts.gpio_mapping)
    options.brightness = opts.brightness
    # Allow user override of PWM / refresh tuning.
    if opts.pwm_lsb_ns is not None:
        options.pwm_lsb_nanoseconds = opts.pwm_lsb_ns
    else:
        options.pwm_lsb_nanoseconds = 130
    if opts.dither_bits is not None:
        options.pwm_dither_bits = opts.dither_bits
    else:
        options.pwm_dither_bits = 1
    # Only set explicit refresh limit if the user asked; letting the library pick often yields less flicker
    if opts.limit_refresh_hz is not None:
        options.limit_refresh_rate_hz = opts.limit_refresh_hz
    # Optional: PWM bit depth (lower can reduce LSB flicker at very low brightness)
    if getattr(opts, 'pwm_bits', None) is not None:
        options.pwm_bits = int(opts.pwm_bits)
    if opts.slowdown_gpio is not None:
        options.gpio_slowdown = opts.slowdown_gpio
    # Only set multiplexing/scan parameters if provided; defaults vary by panel generation
    if getattr(opts, 'multiplexing', None) is not None:
        options.multiplexing = int(opts.multiplexing)
    if getattr(opts, 'scan_mode', None) is not None:
        options.scan_mode = int(opts.scan_mode)
    if getattr(opts, 'row_addr_type', None) is not None:
        options.row_address_type = int(opts.row_addr_type)
    # Panel/controller specific tweaks
    if getattr(opts, 'panel_type', None):
        options.panel_type = opts.panel_type
    if getattr(opts, 'led_rgb_sequence', None):
        options.led_rgb_sequence = opts.led_rgb_sequence
    if getattr(opts, 'disable_hardware_pulsing', False):
        options.disable_hardware_pulsing = True
    options.pixel_mapper_config = ""
    if opts.chain > 1:
        options.chain_length = opts.chain
    if opts.parallel > 1:
        options.parallel = opts.parallel

    matrix = RGBMatrix(options = options)

    renderer = Renderer(opts.cols * opts.chain, opts.rows * opts.parallel)

    # Rotary encoder integration (post-matrix init if not early) ----------------------
    if _HAVE_ENCODER and RotaryEncoder is not None and not getattr(opts, 'no_encoder', False) and not encoder_started_early:
        def _start_encoder():
            nonlocal encoder
            if opts.encoder_debug:
                print("[encoder] Delayed post-matrix init start", file=sys.stderr)
            time.sleep(0.25 if opts.encoder_delay is None else opts.encoder_delay)
            try:
                # Many pins are used by the RGB matrix HAT. Avoid common conflicts.
                conflict_pins = {4,5,6,12,13,16,18,19,20,21,22,23,24,25,26,27}
                user_pins = {opts.enc_clk, opts.enc_dt, opts.enc_sw}
                if conflict_pins & user_pins:
                    print(f"[encoder] Warning: chosen pins {user_pins & conflict_pins} likely conflict with the RGB matrix HAT. Try different GPIOs (e.g., 7, 14, 15) and reboot.", file=sys.stderr)
                # Warn about UART pins – GPIO14/15 are TXD/RXD and may toggle due to serial console
                uart_pins = {14, 15}
                if uart_pins & user_pins:
                    print("[encoder] Warning: using UART pins (GPIO14/15). They can show activity/noise unless serial console/UART is disabled. Prefer other GPIOs for CLK/DT or disable serial.", file=sys.stderr)
                encoder = RotaryEncoder(
                    pin_clk=opts.enc_clk,
                    pin_dt=opts.enc_dt,
                    pin_sw=opts.enc_sw,
                    on_rotate=_on_rotate,  # type: ignore[operator]
                    on_button=_on_button,
                    force_polling=opts.enc_poll,
                    debug=opts.encoder_debug,
                    steps_per_detent=max(1, int(getattr(opts, 'enc_steps_per_detent', 2))),
                )
                encoder.start()
                print("Rotary encoder active (events or polling)", file=sys.stderr)
            except RuntimeError as e:
                print(f"Rotary encoder event init failed ({e}); continuing without encoder.", file=sys.stderr)
                encoder = None
            except Exception as e:  # noqa: BLE001
                print(f"Failed to init rotary encoder: {e}", file=sys.stderr)
                encoder = None
        threading.Thread(target=_start_encoder, daemon=True).start()

    # Fetch helpers
    def fetch_rows(screen: Dict[str, Any], timeout: float = 10.0) -> List[Dict[str, Any]]:
        # Increase fetch size to ensure enough items for two pages even after filtering
        base_fetch = max(opts.limit * 6, 40)
        fetch_size = max(base_fetch, 60) if screen.get('dest_filter') else base_fetch
        # Use a short connect timeout and a moderate read timeout to avoid long stalls on boot
        connect_timeout = min(1.0, max(0.2, timeout / 3.0))
        read_timeout = max(2.5, timeout)
        rows = fd.fetch_stationboard(
            screen['origin'],
            fetch_size,
            transportations=screen.get('transportations'),
            timeout=(connect_timeout, read_timeout),
        )
        dest_filter = screen.get('dest_filter')
        if dest_filter:
            nf = fd._normalize(dest_filter)
            filtered: List[Dict[str, Any]] = []
            for r in rows:
                if (r.get('category') or '').upper() in {'T','TRAM'}:
                    continue
                if fd._normalize(r.get('dest') or '') != nf:
                    continue
                # Override destination text to show platform label if available
                plat = (r.get('plat') or '').strip()
                if plat:
                    r = dict(r)
                    r['_dest_override'] = f"Gleis {plat}"
                filtered.append(r)
            rows = filtered
        # Apply global CLI destination filter as an additional constraint if provided
        if getattr(opts, 'dest', ''):
            nf_cli = fd._normalize(opts.dest)
            rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf_cli]
        # Sort strictly by minutes-to-departure for stable ordering across pages
        rows.sort(key=lambda r: r.get('mins', 0))
        # Return enough rows for two pages (and a small safety buffer)
        return rows[: max(int(opts.limit * 2.5), 10)]

    def fetch_weather_for_screen(screen: Dict[str, Any], timeout: float = 6.0) -> WeatherData:
        return fetch_weather(float(screen['lat']), float(screen['lon']), timeout=timeout)

    # Detect whether system time is synchronized; in 'auto' mode trust RTC/plausible clock
    _sync_cached: Optional[bool] = None
    _sync_ts: float = 0.0
    _sync_locked_true: bool = False  # once true, don't spawn subprocesses again
    _sync_min_interval: float = 15.0  # seconds between checks while not yet true

    ntp_wait_mode = getattr(opts, 'ntp_wait_mode', 'auto')  # 'auto' | 'strict' | 'skip'

    def _rtc_present() -> bool:
        try:
            return os.path.exists('/sys/class/rtc/rtc0')
        except Exception:
            return False

    def _time_looks_sane() -> bool:
        try:
            year = datetime.now().year
            return year >= 2023
        except Exception:
            return False

    def time_is_synchronized() -> bool:
        nonlocal _sync_cached, _sync_ts, _sync_locked_true
        # Mode shortcuts
        if ntp_wait_mode == 'skip':
            return True
        if ntp_wait_mode == 'auto':
            # If RTC present or clock looks sane, treat as synced immediately
            if _rtc_present() or _time_looks_sane():
                _sync_locked_true = True
                _sync_cached = True
                _sync_ts = time.time()
                return True
        # 'strict' or didn't pass auto heuristics: actually query NTP status
        now = time.time()
        if _sync_locked_true:
            return True
        if _sync_cached is not None and (now - _sync_ts) < _sync_min_interval:
            return _sync_cached
        result = False
        try:
            out = subprocess.check_output(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.2,
            ).strip().lower()
            if out in {"yes", "true", "1"}:
                result = True
        except Exception:
            # Fallback heuristic
            result = _time_looks_sane()
        _sync_cached = result
        _sync_ts = now
        if result:
            _sync_locked_true = True
        return result

    # Compute next :00 or :30 boundary timestamp (epoch seconds)
    def next_half_minute_boundary(ts: float) -> float:
        dt = datetime.fromtimestamp(ts)
        sec = dt.second
        if sec < 30:
            target_sec = 30
            target_min = dt.minute
            target_hr = dt.hour
        else:
            target_sec = 0
            # advance minute
            target_min = (dt.minute + 1) % 60
            target_hr = dt.hour + 1 if target_min == 0 else dt.hour
        future = dt.replace(hour=target_hr % 24, minute=target_min, second=target_sec, microsecond=0)
        # If hour rolled beyond day, let datetime handle day rollover by adding difference
        return future.timestamp()

    # --- Initial fetch scheduling --------------------------------------------------
    schedule_fetch(0.0)  # fetch immediately on start
    next_periodic_refresh = time.time() + fetch_interval
    process_start_time = time.time()
    fetch_backoff = 1.0  # start very small on boot; ramp up with failures
    last_time_sync_state = time_is_synchronized()
    # Background fetch control
    fetch_in_flight = False
    current_fetch_timeout = 2.5  # short initial timeout to avoid long stalls at boot

    def start_fetch():
        nonlocal fetch_in_flight, departures, last_fetch_time, fetch_backoff, next_periodic_refresh, current_fetch_timeout
        if fetch_in_flight:
            return
        # Snapshot the active screen at start to fetch a consistent target
        screen_snapshot = dict(active_screen)
        fetch_in_flight = True
        def _worker():
            nonlocal fetch_in_flight, departures, last_fetch_time, fetch_backoff, next_periodic_refresh, current_fetch_timeout
            try:
                if screen_snapshot.get('type') == 'weather':
                    # Fetch and cache weather
                    key = f"{screen_snapshot.get('city','')}"
                    try:
                        w_new = fetch_weather_for_screen(screen_snapshot)
                        weather_cache[key] = {'data': w_new, 'ts': time.time()}
                    except Exception as we:  # noqa: BLE001
                        print(f"[weather] fetch error for {key}: {we}", file=sys.stderr)
                    # Keep departures untouched
                    last_fetch_time = time.time()
                    fetch_backoff = 5.0
                else:
                    rows_local = fetch_rows(screen_snapshot, timeout=current_fetch_timeout)
                    # Only apply if still on the same screen
                    if screen_snapshot is active_screen or screen_snapshot.get('header') == active_screen.get('header'):
                        departures_all[:] = rows_local
                        _update_display_rows_from_page()
                        last_fetch_time = time.time()
                        fetch_backoff = 5.0
                        next_periodic_refresh = last_fetch_time + fetch_interval
                        # Gradually increase timeout after a success (cap at 10s)
                        current_fetch_timeout = min(10.0, max(current_fetch_timeout, 3.0))
            except Exception as e:  # noqa: BLE001
                print(f"[fetch] Error fetching departures for '{screen_snapshot.get('header','?')}': {e}", file=sys.stderr)
                # Quick retry with exponential backoff (cap 60s); also slightly increase timeout
                elapsed = time.time() - process_start_time
                # During the first 20s after boot, keep retries snappy (<= 2s)
                if elapsed < 20.0:
                    fetch_backoff = min(2.0, max(0.5, fetch_backoff * 1.5))
                else:
                    fetch_backoff = min(60.0, max(2.0, fetch_backoff * 1.5))
                current_fetch_timeout = min(10.0, current_fetch_timeout + 1.0)
                schedule_fetch(fetch_backoff)
            finally:
                fetch_in_flight = False
        threading.Thread(target=_worker, daemon=True).start()

    # Single off-screen canvas reused (fix for CreateFrameCanvas spam)
    offscreen = matrix.CreateFrameCanvas()
    # On very early boot, show real clock immediately in auto/skip modes; placeholder only in strict mode without sync
    initial_now = None if time_is_synchronized() else ("--:--" if ntp_wait_mode == 'strict' else None)
    offscreen = draw_frame(offscreen, matrix, renderer, departures, active_screen['header'], active_screen['city_ref'], now_text=initial_now)  # blank first frame, clears stale panel content
    # Kick off the first fetch immediately if clock is usable
    if time_is_synchronized():
        start_fetch()

    running = True
    def _sig_handler(signum, frame):  # noqa: D401, ANN001
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        # Fixed render cadence in seconds (helps avoid visible beating with PWM/refresh)
        render_interval = 1.0 / 30.0  # ~30 FPS is plenty for static text
        next_render = time.time()
        while running:
            now = time.time()
            # Fetch if scheduled
            if next_scheduled_fetch and now >= next_scheduled_fetch:
                # If system time isn't synced yet (strict mode), don't fetch; retry soon
                if not time_is_synchronized():
                    schedule_fetch(min(5.0, fetch_backoff))
                    last_time_sync_state = False
                    next_scheduled_fetch = 0.0
                else:
                    start_fetch()
                    next_scheduled_fetch = 0.0
            # Periodic refresh if stale (even without rotation)
            if departures and now >= next_periodic_refresh and not fetch_in_flight:
                schedule_fetch(0.0)
                next_periodic_refresh = now + fetch_interval
            # Redraw at a fixed cadence. In strict mode before sync, render placeholder clock.
            if now >= next_render:
                now_txt_override = None if time_is_synchronized() else ("--:--" if ntp_wait_mode == 'strict' else None)
                if active_screen.get('type') == 'weather':
                    key = f"{active_screen['city']}"
                    w_entry = weather_cache.get(key)
                    # Refresh weather every 10 minutes
                    w_data = w_entry['data'] if (w_entry and (now - w_entry['ts'] < 600)) else None
                    if w_data is None and not fetch_in_flight and time_is_synchronized():
                        # Opportunistic refresh outside scheduled fetch
                        try:
                            w_new = fetch_weather_for_screen(active_screen)
                            weather_cache[key] = {'data': w_new, 'ts': time.time()}
                            w_data = w_new
                        except Exception as e:  # noqa: BLE001
                            print(f"[weather] fetch error for {key}: {e}", file=sys.stderr)
                    offscreen = draw_weather_frame(offscreen, matrix, renderer, active_screen['header'], w_data, now_text=now_txt_override)
                else:
                    offscreen = draw_frame(offscreen, matrix, renderer, departures, active_screen['header'], active_screen['city_ref'], now_text=now_txt_override)
                next_render += render_interval
                # Avoid drift if we fall behind
                if next_render < now:
                    next_render = now + render_interval
            # If time just became synchronized and we have no departures yet, force a fetch asap
            if (now_txt_override is None) and not departures and not next_scheduled_fetch and not fetch_in_flight:
                schedule_fetch(0.0)
            # Sleep until the next interesting event (render tick or scheduled fetch)
            t_until_render = max(0.0, next_render - time.time())
            t_until_fetch = max(0.0, (next_scheduled_fetch - time.time()) if next_scheduled_fetch else 1.0)
            time.sleep(min(t_until_render, t_until_fetch, 0.05))
    finally:
        if encoder:
            try:
                encoder.stop()
            except Exception:  # noqa: BLE001
                pass


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Show departures on RGB LED matrix')
    p.add_argument('--stop', default=fd.STOP, help='Origin stop name')
    p.add_argument('--dest', default='', help='Optional exact destination filter')
    p.add_argument('--limit', type=int, default=fd.LIMIT, help='Number of departures to display')
    p.add_argument('--refresh', type=int, default=30, help='Refresh interval seconds')
    p.add_argument('--brightness', type=int, default=40, help='Panel brightness (0-100)')
    p.add_argument('--rows', type=int, default=DEFAULT_ROWS, help='Panel rows (height)')
    p.add_argument('--cols', type=int, default=DEFAULT_COLS, help='Panel columns (width)')
    p.add_argument('--gpio-mapping', default='adafruit-hat', help='GPIO mapping (e.g. adafruit-hat)')
    p.add_argument('--chain', type=int, default=1, help='Number of daisy-chained panels')
    p.add_argument('--parallel', type=int, default=1, help='Parallel chains')
    p.add_argument('--all', action='store_true', help='Include all transport types (ignore default tram/train)')
    # Advanced tuning flags (optional)
    p.add_argument('--slowdown-gpio', type=int, choices=[0,1,2,3,4], default=None,
                   help='GPIO slowdown (increase if you see flicker/noise)')
    p.add_argument('--pwm-lsb-ns', type=int, default=None,
                   help='Override pwm_lsb_nanoseconds (timing of LSB pulse)')
    p.add_argument('--limit-refresh-hz', type=int, default=None,
                   help='Hard limit on refresh rate Hz (lower to reduce CPU/flicker)')
    p.add_argument('--dither-bits', type=int, default=None,
                   help='Override pwm dither bits (0 to disable, higher = smoother dims)')
    p.add_argument('--pwm-bits', type=int, default=None,
                   help='PWM bit depth (default panel-specific). Try 8-11 to reduce low-brightness flicker')
    p.add_argument('--multiplexing', type=int, default=None,
                   help='Forced multiplexing scheme (e.g., 0/8/16/32/64). Only set if you know your panel spec')
    p.add_argument('--scan-mode', type=int, choices=[0,1], default=None,
                   help='Scan mode: 0 = progressive, 1 = interlaced. Some panels flicker less with 1')
    p.add_argument('--row-addr-type', type=int, choices=[0,1,2,3,4], default=None,
                   help='Row address type (A/B/C/... lines). Matches panel controller generation')
    p.add_argument('--panel-type', default=None,
                   help='Panel type hint (e.g., FM6126A, ICN2038S). Enables panel-specific init sequences')
    p.add_argument('--led-rgb-sequence', default=None,
                   help='Override LED color sequence (e.g., RGB, RBG, GBR). Can affect ghosting/flicker')
    p.add_argument('--disable-hardware-pulsing', action='store_true',
                   help='Disable HAT hardware pulsing; may help on some clones at the cost of CPU')
    # Rotary encoder options
    p.add_argument('--no-encoder', action='store_true', help='Disable rotary encoder even if library present')
    p.add_argument('--enc-clk', type=int, default=7, help='Rotary encoder CLK (A) GPIO (BCM numbering)')
    p.add_argument('--enc-dt', type=int, default=9, help='Rotary encoder DT (B) GPIO (BCM numbering, optional)')
    p.add_argument('--enc-sw', type=int, default=11, help='Rotary encoder switch GPIO (BCM numbering)')
    p.add_argument('--enc-poll', action='store_true', help='Force polling mode instead of interrupt events')
    p.add_argument('--encoder-early', action='store_true', help='Initialize rotary encoder before RGBMatrix (try if normal init fails)')
    p.add_argument('--encoder-delay', type=float, default=0.0, help='Delay seconds before encoder init (early or delayed)')
    p.add_argument('--encoder-debug', action='store_true', help='Verbose encoder debug messages')
    p.add_argument('--rotate-fetch-delay', type=float, default=0.5,
                   help='Delay seconds after rotation before fetching new departures (immediate header update)')
    p.add_argument('--rotate-min-interval', type=float, default=0.08,
                   help='Minimum seconds between accepted detents (debounce at app level)')
    p.add_argument('--enc-steps-per-detent', type=int, default=1,
                   help='Steps per detent: 1 for directionless (CLK only), 2/4 if using full quadrature')
    p.add_argument('--ntp-wait-mode', choices=['auto','strict','skip'], default='auto',
                   help="Time sync strategy at boot: 'auto' (default) trusts RTC or plausible clock, 'strict' waits for NTP, 'skip' never waits")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    opts = parse_args(argv)
    run_loop(opts)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
