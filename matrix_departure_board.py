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
}

BITMAP = {ch: [[1 if c == '1' else 0 for c in row] for row in rows] for ch, rows in FONT.items()}
CHAR_W = 5
CHAR_H = 7
CHAR_SPACING = 1
LINE_SPACING = 1  # vertical space between rows (can tweak)

# Board size defaults (can override with CLI)
DEFAULT_ROWS = 64
DEFAULT_COLS = 128

# Layout constants
LINE_ID_DEST_GAP = 4
DEST_MINS_GAP = 3
RIGHT_MARGIN = 1
MIN_IDENT_CHARS = 2

class Renderer:
    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows

    def glyph_width(self, ch: str) -> int:  # monospaced here
        return CHAR_W

    def measure(self, text: str) -> int:
        w = 0
        for i, ch in enumerate(text):
            w += self.glyph_width(ch)
            if i != len(text) - 1:
                w += CHAR_SPACING
        return w

    def rows_capacity(self) -> int:
        line_height = CHAR_H + LINE_SPACING
        return self.rows // line_height

    def prepare_rows(self, rows: List[Dict[str, Any]], origin: str) -> List[Dict[str, str]]:
        cap = self.rows_capacity()
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
            mins_text = f"{mins}'"
            # compute width budget
            ident_w = self.measure('X' * ident_col_chars)
            digits = str(mins)
            digits_w = self.measure(digits)
            apostrophe_w = self.glyph_width("'")
            total_minutes_w = digits_w + CHAR_SPACING + apostrophe_w + RIGHT_MARGIN
            digits_start_x = self.cols - total_minutes_w
            dest_start_x = ident_w + LINE_ID_DEST_GAP
            max_dest_w = digits_start_x - DEST_MINS_GAP - dest_start_x
            # truncate dest
            draw_chars = []
            cur = 0
            for ch in dest:
                add = self.glyph_width(ch) if not draw_chars else CHAR_SPACING + self.glyph_width(ch)
                if cur + add > max_dest_w:
                    break
                draw_chars.append(ch)
                cur += add
            dest_draw = ''.join(draw_chars)
            out.append({
                'ident_display': ident_display,
                'ident_col_chars': str(ident_col_chars),
                'dest': dest_draw,
                'mins': str(mins),
            })
        return out

# Matrix specific drawing -----------------------------------------------------

def draw_frame(matrix: RGBMatrix, renderer: Renderer, prep_rows: List[Dict[str, str]]):  # type: ignore[name-defined]
    off = matrix.CreateFrameCanvas()
    line_height = CHAR_H + LINE_SPACING
    # time header at top-right, stop name truncated left (simple header)
    now_txt = datetime.now().strftime('%H:%M')
    r = renderer

    def draw_text(x: int, y: int, text: str):
        for i, ch in enumerate(text):
            bmp = BITMAP.get(ch, BITMAP[' '])
            for dy, brow in enumerate(bmp):
                for dx, bit in enumerate(brow):
                    if bit:
                        off.SetPixel(x+dx, y+dy, 255, 140, 0)
            x += CHAR_W
            if i != len(text) - 1:
                x += CHAR_SPACING

    # Header
    header_y = 0
    time_w = r.measure(now_txt)
    time_x = r.cols - time_w
    draw_text(time_x, header_y, now_txt)

    # Horizontal rule under header
    rule_y = CHAR_H + 0
    for x in range(r.cols):
        off.SetPixel(x, rule_y, 255, 140, 0)

    # Departure rows start below rule
    start_y = rule_y + 2
    for idx, row in enumerate(prep_rows):
        y = start_y + idx * line_height
        if y + CHAR_H > r.rows:
            break
        ident_col_chars = int(row['ident_col_chars'])
        ident_w = r.measure('X' * ident_col_chars)
        ident = row['ident_display']
        # right align ident in its column if short
        if ident_col_chars == MIN_IDENT_CHARS and len(ident) == 1:
            pad = r.measure('X' * MIN_IDENT_CHARS) - r.measure(ident)
            draw_text(pad, y, ident)
        else:
            draw_text(0, y, ident)
        dest_start_x = ident_w + LINE_ID_DEST_GAP
        draw_text(dest_start_x, y, row['dest'])
        # minutes right aligned with apostrophe at fixed board edge -1
        mins = row['mins']
        digits_w = r.measure(mins)
        apostrophe_x = r.cols - RIGHT_MARGIN - CHAR_W
        digits_start_x = apostrophe_x - CHAR_SPACING - digits_w
        draw_text(digits_start_x, y, mins)
        draw_text(apostrophe_x, y, "'")

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
    options.gpio_mapping = opts.gpio_mapping
    options.brightness = opts.brightness
    options.pwm_lsb_nanoseconds = 130
    options.pwm_dither_bits = 1
    options.limit_refresh_rate_hz = 120
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
            prepared = renderer.prepare_rows(rows, opts.stop)
            draw_frame(matrix, renderer, prepared)
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
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    opts = parse_args(argv)
    run_loop(opts)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
