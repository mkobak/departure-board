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
from typing import List, Dict, Any, Optional, Callable

import fetch_departures as fd
import threading
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

def draw_frame(off, matrix: RGBMatrix, renderer: Renderer, rows: List[Dict[str, Any]], origin: str):  # type: ignore[name-defined]
    """Draw a complete frame.

    off: off-screen canvas (re-used each frame)
    rows: departures (empty => blank list area)
    origin: stop name for header
    """
    # Clear (fill black) first – using direct pixel loops (fast enough for 128x64)
    for y in range(renderer.rows):
        for x in range(renderer.cols):
            off.SetPixel(x, y, 0, 0, 0)
    amber = (255, 140, 0)

    r = renderer

    # Layout constants:
    HEADER_BASELINE_Y = 2
    RULE_Y = HEADER_BASELINE_Y + CHAR_H + 3  # 2 + 7 + 3 = 12
    DEPARTURES_START_Y = RULE_Y + 1 + 4      # 12 + 1 + 4 = 17
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

    return matrix.SwapOnVSync(off)


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
    # Build stop choices (feel free to extend list here or later from config)
    stop_choices = ["Basel, Aeschenplatz", "Basel, Denkmal"]
    if opts.stop not in stop_choices:
        stop_choices.insert(0, opts.stop)

    # --- Simplified State Machine --------------------------------------------------
    current_index = stop_choices.index(opts.stop)  # active stop index
    header_stop = stop_choices[current_index]      # stop shown in header
    departures: List[Dict[str, Any]] = []          # last fetched departures for header_stop
    last_fetch_time = 0.0                          # timestamp of last successful fetch
    next_scheduled_fetch = 0.0                     # when to fetch (rotation delay, periodic refresh)
    fetch_interval = max(15.0, float(opts.refresh))  # periodic refresh (>=15s)
    rotate_fetch_delay = max(0.05, getattr(opts, 'rotate_fetch_delay', 0.5))
    encoder = None
    encoder_started_early = False
    last_rotation_accept = 0.0                     # debounce accepted rotation time
    rotation_min_interval = float(getattr(opts, 'rotate_min_interval', 0.08))

    rotation_queue: List[int] = []                 # accumulate raw deltas (optional future use)

    def schedule_fetch(delay: float = 0.0):
        nonlocal next_scheduled_fetch
        t = time.time() + delay
        if next_scheduled_fetch == 0.0 or t < next_scheduled_fetch:
            next_scheduled_fetch = t

    def _accept_rotation(direction: int):
        nonlocal current_index, header_stop, departures
        current_index = (current_index + (1 if direction > 0 else -1)) % len(stop_choices)
        header_stop = stop_choices[current_index]
        # Blank departures immediately – display will show empty area for half second
        departures = []
        schedule_fetch(rotate_fetch_delay)

    def _on_rotate(raw_delta: int):  # noqa: D401
        nonlocal last_rotation_accept
        now = time.time()
        if now - last_rotation_accept < rotation_min_interval:
            return  # debounce / noise filter
        last_rotation_accept = now
        direction = 1 if raw_delta > 0 else -1
        _accept_rotation(direction)

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

    renderer = Renderer(opts.cols * opts.chain, opts.rows * opts.parallel)

    # Rotary encoder integration (post-matrix init if not early) ----------------------
    if _HAVE_ENCODER and RotaryEncoder is not None and not getattr(opts, 'no_encoder', False) and not encoder_started_early:
        def _start_encoder():
            nonlocal encoder
            if opts.encoder_debug:
                print("[encoder] Delayed post-matrix init start", file=sys.stderr)
            time.sleep(0.25 if opts.encoder_delay is None else opts.encoder_delay)
            try:
                conflict_pins = {18,19,21,22,23,24}
                user_pins = {opts.enc_clk, opts.enc_dt, opts.enc_sw}
                if conflict_pins & user_pins:
                    print(f"[encoder] Warning: chosen pins {user_pins & conflict_pins} may be used by the RGB matrix HAT and could cause failures.", file=sys.stderr)
                encoder = RotaryEncoder(
                    pin_clk=opts.enc_clk,
                    pin_dt=opts.enc_dt,
                    pin_sw=opts.enc_sw,
                    on_rotate=_on_rotate,  # type: ignore[operator]
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

    # Fetch helper
    def fetch_rows(stop_name: str) -> List[Dict[str, Any]]:
        rows = fd.fetch_stationboard(stop_name, opts.limit * 4, transportations=None if opts.all else ['tram','train'])
        if opts.dest:
            nf = fd._normalize(opts.dest)
            rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
        rows.sort(key=lambda r: (r.get('mins',0) + (r.get('delay') or 0)))
        return rows[:opts.limit]

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

    # Single off-screen canvas reused (fix for CreateFrameCanvas spam)
    offscreen = matrix.CreateFrameCanvas()
    offscreen = draw_frame(offscreen, matrix, renderer, departures, header_stop)  # blank first frame

    running = True
    def _sig_handler(signum, frame):  # noqa: D401, ANN001
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        while running:
            now = time.time()
            # Fetch if scheduled
            if next_scheduled_fetch and now >= next_scheduled_fetch:
                try:
                    departures = fetch_rows(header_stop)
                    last_fetch_time = now
                except Exception as e:  # noqa: BLE001
                    print(f"[fetch] Error fetching departures for '{header_stop}': {e}", file=sys.stderr)
                finally:
                    next_scheduled_fetch = 0.0
                    next_periodic_refresh = now + fetch_interval
            # Periodic refresh if stale (even without rotation)
            if departures and now >= next_periodic_refresh:
                schedule_fetch(0.0)
                next_periodic_refresh = now + fetch_interval
            # Redraw every loop (lightweight) – header may change instantly on rotation
            offscreen = draw_frame(offscreen, matrix, renderer, departures, header_stop)
            # Compute dynamic sleep (shorter while we're waiting for a scheduled fetch soon)
            sleep_target = 0.1
            if next_scheduled_fetch:
                until_fetch = max(0.0, next_scheduled_fetch - time.time())
                sleep_target = min(sleep_target, max(0.02, until_fetch))
            time.sleep(sleep_target)
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
    # Rotary encoder options
    p.add_argument('--no-encoder', action='store_true', help='Disable rotary encoder even if library present')
    p.add_argument('--enc-clk', type=int, default=5, help='Rotary encoder CLK (A) GPIO (BCM numbering)')
    p.add_argument('--enc-dt', type=int, default=6, help='Rotary encoder DT (B) GPIO (BCM numbering)')
    p.add_argument('--enc-sw', type=int, default=26, help='Rotary encoder switch GPIO (BCM numbering)')
    p.add_argument('--enc-poll', action='store_true', help='Force polling mode instead of interrupt events')
    p.add_argument('--encoder-early', action='store_true', help='Initialize rotary encoder before RGBMatrix (try if normal init fails)')
    p.add_argument('--encoder-delay', type=float, default=0.0, help='Delay seconds before encoder init (early or delayed)')
    p.add_argument('--encoder-debug', action='store_true', help='Verbose encoder debug messages')
    p.add_argument('--rotate-fetch-delay', type=float, default=0.5,
                   help='Delay seconds after rotation before fetching new departures (immediate header update)')
    p.add_argument('--rotate-min-interval', type=float, default=0.08,
                   help='Minimum seconds between accepted detents (debounce at app level)')
    p.add_argument('--enc-steps-per-detent', type=int, default=2,
                   help='Quadrature steps that amount to one detent for your encoder (1,2,4 typical)')
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    opts = parse_args(argv)
    run_loop(opts)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
