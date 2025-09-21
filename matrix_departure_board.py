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
from typing import List, Dict, Any, Optional

import fetch_departures as fd

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
    'I': ["01110","00100","00100","00100","00100","00100","01110"],
    'J': ["00111","00010","00010","00010","00010","10010","01100"],
    'K': ["10001","10010","10100","11000","10100","10010","10001"],
    'L': ["10000","10000","10000","10000","10000","10000","11111"],
    'M': ["10001","11011","10101","10101","10001","10001","10001"],
    'N': ["10001","11001","10101","10011","10001","10001","10001"],
    'O': ["01110","10001","10001","10001","10001","10001","01110"],
    'P': ["11110","10001","10001","11110","10000","10000","10000"],
    'Q': ["01110","10001","10001","10001","10101","10010","01101"],
    'R': ["11110","10001","10001","11110","10100","10010","10001"],
    'S': ["01111","10000","10000","01110","00001","00001","11110"],
    'T': ["11111","00100","00100","00100","00100","00100","00100"],
    'U': ["10001","10001","10001","10001","10001","10001","01110"],
    'V': ["10001","10001","10001","10001","10001","01010","00100"],
    'W': ["10001","10001","10001","10101","10101","11011","10001"],
    'X': ["10001","10001","01010","00100","01010","10001","10001"],
    'Y': ["10001","10001","01010","00100","00100","00100","00100"],
    'Z': ["11111","00001","00010","00100","01000","10000","11111"],
    'a': ["00000","00000","01110","00001","01111","10001","01111"],
    'b': ["10000","10000","11110","10001","10001","10001","11110"],
    'c': ["00000","00000","01110","10000","10000","10001","01110"],
    'd': ["00001","00001","01111","10001","10001","10001","01111"],
    'e': ["00000","00000","01110","10001","11111","10000","01110"],
    'f': ["00110","01001","01000","11100","01000","01000","01000"],
    'g': ["01110","10001","10001","01111","00001","00001","01110"],
    'h': ["10000","10000","11110","10001","10001","10001","10001"],
    'i': ["00100","00000","01100","00100","00100","00100","01110"],
    'j': ["00000","00000","00110","00010","00010","00010","01100"],
    'k': ["10000","10000","10010","10100","11000","10100","10010"],
    'l': ["01100","00100","00100","00100","00100","00100","01110"],
    'm': ["00000","00000","11010","10101","10101","10101","10101"],
    'n': ["00000","00000","11110","10001","10001","10001","10001"],
    'o': ["00000","00000","01110","10001","10001","10001","01110"],
    'p': ["11110","10001","10001","11110","10000","10000","10000"],
    'q': ["01110","10001","10001","01111","00001","00001","00001"],
    'r': ["00000","00000","10110","11001","10000","10000","10000"],
    's': ["00000","00000","01111","10000","01110","00001","11110"],
    't': ["00100","00100","11111","00100","00100","00100","00110"],
    'u': ["00000","00000","10001","10001","10001","10001","01111"],
    'v': ["00000","00000","10001","10001","10001","01010","00100"],
    'w': ["00000","00000","10001","10101","10101","11011","10001"],
    'x': ["00000","00000","10001","01010","00100","01010","10001"],
    'y': ["10001","10001","10001","01111","00001","00001","01110"],
    'z': ["00000","00000","11111","00010","00100","01000","11111"],
    '-': ["00000","00000","00000","11100","00000","00000","00000"],
    "'": ["10000","10000","10000","00000","00000","00000","00000"],
    '/': ["00001","00010","00100","00100","01000","10000","10000"],
    ':': ["00000","01000","00000","00000","01000","00000","00000"],
    ',': ["00000","00000","00000","00000","00000","00000","01000"],
    'Ä': ["01110","10001","10001","11111","10001","10001","10001"],
    'Ö': ["01110","10001","10001","10001","10001","10001","01110"],
    'Ü': ["10001","10001","10001","10001","10001","10001","01110"],
    'ä': ["01010","00000","01110","00001","01111","10001","01111"],
    'ö': ["01010","00000","01110","10001","10001","10001","01110"],
    'ü': ["01010","00000","10001","10001","10001","10001","01111"],
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
    '-': 3,
    "'": 1,
    ',': 1,
    ':': 3,
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
            if cat in {'T','TRAM'} and num:
                ident = num
            else:
                ident = (r.get('line') or f"{cat}{num}" or '?').strip()
            if len(ident) <= MIN_IDENT_CHARS:
                ident_display = ident
                ident_col_chars = MIN_IDENT_CHARS
            else:
                ident_display = ident
                ident_col_chars = len(ident)
            station_city = fd._station_city(origin)
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

def draw_frame(matrix: RGBMatrix, renderer: Renderer, rows: List[Dict[str, Any]], origin: str):  # type: ignore[name-defined]
    off = matrix.CreateFrameCanvas()
    amber = (255, 140, 0)

    r = renderer

    # Explicit layout specification:
    # 0: blank row (top margin)
    # 1..7: header glyph box (baseline at y=1)
    # 8..9: two blank rows
    # 10: horizontal rule (full width, ignores horizontal margin)
    # 11..13: three blank rows
    # 14: first departure row baseline, subsequent rows separated by 5px vertical spacing
    HEADER_BASELINE_Y = 1
    RULE_Y = HEADER_BASELINE_Y + CHAR_H + 2  # 1 + 7 + 2 = 10
    DEPARTURES_START_Y = RULE_Y + 1 + 3      # 10 + 1 + 3 = 14
    cap = r.rows_capacity(DEPARTURES_START_Y)
    prepared = r.prepare_rows(rows, origin, cap)

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
    now_txt = datetime.now().strftime('%H:%M')
    inner_left = BOARD_MARGIN
    inner_right = r.cols - BOARD_MARGIN - 1  # last drawable column inside header margin
    inner_width = r.cols - 2 * BOARD_MARGIN
    time_w = measure(now_txt)
    # leave 1px gap before inner_right
    time_x = inner_right - time_w  # already leaves gap since inner_right not drawn on
    # Determine stop name similarly to demo logic
    station_city = fd._station_city(origin)
    if ',' in origin:
        parts = [p.strip() for p in origin.split(',')]
        if len(parts) >= 2:
            stop_name = parts[1] or parts[0]
        else:
            stop_name = parts[0]
    else:
        stop_name = origin.strip()
    if station_city and stop_name.lower() == station_city.lower():
        alts = [p.strip() for p in origin.split(',') if p.strip().lower() != station_city.lower()]
        if alts:
            stop_name = alts[-1]

    # Truncate stop name to fit before time with at least 1px spacing
    available_w = time_x - inner_left - CHAR_SPACING
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
    # Header left margin is exactly 1 pixel (inner_left)
    draw_text(inner_left, header_baseline, stop_name)
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
        # Right align single char into 2-char column
        if ident_col_chars == MIN_IDENT_CHARS and len(ident) == 1:
            pad = measure('X' * MIN_IDENT_CHARS) - measure(ident)
            draw_text(inner_left + pad, y, ident)
        else:
            draw_text(inner_left, y, ident)
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

    matrix.SwapOnVSync(off)


def run_loop(opts: argparse.Namespace):
    if not MATRIX_AVAILABLE:
        print("rgbmatrix library not available. Falling back to plain text output (developer mode).", file=sys.stderr)
        while True:
            rows = fd.fetch_stationboard(opts.stop, opts.limit * 4, transportations=None if opts.all else ['tram','train'])
            if opts.dest:
                nf = fd._normalize(opts.dest)
                rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
            rows.sort(key=lambda r: (r.get('mins',0) + (r.get('delay') or 0)))
            rows = rows[:opts.limit]
            for r in rows:
                print(fd.format_departure(r, opts.stop))
            print('-' * 40)
            time.sleep(opts.refresh)
        return
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
    if opts.limit_refresh_hz is not None:
        options.limit_refresh_rate_hz = opts.limit_refresh_hz
    else:
        options.limit_refresh_rate_hz = 120
    if opts.slowdown_gpio is not None:
        options.gpio_slowdown = opts.slowdown_gpio
    options.multiplexing = 0
    options.pixel_mapper_config = ""
    if opts.chain > 1:
        options.chain_length = opts.chain
    if opts.parallel > 1:
        options.parallel = opts.parallel

    matrix = RGBMatrix(options = options)

    running = True
    def handle_sig(signum, frame):  # noqa: D401, ANN001
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    renderer = Renderer(opts.cols * opts.chain, opts.rows * opts.parallel)

    while running:
        try:
            rows = fd.fetch_stationboard(opts.stop, opts.limit * 4, transportations=None if opts.all else ['tram','train'])
            if opts.dest:
                nf = fd._normalize(opts.dest)
                rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
            rows.sort(key=lambda r: (r.get('mins',0) + (r.get('delay') or 0)))
            rows = rows[:opts.limit]
            # draw_frame now handles preparation & header, just pass raw rows
            draw_frame(matrix, renderer, rows, opts.stop)
        except Exception as e:  # noqa: BLE001
            print(f"Error: {e}", file=sys.stderr)
        time.sleep(opts.refresh)


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
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    opts = parse_args(argv)
    run_loop(opts)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
